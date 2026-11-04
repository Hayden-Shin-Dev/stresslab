"""Gold-only, fixed annual walk-forward comparison; no cloud/service writes."""
import os,json,hashlib
from pathlib import Path
import numpy as np
import pandas as pd
from catboost import CatBoostRegressor
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import Ridge
ROOT=Path(os.environ.get('STRESSLAB_AUDIT_ROOT',Path(__file__).resolve().parents[1]))
OUT=ROOT/'reports/gold_quantile_benchmark_20261103'
SHOCKS=['shock_fx','shock_rate','shock_oil','shock_vix']
STATE=['market_trend20','market_vol20','fx_trend20','rate_level','oil_level','vix_level','kr3y_level','kr3y_change20']
EXTRA=['asset_trend5','asset_trend20','asset_vol20','asset_vol60','volume_ratio20','drawdown60']
FEATURES=STATE+EXTRA+SHOCKS

def build(g, require_outcome=True):
    dates=pd.DatetimeIndex(sorted(pd.to_datetime(g.trading_date).unique()));frames=[]
    for asset,z in g.groupby('asset_id'):
        z=z.copy();z.index=pd.to_datetime(z.trading_date);z=z.reindex(dates)
        r=z.close.pct_change(fill_method=None)*100;mr=z.kospi_close.pct_change(fill_method=None)*100
        x=pd.DataFrame(index=dates);x['asset']=asset
        for horizon in [5,20]:x['asset_trend'+str(horizon)]=z.close.pct_change(horizon,fill_method=None)*100
        for horizon in [20,60]:x['asset_vol'+str(horizon)]=r.rolling(horizon).std()
        x['volume_ratio20']=z.volume/z.volume.rolling(20).mean();x['drawdown60']=(z.close/z.close.rolling(60).max()-1)*100
        x['market_trend20']=z.kospi_close.pct_change(20,fill_method=None)*100;x['market_vol20']=mr.rolling(20).std()
        x['fx_trend20']=z.usdkrw.pct_change(20,fill_method=None)*100
        for dest,source in [('rate_level','us_treasury_10y'),('oil_level','wti'),('vix_level','vix'),('kr3y_level','korea_3y')]:x[dest]=z[source]
        x['kr3y_change20']=(z.korea_3y-z.korea_3y.shift(20))*100
        for name,col,relative,mult in [('shock_fx','usdkrw',True,100),('shock_rate','us_treasury_10y',False,100),('shock_oil','wti',True,100),('shock_vix','vix',False,1)]:
            x[name]=(z[col].shift(-5)/z[col]-1)*mult if relative else (z[col].shift(-5)-z[col])*mult
        ok=z.quality_status.eq('valid')&z.close.gt(0)&z.volume.gt(0)&z.is_mock.eq(False)
        x['target']=((z.close.shift(-5)/z.close-1)*100).where(ok.rolling(6).sum().shift(-5).eq(6))
        x['scale']=np.sqrt((x.asset_vol20**2+x.asset_vol60**2)/2*5).clip(lower=.1)
        x['end_date']=pd.Series(dates,index=dates).shift(-5);x['date']=dates
        frames.append(x)
    allrows=pd.concat(frames,ignore_index=True)
    a=allrows[allrows.asset.eq('005930')].set_index('date');b=allrows[allrows.asset.eq('005380')].set_index('date')
    portfolio=a.copy();portfolio[FEATURES]=(a[FEATURES]+b[FEATURES])/2
    portfolio['target']=(a.target+b.target)/2;portfolio['asset']='portfolio'
    prices=g.pivot(index='trading_date',columns='asset_id',values='close').sort_index()[['005930','005380']]
    daily=(prices.pct_change(fill_method=None)*100).mean(axis=1,skipna=False);daily.index=pd.to_datetime(daily.index)
    portfolio['scale']=np.sqrt((daily.rolling(20).var()+daily.rolling(60).var())/2*5).reindex(portfolio.index).clip(lower=.1)
    portfolio=portfolio.reset_index();assert np.nanmax(abs(portfolio.target.to_numpy()-(a.target+b.target).to_numpy()/2))<1e-10
    required=FEATURES+['target','scale','end_date'] if require_outcome else STATE+EXTRA+['scale']
    return pd.concat([allrows,portfolio],ignore_index=True).replace([np.inf,-np.inf],np.nan).dropna(subset=required)

def record(test,q,model,fold,train,cal):
    q=np.sort(q,axis=1);lo,med,hi=q.T;y=test.target.to_numpy();volcut=train.market_vol20.quantile([1/3,2/3]).to_numpy()
    regime=np.select([test.market_vol20<=volcut[0],test.market_vol20<=volcut[1]],['low','medium'],default='high')
    severity=np.select([(test.shock_fx.abs()<=1)&(test.shock_rate.abs()<=25),(test.shock_fx.abs()<=3)&(test.shock_rate.abs()<=75)],['ordinary','elevated'],default='extreme')
    out=pd.DataFrame(dict(date=test.date.to_numpy(),asset=test.asset.to_numpy(),fold=fold,model=model,actual=y,median=med,q05=lo,q95=hi,width=hi-lo,
        coverage=((y>=lo)&(y<=hi)).astype(float),mae=abs(y-med),sq_error=(y-med)**2,
        interval_score=hi-lo+20*np.maximum(lo-y,0)+20*np.maximum(y-hi,0),pinball05=np.maximum(.05*(y-lo),-.95*(y-lo)),
        breach=(y<lo).astype(float),miss_size=np.maximum(lo-y,0),forced_width5_coverage=(abs(y-med)<=2.5).astype(float),
        regime=regime,shock_group=severity,train_n=len(train),cal_n=len(cal)))
    # Sparse, disjoint historical windows; only state regime and fx/rate proximity.
    hist=train.iloc[::6];support=[]
    for _,t in test.iterrows():
        samevol=(hist.market_vol20<=volcut[0]) if t.market_vol20<=volcut[0] else ((hist.market_vol20>volcut[0])&(hist.market_vol20<=volcut[1])) if t.market_vol20<=volcut[1] else (hist.market_vol20>volcut[1])
        support.append(int((samevol&(np.sign(hist.market_trend20)==np.sign(t.market_trend20))&(abs(hist.shock_fx-t.shock_fx)<=max(.5,abs(t.shock_fx)*.25))&(abs(hist.shock_rate-t.shock_rate)<=max(10,abs(t.shock_rate)*.25))).sum()))
    out['support_windows']=support;return out

def main():
    OUT.mkdir(parents=True,exist_ok=True);path=ROOT/'exports/seongjin_gold_v1_1/gold_stress_daily.parquet';g=pd.read_parquet(path)
    protocol={'source':'Gold v1.1 only; no legacy panel', 'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
        'target':'simple return close[t+5]/close[t]-1; portfolio equal-weight initial values, no rebalancing',
        'features':FEATURES,'split':'annual 2023-2026; train ends before previous calendar year; previous year disjoint calibration; 20 calendar-day embargo on label end; all-year walk-forward',
        'models':['volatility','ridge','catboost_quantile','catboost_calibrated'],'params':{'iterations':250,'depth':4,'learning_rate':.04,'loss':'MultiQuantile:alpha=0.05,0.5,0.95','seed':20261103},
        'target_goal':'90% coverage AND total width <=5 percentage points; no forced narrowing; fixed-width diagnostic separate',
        'blind':False,'publication_warning':'Gold publication timestamps null; embargo proxy, not certified point-in-time. Do not approve production even if score passes.',
        'portfolio_warning':'Direct fixed 50/50 portfolio quantiles; marginal quantiles not summed. Arbitrary weights and full joint scenario distribution not validated.',
        'selection':'No final test hyperparameter selection; report all candidates; sparse groups <30 flagged',
        'confidence':'Conditional reconstruction with observed future shocks; not causal or shock occurrence forecast'}
    (OUT/'protocol.json').write_text(json.dumps(protocol,ensure_ascii=False,indent=2),encoding='utf8')
    data=build(g);rows=[];counts=[];stability=[]
    for asset,frame in data.groupby('asset'):
        frame=frame.sort_values('date')
        for year in [2023,2024,2025,2026]:
            cut=pd.Timestamp(year=year,month=1,day=1);calcut=pd.Timestamp(year=year-1,month=1,day=1)
            train=frame[frame.end_date<calcut-pd.Timedelta(days=20)]
            cal=frame[(frame.date>=calcut)&(frame.end_date<cut-pd.Timedelta(days=20))].iloc[::6]
            test=frame[(frame.date>=cut)&(frame.date< pd.Timestamp(year=year+1,month=1,day=1))].iloc[::6]
            counts.append(dict(asset=asset,year=year,train=len(train),cal=len(cal),test=len(test)))
            if len(train)<250 or len(cal)<30 or len(test)==0:continue
            assert train.end_date.max()<cal.date.min() and cal.end_date.max()<test.date.min()
            tx=train[FEATURES].to_numpy();cx=cal[FEATURES].to_numpy();qx=test[FEATURES].to_numpy()
            y=train.target/train.scale;cy=cal.target/cal.scale;scale=test.scale.to_numpy()[:,None]
            center=np.median(y);res=cy-center;q=(center+np.quantile(res,[.05,.5,.95]))[None,:]*scale
            rows.append(record(test,q,'volatility',year,train,cal))
            ridge=make_pipeline(StandardScaler(),Ridge(alpha=30)).fit(tx,y);res=cy-ridge.predict(cx)
            q=(ridge.predict(qx)[:,None]+np.quantile(res,[.05,.5,.95])[None,:])*scale
            rows.append(record(test,q,'ridge',year,train,cal))
            model=CatBoostRegressor(iterations=250,depth=4,learning_rate=.04,loss_function='MultiQuantile:alpha=0.05,0.5,0.95',random_seed=20261103,thread_count=2,verbose=False,allow_writing_files=False)
            model.fit(tx,y);cq=np.sort(model.predict(cx),axis=1);tq=np.sort(model.predict(qx),axis=1)
            rows.append(record(test,tq*scale,'catboost_quantile',year,train,cal))
            errors=np.maximum(cq[:,0]-cy.to_numpy(),cy.to_numpy()-cq[:,2]);correction=max(0,float(np.quantile(errors,min(1,np.ceil((len(errors)+1)*.9)/len(errors)),method='higher')))
            adjusted=tq.copy();adjusted[:,0]-=correction;adjusted[:,2]+=correction
            rows.append(record(test,adjusted*scale,'catboost_calibrated',year,train,cal))
            if asset=='portfolio':
                short=train[train.date>=calcut-pd.DateOffset(years=8)]
                alt=CatBoostRegressor(iterations=250,depth=4,learning_rate=.04,loss_function='MultiQuantile:alpha=0.05,0.5,0.95',random_seed=20261103,thread_count=2,verbose=False,allow_writing_files=False)
                alt.fit(short[FEATURES],short.target/short.scale);aq=np.sort(alt.predict(qx),axis=1)*scale
                for j,(_,t) in enumerate(test.iterrows()):stability.append(dict(date=t.date,fold=year,median_long=tq[j,1]*scale[j,0],median_recent=aq[j,1],delta=abs(aq[j,1]-tq[j,1]*scale[j,0]),sign_flip=bool(np.sign(aq[j,1])!=np.sign(tq[j,1]))))
            print(asset,year,len(train),len(test),flush=True)
        # Persist progress and permit inspection without rerunning finished work.
        pd.DataFrame(counts).to_csv(OUT/'sample_counts.csv',index=False)
        if rows:pd.concat(rows,ignore_index=True).to_parquet(OUT/'predictions.parquet',index=False)
    r=pd.concat(rows,ignore_index=True);pd.DataFrame(stability).to_csv(OUT/'training_stability.csv',index=False)
    aggregate(r)

def aggregate(r):
    scores=['coverage','width','mae','interval_score','pinball05','breach','miss_size','forced_width5_coverage']
    summaries=[]
    for scope,x in [('portfolio',r[r.asset.eq('portfolio')]),('stocks',r[~r.asset.eq('portfolio')])]:
        for period,z in [('all',x),('recent3m',x[x.date>='2026-07-30'])]:
            for model,p in z.groupby('model'):
                row=p[scores].mean().to_dict();row.update(scope=scope,period=period,model=model,n=len(p),dates=p.date.nunique(),rmse=np.sqrt(p.sq_error.mean()));summaries.append(row)
    pd.DataFrame(summaries).to_csv(OUT/'metrics.csv',index=False)
    grouped=r.groupby(['asset','model','regime','shock_group']);table=grouped[scores+['support_windows']].mean();table['n']=grouped.size()
    table['meets_descriptive_target']=(table.coverage>=.88)&(table.width<=5)&(table.n>=30)
    table['approval']='research_only_publication_unverified';table.reset_index().to_csv(OUT/'scenario_reliability.csv',index=False)
    print(pd.DataFrame(summaries).to_string(index=False),flush=True)

if __name__=='__main__':main()
