"""Exact additive attribution of the unchanged Ridge on held-out cases."""
import json
from pathlib import Path
import joblib,numpy as np,pandas as pd
from threadpoolctl import threadpool_limits
from .core import STATE,ASSET,SHOCKS
from .finalize_model import BoundedFactor
from .rebuild_fixed_model import training

def main():
    root=Path('reports/service_scope_20261105');out=Path('reports/recent_diagnosis_20261105')
    b=joblib.load(root/'final_service_bundle.joblib');cfg=json.loads((root/'locked_protocol.json').read_text())
    f=pd.read_parquet(root/'corrected_features.parquet');p=pd.read_parquet(out/'predictions.parquet');parts=[]
    for group in ['primary','expanded']:
        d=f[f.asset.isin(cfg['cohorts'][group]['assets'])]
        for year in [2025,2026]:
            tr=training(d,pd.Timestamp(year-1,1,1))
            z=p[(p.group==group)&(p.year==year)][['date','asset','actual','baseline']]
            q=z[['date','asset']].merge(d,on=['date','asset'],validate='one_to_one')
            m=BoundedFactor(dict(alpha=300,dev=10,years=None),b['sectors']).fit(tr)
            contributions=m.design(q)*m.model.coef_
            np.testing.assert_allclose(contributions.sum(axis=1)+m.model.intercept_,z.baseline,atol=1e-8)
            z=z.copy();z['year']=year;z['name']=z.asset.map(b['names']);z['intercept']=m.model.intercept_
            for j,c in enumerate(m.columns):z['term_'+c]=contributions[:,j]
            offset=len(m.columns);z['asset_intercept']=contributions[:,offset:offset+len(m.assets)].sum(axis=1)
            z['stock_shock_deviation']=contributions[:,offset+len(m.assets):].sum(axis=1)
            z['market_state_terms']=z[['term_'+s for s in STATE]].sum(axis=1)
            z['asset_state_terms']=z[['term_'+s for s in ASSET]].sum(axis=1)
            z['shock_terms']=z[['term_'+s for s in SHOCKS]].sum(axis=1)+z.stock_shock_deviation
            z['states_outside_training_range']=((q[STATE+ASSET]<tr[STATE+ASSET].min())|(q[STATE+ASSET]>tr[STATE+ASSET].max())).sum(axis=1).to_numpy()
            z['shocks_outside_training_range']=((q[SHOCKS]<tr[SHOCKS].min())|(q[SHOCKS]>tr[SHOCKS].max())).sum(axis=1).to_numpy()
            parts.append(z)
    z=pd.concat(parts);z['absolute_error']=abs(z.actual-z.baseline)
    z.to_parquet(out/'exact_center_decomposition.parquet',index=False)
    z.sort_values('absolute_error',ascending=False).groupby('asset',sort=False).head(3).to_csv(out/'explained_failures.csv',index=False)
    summary={}
    for label,d in [('recent',z),('crash',z[z.actual<=-5]),('rally',z[z.actual>=5])]:
        summary[label]=dict(n=len(d),actual_mean=float(d.actual.mean()),prediction_mean=float(d.baseline.mean()),
            mae=float(d.absolute_error.mean()),state_range_exceed_rows=int(d.states_outside_training_range.gt(0).sum()),shock_range_exceed_rows=int(d.shocks_outside_training_range.gt(0).sum()),
            mean_signed_terms={c:float(d[c].mean()) for c in ['intercept','asset_intercept','market_state_terms','asset_state_terms','shock_terms']},
            removal_diagnostic_mae={c:float(abs(d.actual-(d.baseline-d[c])).mean()) for c in ['market_state_terms','asset_state_terms','shock_terms']})
    summary['warning']='Terms are relative to training feature means, not causal effects or user zero-shock contributions. Removal is an after-the-fact diagnostic, not an approved model.'
    (out/'center_diagnosis.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(summary,ensure_ascii=True))

if __name__=='__main__':
    with threadpool_limits(limits=2):main()
