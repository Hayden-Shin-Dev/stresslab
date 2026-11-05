"""Separate return-error baselines from shock-association diagnostics."""
import argparse,json
from pathlib import Path
import numpy as np,pandas as pd,joblib
from .core import SHOCKS

def run(out,root):
 out=Path(out);root=Path(root);b=joblib.load(out/'tiered_bundle.joblib')
 priority=json.loads((out/'frozen_four_shock_priority.json').read_text());chosen=set(priority['prior17']+priority['priority_additions']);sectors=b['sectors']
 names={a['asset_id']:a['name'] for a in json.loads((root/'data/research/exposure_universe_20261103/universe.json').read_text(encoding='utf8'))['assets']}
 p=pd.read_parquet(out/'predictions.parquet');primary=set(b['primary']['support']);rows=[]
 for cohort,assets in [('frozen50',chosen),('prior17',primary),('new33',chosen-primary),('all68_training_cohort',set(p.asset))]:
  for model,z in p[p.asset.isin(assets)].groupby('model'):
   crash=z.actual<=-5;rows.append(dict(cohort=cohort,model=model,n=len(z),dates=z.date.nunique(),assets=z.asset.nunique(),mae_pp=abs(z.center-z.actual).mean(),direction=np.mean(np.sign(z.center)==np.sign(z.actual)),crash_n=int(crash.sum()),crash_center_underestimate_pp=np.maximum(z.loc[crash,'center']-z.loc[crash,'actual'],0).mean()))
 pd.DataFrame(rows).to_csv(out/'cohort_metrics.csv',index=False)
 diag=pd.read_parquet(out/'shock_diagnostics.parquet');annual=pd.read_csv(out/'annual_coefficients.csv',dtype={'asset':str});rng=np.random.default_rng(404);rows=[]
 for (a,s),z in diag.groupby(['asset','shock']):
  z=z.sort_values('date');x=z.residual_shock.to_numpy();y=z.residual_return.to_numpy();response=z.model_response.to_numpy();den=np.dot(x,x);slope=np.dot(x,y)/den if den else np.nan;n=len(z);est=[]
  for _ in range(500):
   ix=np.concatenate([(v+np.arange(5))%n for v in rng.integers(0,n,size=int(np.ceil(n/5)))])[:n];xx=x[ix];yy=y[ix];est.append(np.dot(xx,yy)/max(np.dot(xx,xx),1e-12))
  ci=np.quantile(est,[.025,.975]);model_sign=np.sign(z.coefficient.median());strong=bool(ci[0]*ci[1]>0 and np.sign(slope)==model_sign)
  c=annual[annual.asset.eq(a)&annual.shock.eq(s)].coefficient;event=z.large_residual_shock.to_numpy()
  rows.append(dict(asset=a,name=names[a],shock=s,n=n,event_n=int(event.sum()),controlled_oos_slope=slope,slope_ci_low=ci[0],slope_ci_high=ci[1],conditional_correlation=np.corrcoef(x,y)[0,1],large_shock_response_direction_agreement=np.mean(np.sign(response[event])==np.sign(y[event])) if event.any() else np.nan,shock_component_mae_gain_pp=np.mean(abs(y))-np.mean(abs(y-response)),annual_model_sign_agreement=np.mean(np.sign(c)==model_sign),oos_association_aligned_ci_excludes_zero=strong,interpretation='Observed adjusted association, not causal effect; individual 95% intervals not multiplicity corrected'))
 diagout=pd.DataFrame(rows);diagout.to_csv(out/'shock_evidence.csv',index=False)
 # Add BH-adjusted two-sided normal approximation as a multiplicity warning, not a support selector.
 from scipy.stats import norm
 se=(diagout.slope_ci_high-diagout.slope_ci_low)/(2*1.96);pv=2*norm.sf(abs(diagout.controlled_oos_slope)/se.clip(lower=1e-12));order=np.argsort(pv);q=np.empty(len(pv));q[order]=np.minimum.accumulate((pv[order]*len(pv)/np.arange(1,len(pv)+1))[::-1])[::-1];diagout['approx_bh_q']=np.minimum(q,1);diagout.to_csv(out/'shock_evidence.csv',index=False)
 fallback=pd.read_parquet(out/'fallback_predictions.parquet');pd.DataFrame([dict(group=k,model=m,n=len(z),mae_pp=abs(z.center-z.actual).mean(),crash_underestimate_pp=np.maximum(z.loc[z.actual.le(-5),'center']-z.loc[z.actual.le(-5),'actual'],0).mean()) for (k,m),z in fallback.groupby(['group','model'])]).to_csv(out/'fallback_metrics.csv',index=False)
 tiers=[];coeff=[]
 for a,sec in sorted(sectors.items()):
  which=b['primary'] if a in primary else b['expanded'];engine=which['engine'];snap=which['snapshot'];x=snap[snap.asset.eq(a)]
  tier='quantitative_candidate' if a in chosen else 'exploratory'
  if x.empty:tier='history_only'
  tiers.append(dict(asset=a,name=names[a],sector=sec,tier=tier,priority_existing=a in primary,accepted_shocks=SHOCKS,production_approved=False))
  if x.empty:continue
  beta,stable,detail=engine.coefficients(x)
  for j,s in enumerate(SHOCKS):
   evidence=diagout[diagout.asset.eq(a)&diagout.shock.eq(s)].iloc[0].to_dict()
   coeff.append(dict(asset=a,name=names[a],shock=s,coefficient_pp_per_unit=beta[0,j],coefficient_source='asset_partial_pool',training_stable=bool(stable[0,j]),coefficient_cv=detail['global_spread'][0,j],common_coefficient=engine.global_model.slope_parts(x.iloc[0],s)['shared_coefficient'],asset_deviation=engine.global_model.slope_parts(x.iloc[0],s)['asset_deviation'],**{k:v for k,v in evidence.items() if k not in ['asset','name','shock']}))
 pd.DataFrame(coeff).to_csv(out/'four_shock_coefficients.csv',index=False)
 (out/'service_tiers.json').write_text(json.dumps(tiers,ensure_ascii=False,indent=2),encoding='utf8')
 b['tiers']={r['asset']:r['tier'] for r in tiers};b['names']=names;b['evidence']={}
 for r in diagout.to_dict('records'):b['evidence'].setdefault(r['asset'],{})[r['shock']]={k:(None if isinstance(v,float) and not np.isfinite(v) else v) for k,v in r.items()}
 joblib.dump(b,out/'tiered_bundle.joblib')
 counts={s:int(diagout[diagout.asset.isin(chosen)&diagout.shock.eq(s)].oos_association_aligned_ci_excludes_zero.sum()) for s in SHOCKS}
 (out/'summary.json').write_text(json.dumps(dict(candidates=len(sectors),primary=len(primary),frozen_quantitative_candidates=len(chosen),new_candidates=len(chosen-primary),tiers=pd.Series(b['tiers']).value_counts().to_dict(),shock_supported_observed_associations=counts,quantitative_is_not_production_approval=True),indent=2),encoding='utf8');print('summary',counts,flush=True)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--out',required=True);p.add_argument('--root',required=True);a=p.parse_args();run(a.out,a.root)
