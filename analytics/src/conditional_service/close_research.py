"""Freeze the existing stock-specific service candidate; do not promote cloud models."""
import argparse,json,hashlib
from pathlib import Path
import pandas as pd,numpy as np,joblib
from .core import features,SHOCKS

def run(root,out):
 root=Path(root);out=Path(out);old=root/'reports/support_expansion_20261104';b=joblib.load(old/'tiered_bundle.joblib')
 p=pd.read_parquet(out/'predictions.parquet');reference=p[p.model.eq('sector_shock300')]
 served=pd.read_parquet(old/'fallback_predictions.parquet');served=served[served.model.eq('validated_common_fallback')]
 compare=reference[['date','asset','actual','center']].merge(served[['date','asset','actual','center']],on=['date','asset'],suffixes=('_sector','_existing'),validate='one_to_one');np.testing.assert_allclose(compare.actual_sector,compare.actual_existing)
 current=abs(compare.center_existing-compare.actual_existing).mean();sector=abs(compare.center_sector-compare.actual_sector).mean()
 # Service decision: retain stock-specific estimates when bounded tuning has no improvement;
 # industry-only model remains an honest reference, not relabeled as individual sensitivity.
 audit=json.loads((out/'data_audit.json').read_text())['checks']
 clean=(audit['duplicate_keys']==0 and audit['mock_rows']==0 and not any(audit['observation_dates_after_state'].values()) and audit['finite_features'])
 decision=dict(service_candidate_confirmed=bool(clean and current<=sector*1.03),production_approved=False,additional_model_experiments_stopped=True,selected='existing_partial_pool_stock_coefficients',mae_pp=current,sector_baseline_mae_pp=sector,gap_vs_sector_pct=100*(current/sector-1),same_rows=len(compare),service_scope='Explainable hypothetical sensitivity simulation, not calibrated loss forecast',reason='None of five same-structure tuned stock-coefficient variants improve current MAE. Sector-only mean improves modestly but removes within-sector coefficient differences. Preserve current stock-specific calculations and disclose sector benchmark.',selection_is_development_decision_not_blind=True,approval_scope='Local project service candidate only; source publication and corporate actions remain uncertified')
 (out/'decision.json').write_text(json.dumps(decision,indent=2),encoding='utf8')
 g=pd.read_parquet(old/'research_input.parquet');dates=g[g.asset_id.eq('005930')].sort_values('trading_date').iloc[-1]
 b['release_decision']=decision;b['source_observation_dates']={k:str(dates[k+'_observation_date']) for k in ['usdkrw','us_treasury_10y','wti','vix','korea_3y']}
 joblib.dump(b,out/'final_service_bundle.joblib')
 # Validate observed extreme price path instead of automatically deleting a real rally.
 records=[]
 for f in (root/'data/research/exposure_universe_20261103/stocks/073240').glob('*.json'):
  records.extend(r for r in json.loads(f.read_text(encoding='utf8')) if '2018/03/28'<=r['TRD_DD']<='2018/04/06')
 raw=pd.DataFrame(records).sort_values('TRD_DD');raw.to_csv(out/'extreme_official_price_path.csv',index=False)
 price=raw.set_index('TRD_DD').TDD_CLSPRC.str.replace(',','').astype(float)
 np.testing.assert_allclose((price['2018/04/05']/price['2018/03/29']-1)*100,101.12676056338029)
 # Check training-vs-calibration after normalizing for regime return magnitude.
 f=features(g);d=f[f.asset.isin(reference.asset.unique())].dropna(subset=SHOCKS+['target','end_date'])
 scores=pd.read_csv(out/'training_calibration.csv');normalizers={}
 from .finalize_model import BoundedFactor,CONFIGS,stats
 repairs=[]
 from .core import anchors
 for year in [2023,2024,2025,2026]:
  tr=anchors(d[d.end_date<pd.Timestamp(year-1,1,1)-pd.Timedelta(days=20)])
  cal=anchors(d[(d.date>=pd.Timestamp(year-1,1,1))&(d.end_date<pd.Timestamp(year,1,1)-pd.Timedelta(days=20))])
  normalizers[(year,'training')]=abs(tr.target).mean();normalizers[(year,'calibration')]=abs(cal.target).mean()
  raw=d[d.end_date<pd.Timestamp(year-1,1,1)-pd.Timedelta(days=20)]
  window=raw[raw.date>=raw.end_date.max()-pd.DateOffset(years=10)];fitrows=anchors(window)
  mask=scores.year.eq(year)&scores.stage.eq('training')&scores.model.eq('pool300_dev10_10y')
  if int(scores.loc[mask,'n'].iloc[0])!=len(fitrows):
   model=BoundedFactor(next(c for c in CONFIGS if c['name']=='pool300_dev10_10y'),b['sectors']).fit(raw)
   result=stats(fitrows.target,model.predict(fitrows))
   for key,value in result.items():scores.loc[mask,key]=value
   repairs.append(dict(year=year,issue='10-year in-sample metric incorrectly included older rows; model training and evaluation were unaffected',correct_training_n=len(fitrows)))
  normalizers[(year,'training10')]=abs(fitrows.target).mean()
 scores['zero_mae_pp']=[normalizers[(r.year,'training10' if r.stage=='training' and r.model=='pool300_dev10_10y' else r.stage)] for r in scores.itertuples()];scores['mae_relative_to_zero']=scores.mae_pp/scores.zero_mae_pp;scores.to_csv(out/'overfit_audit.csv',index=False)
 scores.drop(columns=['zero_mae_pp','mae_relative_to_zero']).to_csv(out/'training_calibration.csv',index=False)
 (out/'audit_metric_corrections.json').write_text(json.dumps(repairs,indent=2),encoding='utf8')
 fitted=[]
 for name in ['primary','expanded']:
  e=b[name]['engine'];m=e.global_model;t=f[f.asset.isin(m.assets)&(f.end_date<pd.to_datetime(g.trading_date).max()-pd.Timedelta(days=20))].dropna(subset=SHOCKS+['target','end_date'])
  np.testing.assert_allclose(t[m.columns].mean().to_numpy(),m.scaler.mean_,atol=1e-8)
  fitted.append(dict(model=name,training_rows=len(t),last_label=str(t.end_date.max()),scaler_fitted_on_training_only=True,coefficients_finite=bool(np.isfinite(m.model.coef_).all())))
 (out/'fitted_model_audit.json').write_text(json.dumps(fitted,indent=2),encoding='utf8')
 # Annual original-vs-reference results, no selection from single winning year.
 compare['year']=compare.date.dt.year
 pd.DataFrame([dict(year=y,n=len(z),current_mae_pp=abs(z.center_existing-z.actual_existing).mean(),sector_mae_pp=abs(z.center_sector-z.actual_sector).mean()) for y,z in compare.groupby('year')]).to_csv(out/'same_rows_by_year.csv',index=False)
 print(json.dumps(decision),flush=True)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--root',required=True);p.add_argument('--out',required=True);a=p.parse_args()
 from threadpoolctl import threadpool_limits
 with threadpool_limits(limits=2):run(a.root,a.out)
