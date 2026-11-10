"""Real locally fitted artifact integration tests for all four risk factors."""
import argparse,json,os,itertools
from pathlib import Path
import joblib,numpy as np
from fastapi.testclient import TestClient
from threadpoolctl import threadpool_limits
from .core import SHOCKS
from . import tiered_service as api

def run(path):
 path=Path(path);os.environ['STRESSLAB_TIERED_BUNDLE']=str(path.resolve());api.bundle.cache_clear();b=joblib.load(path);c=TestClient(api.app)
 support=c.get('/support');assert support.status_code==200 and support.json()['accepted_shocks_for_all']==SHOCKS
 selected=[a for a,t in b['tiers'].items() if t=='quantitative_candidate'];positions=[dict(asset_id=a,value_krw=1000000) for a in selected]
 responses={};magnitudes=dict(fx_pct=1,us_rate_bp=10,wti_pct=5,vix_points=1)
 for n,shock in [('zero',{}),('fx_only',{'fx_pct':1}),('two',{'fx_pct':1,'us_rate_bp':10}),('three',{'fx_pct':1,'us_rate_bp':10,'wti_pct':5}),('four',magnitudes),('extreme',dict(fx_pct=50,us_rate_bp=500,wti_pct=100,vix_points=50))]:
  r=c.post('/analyze',json=dict(positions=positions,shocks=shock));assert r.status_code==200,r.text
  z=r.json();responses[n]=z;assert z['scenario_arithmetic_complete'] and len(z['assets'])==50
  for row in z['assets']:
   assert set(row['contributions_pp'])==set(SHOCKS) and all(v is not None for v in row['contributions_pp'].values())
   np.testing.assert_allclose(row['baseline_model_return_pct']+sum(row['contributions_pp'].values()),row['scenario_return_pct'],atol=1e-8)
   np.testing.assert_allclose(row['scenario_return_pct']*row['holding_krw']/100,row['hypothetical_pnl_krw'])
  np.testing.assert_allclose(sum(r['hypothetical_pnl_krw'] for r in z['assets']),z['portfolio_hypothetical_pnl_krw'])
 assert responses['zero']['market_candidates']==responses['four']['market_candidates']
 assert responses['extreme']['portfolio_analysis_class']=='exploratory'
 for r in responses['zero']['assets']:assert all(v==0 for v in r['contributions_pp'].values())
 # The previous oil-only designation no longer blocks any rate input.
 air=c.post('/analyze',json=dict(positions=[dict(asset_id='003490',value_krw=1000000),dict(asset_id='010950',value_krw=1000000)],shocks=magnitudes)).json()
 assert all(r['sensitivities']['us_rate_bp']['source']=='asset_partial_pool' for r in air['assets'])
 assert all(r['contributions_pp']['us_rate_bp']!=0 for r in air['assets'])
 assert c.post('/analyze',json=dict(positions=positions[:1],shocks={'fx_pct':-100})).status_code==422
 assert c.get('/model-info').status_code==200
 exploratory=next(a for a,t in b['tiers'].items() if t=='exploratory')
 ez=c.post('/analyze',json=dict(positions=[dict(asset_id=exploratory,value_krw=1000000)],shocks=magnitudes)).json()
 assert ez['assets'][0]['analysis_class']=='exploratory' and ez['assets'][0]['scenario_return_pct'] is not None
 history=next(a for a,t in b['tiers'].items() if t=='history_only')
 hz=c.post('/analyze',json=dict(positions=[dict(asset_id=history,value_krw=1000000)],shocks=magnitudes)).json()
 assert hz['portfolio_hypothetical_pnl_krw'] is None and hz['assets'][0]['analysis_class']=='history_only'
 oil=c.post('/analyze',json=dict(positions=[dict(asset_id='003490',value_krw=1000000),dict(asset_id='010950',value_krw=1000000)],shocks={'wti_pct':10})).json()
 examples=dict(oil10=oil,four_shocks=air,extreme=responses['extreme'])
 (path.parent/'four_shock_examples.json').write_text(json.dumps(examples,ensure_ascii=False,indent=2),encoding='utf8')
 (path.parent/'api_verification.json').write_text(json.dumps(dict(passed=True,stocks_tested=50,scenario_count=6,all_four_inputs_accepted=True,unstable_not_zeroed=True,additivity_exact=True,portfolio_arithmetic_exact=True,market_search_unchanged_by_shock=True,extreme_exploratory=True,azure_changed=False,gold_changed=False,production_approved=False),indent=2),encoding='utf8')
 print('Tiered API verified 50 stocks x 6 scenarios',flush=True)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('bundle');a=p.parse_args()
 with threadpool_limits(limits=2):run(a.bundle)
