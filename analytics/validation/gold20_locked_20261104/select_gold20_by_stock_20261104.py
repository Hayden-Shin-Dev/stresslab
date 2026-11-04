"""Secondary research policy: feature families selected from development only.
Designed after aggregate evaluation was seen; not a blind confirmation test.
No per-stock evaluation outcomes used in the selection rule.
"""
import json
import numpy as np
import pandas as pd
from compare_gold20_locked_20261104 import OUT,GROUPS,metrics

def main():
    dev=pd.concat([pd.read_parquet(p) for p in (OUT/'development').glob('*.parquet')],ignore_index=True)
    assets=json.loads((OUT/'protocol.json').read_text())['assets'];choices={};details=[]
    for asset in assets:
        z=dev[dev.asset==asset];eligible=[]
        if z.empty:choices[asset]='baseline';continue
        baseline=metrics(z[z.method=='baseline'])
        for method in GROUPS:
            score=metrics(z[z.method==method]);yearly=all(metrics(z[(z.method==method)&(z.fold==year)])['mae']<=metrics(z[(z.method=='baseline')&(z.fold==year)])['mae'] for year in [2020,2021])
            ok=bool(score['n']>=60 and score['crash_n']>=5 and score['mae']<=baseline['mae']*.99 and score['direction']>=baseline['direction'] and score['crash_mae']<=baseline['crash_mae'] and yearly)
            details.append(dict(asset=asset,method=method,eligible=ok,**score))
            if ok:eligible.append((score['mae'],method))
        choices[asset]=min(eligible)[1] if eligible else 'baseline'
    # Persist development-only decisions before loading per-stock evaluation outputs.
    (OUT/'stock_frozen_selection.json').write_text(json.dumps(dict(choices=choices,blind=False,designed_after_aggregate_evaluation=True,selection_data='2020-2021 only; no per-stock evaluation outcome selection',rule='>=60 samples, >=5 crash samples; MAE improves >=1%; direction/crash MAE no worse; MAE no worse in both years; choose lowest dev MAE, else baseline'),indent=2),encoding='utf8')
    pd.DataFrame(details).to_csv(OUT/'stock_development_selection.csv',index=False)
    ev=pd.read_parquet(OUT/'predictions.parquet');ev=ev[ev.method!='stock_selected'];selected=pd.concat([ev[(ev.asset==a)&(ev.method==m)] for a,m in choices.items()],ignore_index=True);assert len(selected)==2928
    selected['method']='stock_selected';ev=pd.concat([ev,selected],ignore_index=True);ev.to_parquet(OUT/'predictions.parquet',index=False)
    pd.DataFrame([dict(method=m,**metrics(z)) for m,z in ev.groupby('method')]).to_csv(OUT/'metrics.csv',index=False)
    pd.DataFrame([dict(asset=a,method=m,**metrics(z)) for (a,m),z in ev.groupby(['asset','method'])]).to_csv(OUT/'per_stock.csv',index=False)
    pd.DataFrame([dict(fold=y,method=m,**metrics(z)) for (y,m),z in ev.groupby(['fold','method'])]).to_csv(OUT/'per_year.csv',index=False)
    base=ev[ev.method=='baseline'][['asset','date','center']].rename(columns={'center':'base'});q=selected.merge(base,on=['asset','date'],validate='one_to_one')
    q['gain']=abs(q.actual-q.base)-abs(q.actual-q.center);q['dirgain']=np.where(q.actual.ne(0),(np.sign(q.actual)==np.sign(q.center)).astype(float)-(np.sign(q.actual)==np.sign(q.base)).astype(float),np.nan)
    agg=q.groupby('date').agg(gain=('gain','sum'),n=('gain','size'),direction=('dirgain','sum'),dn=('dirgain','count')).sort_index().to_numpy();rng=np.random.default_rng(20261104);n=len(agg);samples=[]
    for _ in range(1500):
        starts=rng.integers(0,n,size=int(np.ceil(n/5)));idx=np.concatenate([(s+np.arange(5))%n for s in starts])[:n];v=agg[idx].sum(axis=0);samples.append([v[0]/v[1],v[2]/v[3]])
    bounds=np.quantile(samples,[.025,.975],axis=0);ci=pd.read_csv(OUT/'paired_block_bootstrap.csv');ci=ci[ci.method!='stock_selected'];ci=pd.concat([ci,pd.DataFrame([dict(method='stock_selected',mae_gain_lo=bounds[0,0],mae_gain_hi=bounds[1,0],direction_gain_lo=bounds[0,1],direction_gain_hi=bounds[1,1])])]);ci.to_csv(OUT/'paired_block_bootstrap.csv',index=False)
    print(json.dumps(dict(choices=choices,metrics=metrics(selected)),ensure_ascii=False))

if __name__=='__main__':main()
