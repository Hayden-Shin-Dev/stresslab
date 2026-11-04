"""One fixed conservative blend; secondary exploration, not an independent test.
Half initial Gold, equal remaining weight across four separately fitted feature families.
Weights are not optimized on evaluation outcomes. No interval construction.
"""
import json
import numpy as np
import pandas as pd
from compare_gold20_locked_20261104 import OUT,metrics
WEIGHTS={'baseline':.5,'flows':.125,'liquidity':.125,'peers':.125,'company':.125}
def blend(d):
    x=d[d.method.isin(WEIGHTS)].copy();x['center']=x.center*x.method.map(WEIGHTS)
    assert x.groupby(['asset','date']).size().eq(5).all()
    r=x.groupby(['asset','date','fold','actual'],as_index=False).center.sum();r['method']='fixed_blend';return r
def main():
    dev=pd.concat([pd.read_parquet(p) for p in (OUT/'development').glob('*.parquet')]);r=blend(dev)
    diagnostics=[]
    for yr in [2020,2021]:
        a=metrics(r[r.fold==yr]);b=metrics(dev[(dev.method=='baseline')&(dev.fold==yr)]);diagnostics.append(dict(year=yr,blend=a,baseline=b,passes=a['mae']<b['mae'] and a['direction']>=b['direction'] and a['crash_mae']<=b['crash_mae']))
    (OUT/'blend_frozen_policy.json').write_text(json.dumps(dict(weights=WEIGHTS,development=diagnostics,designed_after_aggregate_evaluation=True,blind=False,weight_optimization=False),indent=2),encoding='utf8')
    assert all(x['passes'] for x in diagnostics)
    ev=pd.read_parquet(OUT/'predictions.parquet');ev=ev[ev.method!='fixed_blend'];r=blend(ev);assert len(r)==2928
    ev=pd.concat([ev,r],ignore_index=True);ev.to_parquet(OUT/'predictions.parquet',index=False)
    pd.DataFrame([dict(method=m,**metrics(z)) for m,z in ev.groupby('method')]).to_csv(OUT/'metrics.csv',index=False)
    pd.DataFrame([dict(asset=a,method=m,**metrics(z)) for (a,m),z in ev.groupby(['asset','method'])]).to_csv(OUT/'per_stock.csv',index=False)
    pd.DataFrame([dict(fold=y,method=m,**metrics(z)) for (y,m),z in ev.groupby(['fold','method'])]).to_csv(OUT/'per_year.csv',index=False)
    base=ev[ev.method=='baseline'][['asset','date','center']].rename(columns={'center':'base'});q=r.merge(base,on=['asset','date'],validate='one_to_one')
    q['gain']=abs(q.actual-q.base)-abs(q.actual-q.center);q['dirgain']=np.where(q.actual.ne(0),(np.sign(q.actual)==np.sign(q.center)).astype(float)-(np.sign(q.actual)==np.sign(q.base)).astype(float),np.nan)
    agg=q.groupby('date').agg(gain=('gain','sum'),n=('gain','size'),direction=('dirgain','sum'),dn=('dirgain','count')).sort_index().to_numpy();rng=np.random.default_rng(20261104);n=len(agg);samples=[]
    for _ in range(1500):
        starts=rng.integers(0,n,size=int(np.ceil(n/5)));idx=np.concatenate([(s+np.arange(5))%n for s in starts])[:n];v=agg[idx].sum(axis=0);samples.append([v[0]/v[1],v[2]/v[3]])
    bounds=np.quantile(samples,[.025,.975],axis=0);ci=pd.read_csv(OUT/'paired_block_bootstrap.csv');ci=ci[ci.method!='fixed_blend'];ci=pd.concat([ci,pd.DataFrame([dict(method='fixed_blend',mae_gain_lo=bounds[0,0],mae_gain_hi=bounds[1,0],direction_gain_lo=bounds[0,1],direction_gain_hi=bounds[1,1])])]);ci.to_csv(OUT/'paired_block_bootstrap.csv',index=False)
    print(json.dumps(metrics(r)))
if __name__=='__main__':main()
