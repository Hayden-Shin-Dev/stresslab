"""Exact formula, model routing, unit and API checks on trained artifact."""
import argparse,json,os
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
from fastapi.testclient import TestClient
from .core import SHOCKS
from . import sensitivity_api

def run(path):
    os.environ['STRESSLAB_SENSITIVITY_BUNDLE']=str(Path(path).resolve());sensitivity_api.bundle.cache_clear()
    b=joblib.load(path);client=TestClient(sensitivity_api.app);assets=list(b['snapshot'].asset[:2]);positions=[dict(asset_id=a,value_krw=1000000) for a in assets]
    results=[];candidate_dates=[]
    for shocks in [{},{'us_rate_bp':1},{'wti_pct':10},{'fx_pct':5,'us_rate_bp':100},{'fx_pct':10,'us_rate_bp':200}]:
        r=client.post('/analyze',json=dict(positions=positions,shocks=shocks));assert r.status_code==200,r.text;z=r.json();candidate_dates.append(z['market_candidates'])
        for a in z['assets']:
            np.testing.assert_allclose(a['baseline_model_return_pct']+sum(a['contributions_pp'].values()),a['exploratory_model_return_pct'],atol=1e-8)
            np.testing.assert_allclose(a['holding_krw']*a['exploratory_model_return_pct']/100,a['exploratory_pnl_krw'])
            for s in SHOCKS:np.testing.assert_allclose(a['sensitivities'][s]['coefficient_pp_per_unit']*shocks.get(s,0),a['contributions_pp'][s])
            if a['status']=='limited_evidence':assert a['model_return_pct'] is None and a['hypothetical_pnl_krw'] is None
        np.testing.assert_allclose(sum(a['exploratory_pnl_krw'] for a in z['assets']),z['exploratory_portfolio_pnl_krw'])
        results.append(z)
    assert all(x==candidate_dates[0] for x in candidate_dates)
    bad=client.post('/analyze',json=dict(positions=positions,shocks={'fx_pct':-100}));assert bad.status_code==422
    doubled=[dict(asset_id=p['asset_id'],value_krw=2*p['value_krw']) for p in positions]
    x=client.post('/analyze',json=dict(positions=doubled,shocks={'wti_pct':10})).json()
    np.testing.assert_allclose(x['exploratory_portfolio_pnl_krw'],2*results[2]['exploratory_portfolio_pnl_krw'])
    engine=b['engine'];q=b['snapshot'].copy();q[SHOCKS]=0;base=engine.predict(q)
    for s in SHOCKS:
        x=q.copy();x[s]=1;y=q.copy();y[s]=2
        np.testing.assert_allclose(engine.predict(y)-base,2*(engine.predict(x)-base),atol=1e-8)
    # State intervention only; no shock or target modifications, not a performance test.
    state=[]
    for level in [.25,.75]:
        x=q.copy();x.market_vol20=engine.history.market_vol20.quantile(level)
        beta,ok,detail=engine.coefficients(x)
        for i,a in enumerate(x.asset):
            for j,s in enumerate(SHOCKS):state.append(dict(asset=a,shock=s,state_vol_quantile=level,coefficient=beta[i,j],state_coefficient_used=bool(detail['use_state'][i,j]),stable=bool(ok[i,j])))
    folder=Path(path).parent;pd.DataFrame(state).to_csv(folder/'state_intervention.csv',index=False)
    (folder/'api_verification.json').write_text(json.dumps(dict(exact_contributions=True,A_unchanged_by_user_shocks=True,unit_1bp_checked=True,zero_means_unchanged=True,holding_amount_scaling=True,unstable_primary_values_null=True,affine_shock_response=True,invalid_shock_rejected=True,production_deployed=False),indent=2),encoding='utf8')
    print('Sensitivity API and formula checks passed')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('bundle');run(p.parse_args().bundle)
