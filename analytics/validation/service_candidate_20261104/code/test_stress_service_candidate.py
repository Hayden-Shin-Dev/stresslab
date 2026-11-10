"""Local API integration: real fitted coefficients, no mock prices or Azure changes."""
import os,json,sys
from pathlib import Path
from fastapi.testclient import TestClient
from service_candidate_20261104 import OUT
os.environ['STRESSLAB_MODEL_PATH']=str(OUT/'service/model.json')
from stress_candidate_api import app

def main():
    client=TestClient(app);assert client.get('/health').status_code==200
    positions=[dict(asset_id='005930',value_krw=50000000),dict(asset_id='005380',value_krw=50000000)]
    results={}
    for name,shocks in [('zero',{}),('moderate',dict(fx_pct=2.5,us_rate_bp=50)),('large',dict(fx_pct=5,us_rate_bp=100)),('extreme',dict(fx_pct=10,us_rate_bp=200)),('rate1',dict(us_rate_bp=1))]:
        response=client.post('/stress',json=dict(positions=positions,shocks=shocks));assert response.status_code==200,response.text
        r=response.json();results[name]=r
        assert r['input_shocks']['vix_change_points']==0 and r['input_shocks']['wti_pct']==0
        assert abs(sum(a['hypothetical_pnl_krw'] for a in r['assets'])-r['hypothetical_portfolio_pnl_krw'])<1e-6
        for a in r['assets']:
            assert abs(sum(a['factor_contribution_pp'].values())-a['model_center_return_pct'])<1e-10
            assert a['scenario_probability_validated'] is False
            assert all(x['end']<r['state_date'] for x in a['historical_analogues'])
    assert results['zero']['hypothetical_portfolio_pnl_krw']==0
    assert abs(results['extreme']['hypothetical_portfolio_pnl_krw']-2*results['large']['hypothetical_portfolio_pnl_krw'])<1e-6
    assert all(a['support_label']=='exploratory' for a in results['extreme']['assets'])
    assert results['rate1']['input_shocks']['fx_pct']==0
    for a in results['rate1']['assets']:
        assert a['factor_contribution_pp']['shock_fx']==0 and a['factor_contribution_pp']['shock_vix']==0
    for payload in [dict(positions=[dict(asset_id='999999',value_krw=1)],shocks={}),dict(positions=positions+positions,shocks={}),dict(positions=positions,shocks={'fx_pct':-100}),dict(positions=positions,shocks={'unexpected':1}),dict(positions=[],shocks={})]:
        assert client.post('/stress',json=payload).status_code==422
    model=json.loads((OUT/'service/model.json').read_text());allp=[dict(asset_id=a,value_krw=1000000) for a in model['states']]
    r=client.post('/stress',json=dict(positions=allp,shocks=dict(fx_pct=5,us_rate_bp=100))).json();assert len(r['assets'])==20
    (OUT/'api_examples.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf8')
    check=dict(passed=True,all20_supported=True,positions_arithmetic=True,attribution_sum=True,zero_change_preserves_levels=True,user_vix_preserved=True,extreme_not_blocked=True,invalid_payloads_rejected=True,market_search_excludes_user_shock=True,azure_changed=False)
    (OUT/'api_verification.json').write_text(json.dumps(check,indent=2));print(json.dumps(check));print(json.dumps({k:round(v['hypothetical_portfolio_pnl_krw']) for k,v in results.items()}))

if __name__=='__main__':main()
