"""Finalize saved-result width decomposition. No model selection or deployment."""
import json,hashlib
from pathlib import Path
import numpy as np
import pandas as pd
from .width_audit import OUT,metric

def main():
    v1=pd.read_csv('reports/v2/matched_comparison.csv');v1[v1.model.eq('v1_selected')].to_csv(OUT/'initial_poc_widths.csv',index=False)
    p=pd.read_parquet('reports/pooled_hybrid_20261104/predictions.parquet');p=p[p.model.eq('catboost')]
    rows=[]
    for year,z in p.groupby('fold'):
        c=pd.read_parquet(f'reports/pooled_hybrid_20261104/folds/{year}_calibration.parquet');c=c[c.model.eq('catboost')]
        for method in ['asset','pooled']:
            for level in [.8,.9]:
                for a,t in z.groupby('asset'):
                    q=c if method=='pooled' else c[c.asset.eq(a)]
                    low,high=np.quantile((q.actual-q.center)/q.scale,[(1-level)/2,1-(1-level)/2])
                    t=t.copy();t['lo']=t.center+low*t.scale;t['hi']=t.center+high*t.scale;t['method']=method;t['level']=level;rows.append(t)
    x=pd.concat(rows)
    pd.DataFrame([dict(method=m,level=l,**metric(z.actual,z.lo,z.hi)) for (m,l),z in x.groupby(['method','level'])]).to_csv(OUT/'legacy20_same_levels.csv',index=False)
    latest=pd.read_parquet('reports/three_model_intervals_20261105/intervals.parquet');latest=latest[latest.model.eq('catboost')]
    pd.DataFrame([dict(asset=a,level=l,**metric(z.actual,z.lo,z.hi)) for (a,l),z in latest[latest.interval.eq('pooled')].groupby(['asset','level'])]).to_csv(OUT/'latest_by_asset.csv',index=False)
    # Exact arithmetic bridge: evaluate same overlap first, then change only pool composition,
    # then reporting universe, then target coverage. It is path-specific, not universal causation.
    corr=pd.read_parquet(OUT/'matched_correction_intervals.parquet')
    cv=corr[corr.version.eq('corrected_values')&corr.method.eq('asset')&corr.level.eq(.8)]
    check=cv.merge(latest[latest.interval.eq('asset')&latest.level.eq(.8)],on=['date','asset'],suffixes=('_retrain','_saved'),validate='one_to_one')
    for col in ['center','lo','hi']:np.testing.assert_allclose(check[col+'_retrain'],check[col+'_saved'],atol=1e-9)
    ci=pd.read_csv(OUT/'correction_effect.csv');sc=pd.read_csv(OUT/'current_scope_and_calibration.csv')
    def c(v,m,l):return float(ci[(ci.version==v)&(ci.method==m)&(ci.level==l)].width_pp.iloc[0])
    def s(v,m,l):return float(sc[(sc.scope==v)&(sc.method==m)&(sc.level==l)].width_pp.iloc[0])
    steps=[('old_values_common_rows_asset80',c('legacy_values','asset',.8)),('corrected_values_same_rows_asset80',c('corrected_values','asset',.8)),('same_rows_pool13_80',c('corrected_values','pooled',.8)),('same_rows_pool50_80',s('old20_overlap','pooled',.8)),('report_all50_pool50_80',s('all50','pooled',.8)),('report_all50_pool50_90',s('all50','pooled',.9))]
    bridge=[dict(step=n,width_pp=w,delta_previous_pp=0 if i==0 else w-steps[i-1][1]) for i,(n,w) in enumerate(steps)]
    pd.DataFrame(bridge).to_csv(OUT/'width_bridge.csv',index=False)
    verification=dict(corrected_retrain_reproduces_saved=True,common_assets=check.asset.nunique(),common_rows=len(check),causal_scope='matched value correction; universe composition descriptive; path dependent bridge',web_work_stopped=True,azure_gold_unchanged=True,production_model_changed=False)
    (OUT/'verification.json').write_text(json.dumps(verification,indent=2))
    paths=['reports/validation.json','reports/v2/matched_comparison.csv','reports/pooled_hybrid_20261104/predictions.parquet','reports/service_scope_20261105/corrected_features.parquet','reports/support_expansion_20261104/research_input.parquet','reports/three_model_intervals_20261105/intervals.parquet']
    (OUT/'sources.json').write_text(json.dumps({f:hashlib.sha256(Path(f).read_bytes()).hexdigest() for f in paths},indent=2))
    print(pd.read_csv(OUT/'legacy20_same_levels.csv').to_string(index=False));print(pd.DataFrame(bridge).to_string(index=False))

if __name__=='__main__':main()
