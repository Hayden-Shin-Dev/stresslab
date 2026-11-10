"""Four common risk factors for every supported asset; confidence is not an input gate."""
import os,json
from functools import lru_cache
import joblib,numpy as np,pandas as pd
from fastapi import FastAPI,HTTPException
from .api import Request
from .core import SHOCKS,STATE,market_search
from .four_shock_policy import shared
from .service_contract import AnalysisResponse

app=FastAPI(title='StressLab four shock sensitivity candidate',version='3.0')

@lru_cache(maxsize=1)
def bundle():
 from .final_service import bundle as frozen_bundle
 return frozen_bundle()

def analyze(b,positions,shocks):
 if not positions or len({p['asset_id'] for p in positions})!=len(positions):raise ValueError('Unique positions required')
 if set(shocks)-set(SHOCKS):raise ValueError('Unknown shock')
 sh={s:float(shocks.get(s,0)) for s in SHOCKS}
 if not np.isfinite(list(sh.values())).all() or sh['fx_pct']<=-100 or sh['wti_pct']<=-100:raise ValueError('Invalid shock')
 source=b['expanded'];snap=source['snapshot'];h=source['engine'].history;candidates=market_search(h,snap.iloc[0]);candidate_dates=set(candidates.date)
 rows=[]
 for p in positions:
  a=p['asset_id'];value=float(p['value_krw'])
  if a not in b['tiers'] or not np.isfinite(value) or value<=0:raise ValueError('Unknown asset or invalid holding')
  selected=b['primary'] if a in b['primary']['support'] else b['expanded'];engine=selected['engine'];q=selected['snapshot'][selected['snapshot'].asset.eq(a)].copy()
  if q.empty:
   rows.append(dict(asset_id=a,name=b['names'][a],analysis_class='history_only',reason='Insufficient certified history for fitted stock coefficients',accepted_shocks=SHOCKS,historical_examples=b.get('history_only_examples',{}).get(a,[]),scenario_return_pct=None,hypothetical_pnl_krw=None,contributions_pp={s:None for s in SHOCKS}));continue
  if q.vix_level.iloc[0]+sh['vix_points']<0:raise ValueError('Negative VIX level')
  cache=b['calculation_cache'][a];base=cache['baseline'];hist=engine.history[engine.history.asset.eq(a)]
  joint=(((hist[SHOCKS]-pd.Series(sh))/engine.iqr).abs().max(axis=1)<=1)&(((hist[STATE]-q.iloc[0][STATE].astype(float))/engine.state_iqr).pow(2).mean(axis=1)<=1)
  detail={};contrib={};warnings=[]
  for s in SHOCKS:
   c=dict(cache['sensitivities'][s]);outside=not c['observed_range'][0]<=sh[s]<=c['observed_range'][1]
   c['outside_observed_range']=outside;c['evidence']=b['evidence'].get(a,{}).get(s)
   ev=c['evidence'] or {}
   out_supported=bool(ev.get('oos_association_aligned_ci_excludes_zero') and ev.get('approx_bh_q',1)<=.1)
   c['evidence_level']='training_stable_and_adjusted_oos_association' if c['training_stable'] and out_supported else ('training_stable_oos_limited' if c['training_stable'] else 'unstable_exploratory')
   c['economic_nonexposure_not_inferred']=True;detail[s]=c;contrib[s]=c['coefficient_pp_per_unit']*sh[s]
   if sh[s] and not c['training_stable']:warnings.append(s+': coefficient unstable; exploratory estimate, not zero impact')
   if sh[s] and outside:warnings.append(s+': extrapolation')
   if sh[s] and not out_supported:warnings.append(s+': stock-specific out-of-sample association not established')
  if any(sh.values()) and int(joint.sum())<15:warnings.append('Sparse joint state and shock support')
  if b['tiers'][a]!='quantitative_candidate':warnings.append('Exploratory stock tier')
  center=base+sum(contrib.values());pnl=center*value/100
  if not np.isfinite([center,pnl]).all():raise ValueError('Numerical overflow')
  # Exact direct model check when no common fallback changes the coefficient equation.
  q[SHOCKS]=[sh[s] for s in SHOCKS]
  if not cache['used_common']:np.testing.assert_allclose(center,engine.global_model.predict(q)[0],atol=1e-8)
  evidence=hist[hist.date.isin(candidate_dates)].copy();evidence['shock_distance']=((evidence[SHOCKS]-pd.Series(sh))/engine.iqr).pow(2).mean(axis=1)
  examples=[dict(date=str(r.date.date()),observed_shocks={s:float(getattr(r,s)) for s in SHOCKS},actual_return_pct=float(r.target),replay_pnl_krw=float(r.target*value/100)) for r in evidence.sort_values('shock_distance').head(5).itertuples()]
  rows.append(dict(asset_id=a,name=b['names'][a],analysis_class='exploratory' if warnings else 'quantitative_model_candidate',baseline_model_return_pct=base,scenario_return_pct=center,change_from_baseline_pp=sum(contrib.values()),contributions_pp=contrib,hypothetical_pnl_krw=pnl,sensitivities=detail,joint_support_nonoverlap_windows=int(joint.sum()),warnings=warnings,historical_examples=examples,model_version=selected['version'],training_label_end=str(engine.train_label_end),dataset_version=selected['audit']['dataset_version'],return_validation=b.get('return_validation',{}).get(a),holding_krw=value))
 complete=all(r['scenario_return_pct'] is not None for r in rows)
 return dict(version='four-common-shocks-local-v1',release_decision=b.get('release_decision'),source_observation_dates=b.get('source_observation_dates'),state_date=str(snap.date.iloc[0].date()),horizon_trading_days=5,shocks=sh,market_candidates=[str(d.date()) for d in candidates.date],assets=rows,portfolio_hypothetical_pnl_krw=sum(r['hypothetical_pnl_krw'] for r in rows) if complete else None,portfolio_analysis_class='incomplete' if not complete else ('exploratory' if any(r['analysis_class']=='exploratory' for r in rows) else 'quantitative_model_candidate'),scenario_arithmetic_complete=complete,production_approved=False,publication_verified=False,interpretation='All four inputs are changes, zero means level unchanged. Statistical scenario, not causal effect or certified loss prediction. Stock-shock interactions absent from additive model; joint nonlinear interactions unvalidated.')

@app.get('/support')
def support():
 from .final_service import support as final_support
 return final_support()

@app.get('/model-info')
def model_info():
 from .final_service import model_info as final_info
 return final_info()

@app.post('/analyze',response_model=AnalysisResponse)
def post(r:Request):
 from .final_service import post as final_post
 return final_post(r)


def prepare_cache(b):
 cache={}
 for a,tier in b['tiers'].items():
  selected=b['primary'] if a in b['primary']['support'] else b['expanded'];e=selected['engine'];q=selected['snapshot'][selected['snapshot'].asset.eq(a)].copy()
  if q.empty:continue
  q[SHOCKS]=0;base=float(e.global_model.predict(q)[0]);beta,stable,det=e.coefficients(q);common=shared(e.global_model)
  v=np.stack([shared(m) for m,_ in e.checks]+[common]);common_stable=((v>0).all(0)|(v<0).all(0))&(v.std(0)/np.maximum(abs(np.median(v,axis=0)),1e-8)<=.75)
  hist=e.history[e.history.asset.eq(a)];ss={};used=[]
  for j,s in enumerate(SHOCKS):
   use=s in b['common_fallback_policy'].get(a,[]) and common_stable[j]
   if use:used.append(s)
   ss[s]=dict(coefficient_pp_per_unit=float(common[j] if use else beta[0,j]),source='common_validated_calibration' if use else 'asset_partial_pool',training_stable=bool(common_stable[j] if use else stable[0,j]),training_coefficient_cv=float(det['global_spread'][0,j]),observed_range=[float(hist[s].min()),float(hist[s].max())],components=e.global_model.slope_parts(q.iloc[0],s),coefficient_calculation='shared only' if use else 'shared plus asset deviation',validation_model_scope='Expanded-cohort residual association; original17 return benchmark evaluated separately')
  cache[a]=dict(baseline=base,sensitivities=ss,used_common=used)
 b['calculation_cache']=cache;return b

if __name__=='__main__':
 import argparse
 p=argparse.ArgumentParser();p.add_argument('artifact');a=p.parse_args();b=prepare_cache(joblib.load(a.artifact));joblib.dump(b,a.artifact);print('cache prepared',len(b['calculation_cache']))
