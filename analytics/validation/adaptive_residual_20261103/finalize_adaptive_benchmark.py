"""Join predeclared comparators and validate stored online residual availability."""
import json,sys
import numpy as np
import pandas as pd
from adaptive_residual_benchmark import ROOT,OUT,summarize

def main():
    a=pd.read_parquet(OUT/'predictions.parquet');b=pd.read_parquet(OUT/'direct80_predictions.parquet')
    if 'direct80' in set(a.method):a=a[a.method!='direct80']
    r=pd.concat([a,b],ignore_index=True)
    penalty=np.where(r.nominal.eq(.9),20,10)
    r['interval_score']=r.width+penalty*(np.maximum(r.q10-r.actual,0)+np.maximum(r.actual-r.q90,0))
    assert not r.duplicated(['date','asset','model','method']).any()
    check=b.merge(a[(a.model=='lightgbm')&(a.method=='vol80')],on=['date','asset'],suffixes=('_a','_b'),validate='one_to_one')
    assert len(check)==len(b) and np.max(abs(check.center_a-check.center_b))<1e-9
    ready=pd.to_datetime(r.latest_residual_ready,errors='coerce');assert (ready[ready.notna()]<r.loc[ready.notna(),'date']).all()
    bank=r[~r.method.isin(['vol80','vol90','direct80'])];assert bank.cal_n.min()>=30
    r.to_parquet(OUT/'predictions.parquet',index=False);summarize(r)
    decisions=pd.read_csv(OUT/'selection.csv')
    for i,d in decisions.iterrows():
        scope=r[r.asset.eq('portfolio')] if d.scope=='portfolio' else r[~r.asset.eq('portfolio')]
        candidate=scope[(scope.model==d.model)&(scope.method==d.method)&scope.market_crash]
        base=scope[(scope.model==d.model)&(scope.method=='vol90')&scope.market_crash]
        safety=bool(len(candidate) and candidate.breach.mean()<=base.breach.mean()+1e-12 and candidate.miss_size.mean()<=base.miss_size.mean()+1e-12)
        decisions.loc[i,'preserves_old90_crash_safety']=safety
        decisions.loc[i,'passes_target_and_old90_safety']=bool(d.passes_requested_gate and safety)
    decisions.to_csv(OUT/'selection.csv',index=False)
    diagnostics=[]
    for scope,z in [('portfolio',r[r.asset.eq('portfolio')]),('stocks',r[~r.asset.eq('portfolio')])]:
        for model,x in z[z.method.eq('vol80')].groupby('model'):
            err=abs(x.actual-x.center);diagnostics.append(dict(scope=scope,model=model,n=len(x),raw_center_mae=err.mean(),retrospective_abs_error_q80=err.quantile(.8),fixed_center_width5_coverage=(err<=2.5).mean(),note='retrospective center diagnostic, not independent interval validation'))
    pd.DataFrame(diagnostics).to_csv(OUT/'center_precision.csv',index=False)
    narrow=[]
    for (asset,model,method),x in r[r.nominal.eq(.8)].groupby(['asset','model','method']):
        z=x[x.width<=5];narrow.append(dict(asset=asset,model=model,method=method,n=len(z),total=len(x),coverage=z.coverage.mean(),width=z.width.mean(),miss_size=z.miss_size.mean()))
    pd.DataFrame(narrow).to_csv(OUT/'width5_subsets.csv',index=False)
    v=json.loads((OUT/'verification.json').read_text());v.update(final_rows=len(r),direct80_same_centers=True,stored_residual_ready_before_query=True,no_duplicate_predictions=True)
    (OUT/'verification.json').write_text(json.dumps(v,indent=2),encoding='utf8')
    import lightgbm,xgboost,sklearn
    (OUT/'environment.json').write_text(json.dumps({'python':sys.version,'lightgbm':lightgbm.__version__,'xgboost':xgboost.__version__,'sklearn':sklearn.__version__},indent=2),encoding='utf8')

if __name__=='__main__':main()
