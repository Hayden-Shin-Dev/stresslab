"""Add exact served-cohort validation and historical-only evidence without changing fits."""
import argparse,json
from pathlib import Path
import pandas as pd,numpy as np,joblib
from .core import features,anchors,SHOCKS

def run(folder):
 p=Path(folder);b=joblib.load(p/'tiered_bundle.joblib');z=pd.read_parquet(p/'fallback_predictions.parquet');z=z[z.model.eq('validated_common_fallback')];rows=[]
 for a,x in z.groupby('asset'):
  crash=x.actual.le(-5);rows.append(dict(asset=a,n=len(x),dates=x.date.nunique(),mae_pp=abs(x.center-x.actual).mean(),zero_mae_pp=abs(x.actual).mean(),improvement_vs_zero_pct=100*(1-abs(x.center-x.actual).mean()/abs(x.actual).mean()),direction_agreement=np.mean(np.sign(x.center)==np.sign(x.actual)),crash_n=int(crash.sum()),crash_center_underestimate_pp=np.maximum(x.loc[crash,'center']-x.loc[crash,'actual'],0).mean(),evaluation='Repeated 2023-2026 development walk-forward; actual future shocks provided retrospectively'))
 pd.DataFrame(rows).to_csv(p/'served_per_asset.csv',index=False);b['return_validation']={r['asset']:r for r in rows}
 g=pd.read_parquet(p/'research_input.parquet');hist_assets=[a for a,t in b['tiers'].items() if t=='history_only'];d=features(g[g.asset_id.isin(hist_assets)]).dropna(subset=SHOCKS+['target','end_date']);b['history_only_examples']={}
 for a,x in anchors(d).groupby('asset'):
  b['history_only_examples'][a]=[dict(date=str(r.date.date()),observed_shocks={s:float(getattr(r,s)) for s in SHOCKS},actual_return_pct=float(r.target),selection='latest historical disjoint windows; not model estimate or matched environment') for r in x.sort_values('date').tail(5).itertuples()]
 selected=set(a for a,t in b['tiers'].items() if t=='quantitative_candidate');x=z[z.asset.isin(selected)];primary=set(b['primary']['support'])
 metrics={}
 for n,assets in [('served50',selected),('preserved17',primary),('new33',selected-primary)]:
  y=x[x.asset.isin(assets)];metrics[n]=dict(n=len(y),assets=y.asset.nunique(),dates=y.date.nunique(),mae_pp=abs(y.center-y.actual).mean(),zero_mae_pp=abs(y.actual).mean(),improvement_vs_zero_pct=100*(1-abs(y.center-y.actual).mean()/abs(y.actual).mean()))
 rows=[]
 for a in sorted(selected):
  row=dict(asset=a,name=b['names'][a],sector=b['sectors'][a],priority_existing=a in primary,accepted_shocks=','.join(SHOCKS))
  for k,c in b['calculation_cache'][a]['sensitivities'].items():row[k+'_coefficient']=c['coefficient_pp_per_unit'];row[k+'_stable']=c['training_stable']
  rows.append(row)
 pd.DataFrame(rows).to_csv(p/'service50.csv',index=False,encoding='utf-8-sig')
 baseline=pd.read_parquet(p/'predictions.parquet');relative=[];rng=np.random.default_rng(4411)
 for model in ['zero','sector_history_mean','sector_shock_ridge']:
  pair=x.merge(baseline[baseline.model.eq(model)][['date','asset','center']],on=['date','asset'],suffixes=('','_baseline'),validate='one_to_one')
  pair['e']=abs(pair.center-pair.actual);pair['eb']=abs(pair.center_baseline-pair.actual);daily=pair.groupby('date')[['e','eb']].sum();n=len(daily);samples=[]
  for _ in range(2000):
   ix=np.concatenate([(i+np.arange(5))%n for i in rng.integers(0,n,size=int(np.ceil(n/5)))])[:n];r=daily.iloc[ix];samples.append(100*(1-r.e.sum()/r.eb.sum()))
  relative.append(dict(baseline=model,n=len(pair),improvement_pct=100*(1-pair.e.mean()/pair.eb.mean()),ci95=np.quantile(samples,[.025,.975]).tolist()))
 (p/'served_relative_uncertainty.json').write_text(json.dumps(relative,indent=2),encoding='utf8')
 (p/'served_cohort_metrics.json').write_text(json.dumps(metrics,indent=2),encoding='utf8');joblib.dump(b,p/'tiered_bundle.joblib');print(json.dumps(metrics))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('folder');a=p.parse_args();run(a.folder)
