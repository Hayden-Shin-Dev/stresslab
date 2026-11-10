"""Frozen 20-stock Gold benchmark; matched samples, family ablations, prior-period selection."""
import os,json,hashlib,time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,as_completed
import numpy as np
import pandas as pd
from catboost import CatBoostRegressor
from lightgbm import LGBMRegressor
from gold_quantile_benchmark import ROOT,FEATURES
from build_gold20_locked_20261104 import FLOW_FEATURES,FLOW_RATIOS,MARKET_FLOW,PRICE_FEATURES,PEER_FEATURES,COMPANY_FEATURES
OUT=ROOT/'reports/gold20_locked_20261104'
PARAMS=dict(iterations=250,depth=4,learning_rate=.04,loss_function='MultiQuantile:alpha=0.05,0.5,0.95',random_seed=20261103,thread_count=2,verbose=False,allow_writing_files=False)
GROUPS={'flows':FLOW_FEATURES+FLOW_RATIOS+MARKET_FLOW,'liquidity':PRICE_FEATURES,'peers':PEER_FEATURES,'company':COMPANY_FEATURES}
METHODS=['baseline','raw_target','lgb_same_features']+list(GROUPS)+['all_added']

def metrics(z):
    y=z.actual.to_numpy();p=z.center.to_numpy();nz=y!=0;cr=y<=-5;up=y>=5
    return dict(n=len(z),stocks=z.asset.nunique(),dates=z.date.nunique(),mae=float(np.mean(abs(y-p))),rmse=float(np.sqrt(np.mean((y-p)**2))),direction=float(np.mean(np.sign(y[nz])==np.sign(p[nz]))),crash_n=int(cr.sum()),crash_mae=float(np.mean(abs(y[cr]-p[cr]))) if cr.any() else None,crash_direction=float(np.mean(p[cr]<0)) if cr.any() else None,crash_caught=int(((p<=-5)&cr).sum()),false_crash=int(((p<=-5)&~cr).sum()),surge_mae=float(np.mean(abs(y[up]-p[up]))) if up.any() else None)

def task(asset,frame,year,locked):
    cut=pd.Timestamp(year,1,1);train=frame[frame.end_date<pd.Timestamp(year-1,1,1)-pd.Timedelta(days=20)]
    cal=frame[(frame.date>=pd.Timestamp(year-1,1,1))&(frame.end_date<cut-pd.Timedelta(days=20))].iloc[::6]
    if year>=2023:
        dates=locked.loc[(locked.asset==asset)&(locked.fold==year),'date']
        test=frame[frame.date.isin(dates)].sort_values('date')
        assert len(test)==len(dates)
    else:test=frame[(frame.date>=cut)&(frame.date<pd.Timestamp(year+1,1,1))].iloc[::6]
    if len(train)<250 or len(cal)<30 or test.empty:return [],[]
    assert train.end_date.max()<cal.date.min() and cal.end_date.max()<test.date.min()
    results=[];audit=[]
    for method in METHODS:
        cols=FEATURES+(sum(GROUPS.values(),[]) if method=='all_added' else GROUPS.get(method,[]))
        normal=method!='raw_target';y=train.target/train.scale if normal else train.target
        if method=='lgb_same_features':
            model=LGBMRegressor(objective='quantile',alpha=.5,n_estimators=250,max_depth=4,num_leaves=15,learning_rate=.04,min_child_samples=30,reg_lambda=10,random_state=20261103,n_jobs=2,verbosity=-1)
            model.fit(train[cols].to_numpy(),y);center=model.predict(test[cols].to_numpy());fitted=model.predict(train[cols].to_numpy())
        else:
            model=CatBoostRegressor(**PARAMS);model.fit(train[cols].to_numpy(),y)
            center=np.sort(model.predict(test[cols].to_numpy()),axis=1)[:,1];fitted=np.sort(model.predict(train[cols].to_numpy()),axis=1)[:,1]
        if normal:center=center*test.scale.to_numpy();fitted=fitted*train.scale.to_numpy()
        out=pd.DataFrame(dict(asset=asset,date=test.date.to_numpy(),fold=year,method=method,actual=test.target.to_numpy(),center=center))
        if method=='baseline' and year>=2023:
            old=locked[(locked.asset==asset)&(locked.fold==year)].sort_values('date')
            assert np.allclose(out.actual,old.actual,rtol=0,atol=1e-10)
            delta=float(np.max(abs(center-old['median'].to_numpy())))
            assert delta<1e-7,(asset,year,delta)
        else:delta=None
        results.append(out)
        audit.append(dict(asset=asset,fold=year,method=method,features=len(cols),train_n=len(train),cal_n=len(cal),test_n=len(test),train_end=str(train.end_date.max()),test_start=str(test.date.min()),train_mae=float(np.mean(abs(train.target.to_numpy()-fitted))),added_train_missing=float(train[cols].isna().mean().mean()),added_test_missing=float(test[cols].isna().mean().mean()),baseline_reproduction_max_error=delta))
    return results,audit

def stage(data,locked,years,name):
    folder=OUT/name;folder.mkdir(exist_ok=True);jobs=[]
    with ThreadPoolExecutor(max_workers=4) as pool:
        for asset,frame in data.groupby('asset'):
            for year in years:
                path=folder/f'{asset}_{year}.parquet'
                if not path.exists():jobs.append(pool.submit(task,asset,frame.sort_values('date'),year,locked))
        for i,f in enumerate(as_completed(jobs),1):
            rr,aa=f.result()
            if rr:
                r=pd.concat(rr);stem=f'{r.asset.iloc[0]}_{r.fold.iloc[0]}'
                r.to_parquet(folder/f'{stem}.parquet',index=False);pd.DataFrame(aa).to_csv(folder/f'{stem}.csv',index=False)
            (OUT/'progress.json').write_text(json.dumps(dict(stage=name,completed=i,total=len(jobs),time=time.time())),encoding='utf8')
            print(name,i,len(jobs),flush=True)
    return pd.concat([pd.read_parquet(p) for p in folder.glob('*.parquet')],ignore_index=True)

def main():
    path=ROOT/'exports/seongjin_gold_v1_1/gold_stress_daily.parquet';oldpath=ROOT/'reports/gold_quantile_benchmark_20261103/predictions.parquet'
    old=pd.read_parquet(oldpath);locked=old[(old.model=='catboost_quantile')&(old.asset!='portfolio')].copy()
    assert len(locked)==2928 and locked.asset.nunique()==20
    locked.to_parquet(OUT/'locked_baseline.parquet',index=False)
    data=pd.read_parquet(OUT/'learning_table.parquet');assert data.asset.nunique()==20
    protocol=dict(gold_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),baseline_sha256=hashlib.sha256(oldpath.read_bytes()).hexdigest(),assets=sorted(locked.asset.unique()),n=2928,features=FEATURES,groups=GROUPS,params=PARAMS,selection='2020 and 2021 development only; >=1% MAE improvement, direction >=baseline, crash MAE <=baseline, and MAE no worse in either year; choose lowest development MAE among eligible family models, else baseline. Freeze before evaluation.',evaluation='2023-2026 reused research, NOT blind; exact initial stock/date/target and annual training split',publication_limit='Original Gold vintage/publication timestamps incomplete; not certified historical availability',scope='No Azure, production or Gold contract changes; no imputed zero flow; current 20-stock universe survivorship limitation',meaning='Observed five-day shocks supplied retrospectively; conditional reconstruction, not causal effect',methods=METHODS)
    (OUT/'protocol.json').write_text(json.dumps(protocol,ensure_ascii=False,indent=2),encoding='utf8')
    dev=stage(data,locked,[2020,2021],'development');dm={m:metrics(z) for m,z in dev.groupby('method')};b=dm['baseline'];eligible=[]
    for m in GROUPS:
        s=dm[m]
        yearly=all(metrics(dev[(dev.method==m)&(dev.fold==yr)])['mae']<=metrics(dev[(dev.method=='baseline')&(dev.fold==yr)])['mae'] for yr in [2020,2021])
        if s['mae']<=b['mae']*.99 and s['direction']>=b['direction'] and s['crash_mae']<=b['crash_mae'] and yearly:eligible.append(m)
    chosen=min(eligible,key=lambda m:dm[m]['mae']) if eligible else 'baseline'
    (OUT/'frozen_selection.json').write_text(json.dumps(dict(chosen=chosen,eligible=eligible,development_metrics=dm),indent=2),encoding='utf8')
    ev=stage(data,locked,[2023,2024,2025,2026],'evaluation')
    for m,z in ev.groupby('method'):
        assert len(z)==2928 and z.asset.nunique()==20
        q=z.merge(locked[['asset','date','actual']],on=['asset','date'],validate='one_to_one',suffixes=('','_old'));assert np.allclose(q.actual,q.actual_old)
    selected=ev[ev.method==chosen].copy();selected['method']='prior_selected';ev=pd.concat([ev,selected],ignore_index=True);ev.to_parquet(OUT/'predictions.parquet',index=False)
    pd.DataFrame([dict(method=m,**metrics(z)) for m,z in ev.groupby('method')]).to_csv(OUT/'metrics.csv',index=False)
    pd.DataFrame([dict(asset=a,method=m,**metrics(z)) for (a,m),z in ev.groupby(['asset','method'])]).to_csv(OUT/'per_stock.csv',index=False)
    pd.DataFrame([dict(fold=y,method=m,**metrics(z)) for (y,m),z in ev.groupby(['fold','method'])]).to_csv(OUT/'per_year.csv',index=False)
    # Paired time-block resampling, preserving all cross-stock observations within sampled dates.
    base=ev[ev.method=='baseline'][['asset','date','center']].rename(columns={'center':'base'});rng=np.random.default_rng(20261104);ci=[]
    for m,z in ev.groupby('method'):
        q=z.merge(base,on=['asset','date'],validate='one_to_one');q['gain']=abs(q.actual-q.base)-abs(q.actual-q.center);q['dirgain']=np.where(q.actual.ne(0),(np.sign(q.actual)==np.sign(q.center)).astype(float)-(np.sign(q.actual)==np.sign(q.base)).astype(float),np.nan)
        agg=q.groupby('date').agg(gain=('gain','sum'),n=('gain','size'),direction=('dirgain','sum'),dn=('dirgain','count')).sort_index().to_numpy();n=len(agg);samples=[]
        for _ in range(1500):
            starts=rng.integers(0,n,size=int(np.ceil(n/5)));idx=np.concatenate([(s+np.arange(5))%n for s in starts])[:n];v=agg[idx].sum(axis=0);samples.append([v[0]/v[1],v[2]/v[3]])
        bounds=np.quantile(samples,[.025,.975],axis=0);ci.append(dict(method=m,mae_gain_lo=bounds[0,0],mae_gain_hi=bounds[1,0],direction_gain_lo=bounds[0,1],direction_gain_hi=bounds[1,1]))
    pd.DataFrame(ci).to_csv(OUT/'paired_block_bootstrap.csv',index=False)
    (OUT/'progress.json').write_text(json.dumps(dict(stage='complete',chosen=chosen)),encoding='utf8')
    print(pd.read_csv(OUT/'metrics.csv').to_string(index=False))

if __name__=='__main__':main()
