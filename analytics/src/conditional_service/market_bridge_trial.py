"""Quarterly out-of-time KOSPI forecasts linked to stock stress regressions."""
import json,hashlib
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits
from .core import STATE,ASSET,SHOCKS
from .preopen_method_trial import SOURCE,LEVELS,metrics

OUT=Path('reports/market_bridge_trial_20261105');F=STATE+ASSET+SHOCKS

def regress(z,t,cols,y):
    s=StandardScaler().fit(z[cols]);m=Ridge(alpha=100).fit(s.transform(z[cols]),y)
    return m.predict(s.transform(t[cols])),m,s

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    inputs=[Path('reports/service_scope_20261105/corrected_features.parquet'),Path('reports/service_scope_20261105/corrected_daily_input.parquet'),Path('reports/service_scope_20261105/final_service_bundle.joblib')]
    hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}
    g=pd.read_parquet(inputs[1]);x=pd.read_parquet(inputs[0]).dropna(subset=F+['target','end_date','label_known_by']).copy();x['known']=pd.to_datetime(x.label_known_by,utc=True)
    market=g[['trading_date','kospi_close']].drop_duplicates().sort_values('trading_date').rename(columns={'trading_date':'date'})
    market['date']=pd.to_datetime(market.date);assert not market.date.duplicated().any()
    lp=100*np.log(market.kospi_close);r=lp.diff();vol=np.sqrt(r.pow(2).ewm(alpha=.06,adjust=False).mean()).clip(lower=.05)
    market['ret20_z']=lp.diff(20)/(vol*np.sqrt(20));market['ret1_z']=r/vol
    market['vol_ratio']=r.rolling(5).std()/r.rolling(60).std();market['scale_m']=vol*np.sqrt(5)
    market['market_actual']=(market.kospi_close.shift(-5)/market.kospi_close-1)*100;market['end_m']=market.date.shift(-5)
    # Source preopen information is usable only after its decision timestamp.
    ew=pd.read_csv(SOURCE/'research/results/project_b_ewy_inputs_v123/features.csv')
    us=pd.read_csv(SOURCE/'research/results/project_c_preopen_v9/preopen_features.csv')
    ex=ew[['origin','decision_utc','ewy_move_log_pct']].merge(us[['origin','us_move_log_pct']],on='origin',validate='one_to_one');ex['available']=pd.to_datetime(ex.decision_utc,utc=True)
    market['cutoff']=pd.to_datetime(market.date,utc=True)+pd.Timedelta(hours=6,minutes=30)
    market=pd.merge_asof(market.sort_values('cutoff'),ex.sort_values('available'),left_on='cutoff',right_on='available',direction='backward',tolerance=pd.Timedelta(days=4))
    assert (market.available.dropna()<=market.loc[market.available.notna(),'cutoff']).all()
    market['us_z']=market.us_move_log_pct/(market.scale_m/np.sqrt(5));market['ewy_z']=market.ewy_move_log_pct/(market.scale_m/np.sqrt(5))
    arms={'gold_market':['ret20_z','vol_ratio'],'market_us_ewy':['ret20_z','vol_ratio','ret1_z','us_z','ewy_z']}
    forecasts=[];audit=[]
    for q in pd.period_range('2010Q1',market.date.max().to_period('Q'),freq='Q'):
        start=q.start_time;end=(q+1).start_time
        for arm,cols in arms.items():
            z=market[(market.end_m<start)].dropna(subset=cols+['market_actual','scale_m']).tail(2520)
            t=market[(market.date>=start)&(market.date<end)].dropna(subset=cols+['market_actual','scale_m'])
            if len(z)<1000 or t.empty:continue
            assert z.end_m.max()<start
            y=100*np.log1p(z.market_actual/100)/z.scale_m;loc,_,_=regress(z,t,cols,y)
            base=np.quantile(y,LEVELS)-y.mean();v=100*np.expm1((loc[:,None]+base)*t.scale_m.to_numpy()[:,None]/100)
            out=t[['date','market_actual','end_m','available','cutoff']].copy();out['market_prediction']=np.median(v,axis=1);out['lo']=np.quantile(v,.05,axis=1);out['hi']=np.quantile(v,.95,axis=1);out['arm']=arm;out['fit_cutoff']=start;forecasts.append(out)
            audit.append(dict(arm=arm,quarter=str(q),train_n=len(z),train_label_end=str(z.end_m.max()),test_start=str(t.date.min())))
    mf=pd.concat(forecasts);mf.to_parquet(OUT/'market_forecasts.parquet',index=False);pd.DataFrame(audit).to_csv(OUT/'market_splits.csv',index=False)
    ref=pd.read_parquet('reports/three_model_intervals_20261105/points.parquet');ref=ref[ref.model.eq('catboost')];keys=ref[['date','asset']];assets=set(ref.asset)
    points=[];splits=[];scenarios=[]
    for arm in arms:
        d=x.merge(mf[mf.arm.eq(arm)][['date','market_prediction','market_actual']],on='date',validate='many_to_one')
        cache={}
        for q in pd.period_range('2022Q1',ref.date.max().to_period('Q'),freq='Q'):
            start=q.start_time;end=(q+1).start_time
            train=d[(d.end_date<start)&(d.known<start.tz_localize('UTC'))]
            test=d[(d.date>=start)&(d.date<end)&d.asset.isin(assets)]
            for a,t in test.groupby('asset'):
                z=train[train.asset.eq(a)].sort_values('date').tail(2520)
                if len(z)<250:continue
                beta=float(np.cov(z.market_actual,z.target,ddof=0)[0,1]/np.var(z.market_actual))
                for variant in ['unlinked','forecast_feature','forecast_anchor']:
                    cols=F+(['market_prediction'] if variant=='forecast_feature' else [])
                    offset=beta if variant=='forecast_anchor' else 0.
                    center,m,s=regress(z,t,cols,z.target-offset*z.market_prediction);center+=offset*t.market_prediction.to_numpy()
                    zz=t[cols].copy();zz[SHOCKS]=0;zero=m.predict(s.transform(zz))+offset*t.market_prediction.to_numpy()
                    contribution=t[SHOCKS].to_numpy()*(m.coef_[[cols.index(v) for v in SHOCKS]]/s.scale_[[cols.index(v) for v in SHOCKS]])
                    np.testing.assert_allclose(center-zero,contribution.sum(axis=1),atol=1e-8)
                    past=cache.get((a,variant),[]);cal=pd.concat(past) if past else pd.DataFrame()
                    if len(cal):cal=cal[(cal.date>=start-pd.DateOffset(years=1))&(cal.end_date<start)&(cal.known<start.tz_localize('UTC'))]
                    if len(cal)>=60:
                        base=np.quantile(cal.residual,[.05,.1,.9,.95]);t=t.copy()
                        for level,lo,hi in [(.8,1,2),(.9,0,3)]:
                            v=t[['date','asset','target']].rename(columns={'target':'actual'}).copy();v['model']=arm+'__'+variant;v['level']=level;v['center']=center;v['lo']=center+base[lo]*t.scale.to_numpy();v['hi']=center+base[hi]*t.scale.to_numpy();v=v.merge(keys,on=['date','asset'],validate='one_to_one');points.append(v)
                        splits.append(dict(arm=arm,variant=variant,asset=a,quarter=str(q),n=len(z),cal_n=len(cal),beta=beta,train_end=str(z.end_date.max())))
                        wanted=t.merge(keys,on=['date','asset'],validate='one_to_one')
                        for rr in wanted.itertuples():
                            i=pd.Index(t.date).get_loc(rr.date)
                            scenarios.append(dict(date=rr.date,asset=a,model=arm+'__'+variant,actual=rr.target,market_prediction=rr.market_prediction,market_component=offset*rr.market_prediction,zero_shock_return=zero[i],center=center[i],**{v:contribution[i,j] for j,v in enumerate(SHOCKS)}))
                    c=t[['date','end_date','known']].copy();c['residual']=(t.target.to_numpy()-center)/t.scale.to_numpy();cache.setdefault((a,variant),[]).append(c)
            print('stocks',arm,q,flush=True)
    p=pd.concat(points);shared=None
    for _,v in p.groupby('model'):
        k=set(zip(v.date,v.asset));shared=k if shared is None else shared&k
    p=p[[k in shared for k in zip(p.date,p.asset)]];assert not p.duplicated(['date','asset','model','level']).any()
    p.to_parquet(OUT/'predictions.parquet',index=False);pd.DataFrame(splits).to_csv(OUT/'splits.csv',index=False);pd.DataFrame(scenarios).to_parquet(OUT/'decomposition.parquet',index=False)
    rows=[dict(period=period,model=m,level=l,**metrics(v)) for period,z in [('all',p),('2025_2026',p[p.date.dt.year>=2025])] for (m,l),v in z.groupby(['model','level'])]
    pd.DataFrame(rows).to_csv(OUT/'metrics.csv',index=False)
    pd.DataFrame([dict(asset=a,model=m,level=l,**metrics(v)) for (a,m,l),v in p.groupby(['asset','model','level'])]).to_csv(OUT/'per_asset.csv',index=False)
    # Fixed common dates also evaluate the market predictor itself.
    mp=mf[mf.date.isin(p.date.unique())].rename(columns={'market_actual':'actual','market_prediction':'center'});mp['level']=.9
    pd.DataFrame([dict(model=m,**metrics(v.assign(asset='KOSPI'))) for m,v in mp.groupby('arm')]).to_csv(OUT/'market_metrics.csv',index=False)
    pairs=[];rng=np.random.default_rng(20261105)
    for arm in arms:
        b=p[(p.model==arm+'__unlinked')&(p.level==.9)]
        for var in ['forecast_feature','forecast_anchor']:
            z=b.merge(p[(p.model==arm+'__'+var)&(p.level==.9)],on=['date','asset'],suffixes=('_ref','_new'),validate='one_to_one');np.testing.assert_allclose(z.actual_ref,z.actual_new)
            diff=(abs(z.actual_ref-z.center_ref)-abs(z.actual_new-z.center_new)).groupby(z.date).mean().sort_index().to_numpy();n=len(diff);ix=(rng.integers(0,n,(2000,int(np.ceil(n/4)),1))+np.arange(4)[None,None,:])%n;draws=diff[ix.reshape(2000,-1)[:,:n]].mean(1)
            pairs.append(dict(arm=arm,variant=var,mae_improvement=float(diff.mean()),ci_low=float(np.quantile(draws,.025)),ci_high=float(np.quantile(draws,.975))))
    pd.DataFrame(pairs).to_csv(OUT/'paired_ci.csv',index=False)
    assert all(hashlib.sha256(Path(k).read_bytes()).hexdigest()==v for k,v in hashes.items())
    (OUT/'protocol.json').write_text(json.dumps(dict(shared_n=len(shared),features=F,source_hashes=hashes,market_method='B134 Ridge100 and empirical normalized-return distribution; trained on Gold KOSPI; gold_market uses Gold only, optional US/EWY asof KRX close, not next-morning data',timing='Quarterly OOS market predictions for every stock training/calibration/test row. Matured labels only. Market actual only used to estimate historical beta; never inference input.',anchor='Train residual target = stock actual - beta * OOS market forecast. Not actual future market subtraction. All four shocks retained; contributions equal model difference.',limitations='Repeated development evaluation. US/EWY availability uses source assumed market clocks, not certified receipt. Not a no-shock counterfactual. Previous-year OOS residual intervals, overlapping rows are not independent events.',azure_gold_operating_model_changed=False),indent=2))
    print(pd.DataFrame(rows).query("period=='all' and level==0.9").to_string(index=False));print(pd.DataFrame(pairs).to_string(index=False))

if __name__=='__main__':
    with threadpool_limits(limits=2):main()
