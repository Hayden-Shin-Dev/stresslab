"""Frozen local audit: search utility and conditional risk; never deploys.

Official KRX/ECOS/FRED panel only. Previously examined dates are not blind.
Uses the existing Ridge implementation and reports every preregistered variant.
"""
import sys, json, hashlib, os
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler

ROOT = Path(os.environ.get('STRESSLAB_AUDIT_ROOT', Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(ROOT))
if (Path(__file__).parent/'reference').exists():
    sys.path.insert(0, str(Path(__file__).parent/'reference'))
from stresslab.config import STATES, SHOCKS
from stresslab.point_in_time_daily import windows, PerAssetRidge
from stresslab.models import pct

OUT = ROOT/'reports/search_stress_validation_20261103'
S = ['s_'+s for s in SHOCKS]
E = ['kr3y_level', 'kr3y_change20_bp']
SPECS = {'shock_only': S, 'state_ridge': S+STATES,
         'state_ecos_ridge': S+STATES+E, 'volatility': S}


def metrics(actual, draws):
    lo, mid, hi = np.quantile(draws, [.05,.5,.95], axis=1)
    es = np.array([d[d <= q].mean() for d,q in zip(draws,lo)])
    return pd.DataFrame({'actual':actual, 'median':mid, 'q05':lo, 'q95':hi, 'es05':es,
        'mae':abs(actual-mid), 'squared_error':(actual-mid)**2,
        'coverage':((actual>=lo)&(actual<=hi)).astype(float), 'width':hi-lo,
        'interval_score':hi-lo+20*np.maximum(lo-actual,0)+20*np.maximum(actual-hi,0),
        'pinball05':np.maximum(.05*(actual-lo),-.95*(actual-lo)),
        'var_breach':(actual<lo).astype(float), 'shortfall_beyond_var':np.maximum(lo-actual,0)})


def select(order, starts, ends, k=20):
    selected=[]
    for i in order:
        if all(ends[i] < starts[j] or starts[i] > ends[j] for j in selected):
            selected.append(int(i))
        if len(selected)==k:break
    return np.array(selected,dtype=int)


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    panel_path=ROOT/'reports/official20_20261102/official_panel.parquet'
    gold_path=ROOT/'exports/seongjin_gold_v1_1/gold_stress_daily.parquet'
    p=pd.read_parquet(panel_path).sort_values('date').reset_index(drop=True)
    g=pd.read_parquet(gold_path)
    w=windows(p,True)
    w['kr3y_level']=p.kr3y
    w['kr3y_change20_bp']=(p.kr3y-p.kr3y.shift(20))*100
    assets=sorted(g.asset_id.unique())
    for a in assets:
        price=p[a]; r=100*np.log(price/price.shift(1))
        w['scale_'+a]=np.sqrt((r.rolling(20).var()+r.rolling(60).var())/2*5)
        quality=g[g.asset_id.eq(a)].set_index('trading_date').quality_status
        quality.index=pd.to_datetime(quality.index)
        good=price.gt(0)&pd.Series(quality.reindex(p.date).eq('valid').to_numpy())
        if 'bad_'+a in p:good &= ~p['bad_'+a].fillna(True)
        good=good.rolling(6).sum().shift(-5).eq(6)
        w['y_'+a]=(100*np.log(price.shift(-5)/price)).where(good)
    previous=pd.read_parquet(ROOT/'reports/official20_20261102/predictions.parquet')
    test_dates=sorted(pd.to_datetime(previous.date.unique()))
    # Disjoint calibration outcome windows, fixed without test performance feedback.
    cal_pool=w[(w.date>='2020-01-01') & (w.label_schedule_not_before<pd.Timestamp('2023-01-01',tz='Asia/Seoul'))]
    cal_ids=select(range(len(cal_pool)),cal_pool.date.to_numpy(),cal_pool.end_date.to_numpy(),10000)
    cal_dates=set(cal_pool.iloc[cal_ids].date)
    protocol={'blind':False,'period':'previously examined 2023-2026 dates',
      'train':'label_schedule_not_before < 2020-01-01 KST',
      'calibration':'2020-2022 nonoverlapping five-session windows; labels available by proxy before 2023',
      'test':'same pre-existing 184 evaluation dates, same eligible rows across all model variants',
      'models':SPECS,'new_algorithm':False,'sample_rule':'positive prices; six Gold valid rows; no audited KRX-return mismatch inside target window',
      'search':'six released daily states; standardized distance; 20% pool/min120; no user shocks in first stage',
      'search_controls':['recent nonoverlapping windows','10 deterministic random selections'],
      'heldout_search_checks':['60-session KOSPI drawdown','daily declining share of available selected20 stocks, not KOSPI-wide'],
      'publication':'schedule proxy only; Gold publication timestamps null; historical data vintages not certified',
      'shock_alignment':'existing official-panel previous-observation endpoints retained; not exact intraday synchronous shocks',
      'scope':'local only; no Azure writes; no model promotion; current20 survivorship bias remains',
      'sources':{str(x.relative_to(ROOT)):hashlib.sha256(x.read_bytes()).hexdigest() for x in [panel_path,gold_path]}}
    (OUT/'protocol.json').write_text(json.dumps(protocol,ensure_ascii=False,indent=2),encoding='utf8')
    # Independent-of-search observed state checks. No future returns used in distances.
    w['drawdown60']=(p.kospi/p.kospi.rolling(60).max()-1)*100
    rr=p[assets].pct_change(fill_method=None)
    w['breadth20']=rr.lt(0).sum(axis=1)/rr.notna().sum(axis=1).replace(0,np.nan)
    w.loc[rr.notna().sum(axis=1)<10,'breadth20']=np.nan
    search=[]; replay_ids={}; overlap=[]
    required=S+STATES+E+['scale_kospi']
    common=w.dropna(subset=required)
    high_cut=common.loc[common.label_schedule_not_before<pd.Timestamp('2020-01-01',tz='Asia/Seoul'),'kospi_vol20'].quantile(.8)
    for date in test_dates:
        query=common[common.date.eq(date)]
        if query.empty:continue
        h=common[common.label_schedule_not_before<pd.Timestamp(date,tz='Asia/Seoul')].reset_index(drop=True)
        assert (h.end_date<date).all()
        scaler=StandardScaler().fit(h[STATES]);x=scaler.transform(h[STATES]);q=scaler.transform(query[STATES])[0]
        distances=np.mean((x-q)**2,axis=1);order=np.argsort(distances,kind='stable')
        count=min(len(h),max(120,int(np.ceil(.2*len(h)))))
        pool=order[:count];starts=h.date.to_numpy();ends=h.end_date.to_numpy()
        chosen=select(order,starts,ends)
        plans={'state':chosen,'recent':select(np.arange(len(h)-1,-1,-1),starts,ends)}
        for seed in range(10):plans['random_'+str(seed)]=select(np.random.default_rng(seed+20261103).permutation(len(h)),starts,ends)
        for method,ids in plans.items():
            hs=h.iloc[ids]
            row={'date':date,'method':method,'state_distance':float(np.sqrt(distances[ids]).mean()),'n':len(ids)}
            for f in ['drawdown60','breadth20']:
                scale=h[f].std();row[f+'_distance']=float(abs(hs[f]-query[f].iloc[0]).mean()/scale) if scale>0 else np.nan
            search.append(row)
        for label,trend_delta,vol_ratio in [('small',.1,1.01),('large',-3,1.5)]:
            changed=query[STATES].copy();changed['kospi_trend20']+=trend_delta;changed['kospi_vol20']*=vol_ratio
            z=scaler.transform(changed)[0];d=np.mean((x-z)**2,axis=1);new_order=np.argsort(d,kind='stable')
            new_pool=new_order[:count];new_cases=select(new_order,starts,ends)
            overlap.append({'date':date,'change':label,'pool_overlap':len(set(pool)&set(new_pool))/len(pool),
                'case_overlap':len(set(chosen)&set(new_cases))/len(chosen)})
        # Both replay methods use identical shock distance and event exclusion rules.
        shock_scaler=StandardScaler().fit(h[S].div(h.scale_kospi.clip(lower=.05),axis=0))
        sx=shock_scaler.transform(h[S].div(h.scale_kospi.clip(lower=.05),axis=0))
        sq=shock_scaler.transform(query[S].div(query.scale_kospi.clip(lower=.05),axis=0))[0]
        sd=((sx-sq)**2).mean(axis=1)
        for method,eligible in [('shock_replay',np.arange(len(h))),('state_shock_replay',pool)]:
            rank=sorted(eligible,key=lambda i:(sd[i],distances[i],int(i)))
            ids=select(rank,starts,ends,12)
            replay_ids[(date,method)]=h.iloc[ids].copy()
    pd.DataFrame(search).to_csv(OUT/'search_checks.csv',index=False)
    pd.DataFrame(overlap).to_csv(OUT/'search_stability.csv',index=False)
    records=[];counts=[];portfolio_records=[];sensitivity=[];event_dependence=[]
    for a in assets+['portfolio']:
        aa=['005930','005380'] if a=='portfolio' else [a]
        good=common.dropna(subset=['scale_'+s for s in aa]+['y_'+s for s in aa])
        train=good[good.label_schedule_not_before<pd.Timestamp('2020-01-01',tz='Asia/Seoul')]
        cal=good[good.date.isin(cal_dates)];test=good[good.date.isin(test_dates)]
        counts.append({'asset':a,'train':len(train),'cal':len(cal),'test':len(test),'eligible':len(train)>=250 and len(cal)>=30 and len(test)>=30})
        if not counts[-1]['eligible']:continue
        actual=pct(test[['y_'+s for s in aa]].to_numpy()).mean(axis=1)
        for name,features in SPECS.items():
            m=PerAssetRidge(aa,features,'volatility' if name=='volatility' else 'ridge').fit({s:train for s in aa}).calibrate(cal)
            draws=pct(m.draws(test)).mean(axis=2)
            frame=metrics(actual,draws);frame['date']=test.date.to_numpy();frame['model']=name;frame['asset']=a
            frame['high_vol']=test.kospi_vol20.to_numpy()>=high_cut
            records.append(frame)
            if a=='portfolio' and name!='volatility':
                # Same state and evaluation amounts; only shocks vary. No accuracy claim for hypothetical conditions.
                q=test.tail(1).copy();base_q=q.copy()
                for fx,rate in [(0,0),(2,50),(5,100),(10,200),(-5,-100)]:
                    z=base_q.copy();z['s_usdkrw']=float(fx);z['s_us_treasury_10y']=float(rate);z['s_wti']=0.0;z['s_vix']=0.0
                    d=pct(m.draws(z)).mean(axis=2)[0]
                    entry={'model':name,'date':str(z.date.iloc[0].date()),'fx_pct':fx,'us_rate_bp':rate,
                       'median_pct':float(np.median(d)),'p05':float(np.quantile(d,.05)),'p95':float(np.quantile(d,.95)),
                       'median_krw_100m':float(np.median(d)*1_000_000),
                       'training_joint_at_least_abs':int(((train.s_usdkrw.abs()>=abs(fx))&(train.s_us_treasury_10y.abs()>=abs(rate))).sum())}
                    sensitivity.append(entry)
        # Replay comparisons share identical valid cases for both selected stocks.
        for method in ['shock_replay','state_shock_replay']:
            for i,(_,q) in enumerate(test.iterrows()):
                h=replay_ids.get((q.date,method))
                if h is None:continue
                h=h.dropna(subset=['y_'+s for s in aa])
                if len(h)<5:continue
                d=pct(h[['y_'+s for s in aa]].to_numpy()).mean(axis=1)
                r=metrics(np.array([actual[i]]),d[None,:]);r['date']=q.date;r['asset']=a;r['model']=method;r['high_vol']=q.kospi_vol20>=high_cut;r['cases']=len(h)
                records.append(r)
                if a=='portfolio':
                    med=np.median(d);leave=np.array([np.median(np.delete(d,j)) for j in range(len(d))])
                    event_dependence.append({'date':q.date,'method':method,'cases':len(d),'median':med,
                        'max_leave_one_change_pct':float(np.max(abs(leave-med))),
                        'direction_flip':bool(np.any(np.sign(leave)!=np.sign(med)))})
        print(a,counts[-1],flush=True)
    r=pd.concat(records,ignore_index=True);r.to_parquet(OUT/'predictions.parquet',index=False)
    pd.DataFrame(counts).to_csv(OUT/'sample_counts.csv',index=False)
    pd.DataFrame(sensitivity).to_csv(OUT/'hypothetical.csv',index=False)
    pd.DataFrame(event_dependence).to_csv(OUT/'event_dependence.csv',index=False)
    summaries=[]
    for period,part in [('all',r),('recent3m',r[r.date>='2026-07-16']),('high_vol',r[r.high_vol])]:
        for (asset,model),z in part.groupby(['asset','model']):
            sums=z[['mae','squared_error','coverage','width','interval_score','pinball05','var_breach','shortfall_beyond_var']].mean().to_dict()
            sums.update(asset=asset,model=model,period=period,n=len(z),rmse=float(np.sqrt(sums['squared_error'])))
            summaries.append(sums)
    pd.DataFrame(summaries).to_csv(OUT/'metrics.csv',index=False)
    print('DONE',OUT,flush=True)


if __name__=='__main__':main()

