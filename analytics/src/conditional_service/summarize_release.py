"""Paired date-block uncertainty and explicit support export; no model selection."""
import argparse,json
from pathlib import Path
import joblib,numpy as np,pandas as pd
from .core import metrics,SHOCKS
from .service_release import analyze_release

def run(folder):
 p=Path(folder);b=joblib.load(p/'candidate_bundle.joblib');d=pd.read_parquet(p/'predictions.parquet')
 rows=[];rng=np.random.default_rng(241104)
 for baseline in ['all26_global_common','individual_ridge_raw']:
  x=d[d.model.eq('selected_global')].merge(d[d.model.eq(baseline)],on=['date','asset'],suffixes=('_new','_old'),validate='one_to_one')
  x['delta']=abs(x.center_new-x.actual_new)-abs(x.center_old-x.actual_old)
  daily=x.groupby('date').agg(delta=('delta','sum'),n=('delta','size'))
  estimates=[];n=len(daily);block=5
  for _ in range(2000):
   ix=np.concatenate([(s+np.arange(block))%n for s in rng.integers(0,n,size=int(np.ceil(n/block)))])[:n]
   z=daily.iloc[ix];estimates.append(z.delta.sum()/z.n.sum())
  rows.append(dict(baseline=baseline,paired_rows=len(x),dates=n,mae_delta_pp=x.delta.mean(),delta_ci95=np.quantile(estimates,[.025,.975]).tolist(),block_evaluation_dates=block,interpretation='negative favors selected; repeated development evaluation, not blind'))
 (p/'paired_uncertainty.json').write_text(json.dumps(rows,indent=2),encoding='utf8')
 pd.DataFrame([dict(year=y,model=m,**metrics(z)) for (y,m),z in d.groupby(['fold','model'])]).to_csv(p/'per_year.csv',index=False)
 bad=d[d.model.eq('selected_global')].copy();bad['absolute_error_pp']=abs(bad.center-bad.actual)
 bad.sort_values('absolute_error_pp',ascending=False).groupby('asset').head(3).to_csv(p/'failure_cases.csv',index=False)
 e=b['engine'];snap=b['snapshot'];beta,stable,det=e.coefficients(snap);rows=[]
 for i,r in enumerate(snap.itertuples()):
  for j,s in enumerate(SHOCKS):
   v=det['global_fold_beta'][:,i,j]
   rows.append(dict(asset=r.asset,shock=s,supported=s in b['support'].get(r.asset,[]),coefficient_pp_per_unit=beta[i,j],coefficient_cv=det['global_spread'][i,j],training_refit_sign_consistent=bool((v>0).all() or (v<0).all()),fit_coefficients=json.dumps(v.tolist()),scope='research_candidate_not_causal'))
 pd.DataFrame(rows).to_csv(p/'coefficients.csv',index=False)
 (p/'active_support.json').write_text(json.dumps(b['support'],indent=2),encoding='utf8')
 positions=[dict(asset_id=a,value_krw=1000000) for a in ['003490','010950']]
 examples={n:analyze_release(b,positions,s) for n,s in [('zero',{}),('oil10',{'wti_pct':10}),('fx5_rate100',{'fx_pct':5,'us_rate_bp':100})]}
 (p/'examples.json').write_text(json.dumps(examples,ensure_ascii=False,indent=2),encoding='utf8')
 print(json.dumps(rows[:1]));print(json.dumps(json.loads((p/'paired_uncertainty.json').read_text())))
if __name__=='__main__':
 a=argparse.ArgumentParser();a.add_argument('folder');run(a.parse_args().folder)
