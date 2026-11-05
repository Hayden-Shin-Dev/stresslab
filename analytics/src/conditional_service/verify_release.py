"""Integration checks for selected scope, partial portfolios and contribution accounting."""
import argparse,json,os
from pathlib import Path
import numpy as np
import joblib
from fastapi.testclient import TestClient
from .core import SHOCKS
from . import release_api

def run(path):
    os.environ['STRESSLAB_RELEASE_BUNDLE']=str(Path(path).resolve());release_api.bundle.cache_clear();b=joblib.load(path);client=TestClient(release_api.app)
    r=client.get('/support');assert r.status_code==200 and r.json()['supported_shocks_by_asset']==b['support']
    a=next(a for a,s in b['support'].items() if s and len(s)<4);s=b['support'][a][0];unsupported=next(k for k in SHOCKS if k not in b['support'][a])
    position=[dict(asset_id=a,value_krw=1000000)]
    results={}
    for name,shock in [('zero',{}),('supported',{s:1}),('mixed',{s:1,unsupported:1})]:
        response=client.post('/analyze',json=dict(positions=position,shocks=shock));assert response.status_code==200,response.text
        results[name]=response.json();row=results[name]['assets'][0]
        np.testing.assert_allclose(row['baseline_model_return_pct']+sum(row['diagnostic_contributions_pp'].values()),row['exploratory_model_return_pct'],atol=1e-8)
        np.testing.assert_allclose(row['holding_krw']*row['exploratory_model_return_pct']/100,row['exploratory_pnl_krw'])
    assert results['supported']['portfolio_analysis_complete']
    mixed=results['mixed'];row=mixed['assets'][0]
    assert row['change_from_baseline_pp'] is None
    assert row['unsupported_active_shocks']==[unsupported] and row['contributions_pp'][unsupported] is None
    assert not mixed['portfolio_analysis_complete'] and mixed['portfolio_hypothetical_pnl_krw'] is None
    assert mixed['shock_contributions_krw'][unsupported] is None
    assert results['zero']['market_candidates']==results['mixed']['market_candidates']
    assert all(r['coefficient_source']=='global_partial_pool' for r in row['sensitivities'].values())
    # Mixed portfolio must not hide incomplete assets by summing only supported positions.
    second=next(k for k in b['support'] if k!=a)
    both=client.post('/analyze',json=dict(positions=position+[dict(asset_id=second,value_krw=2000000)],shocks={unsupported:1})).json()
    assert not both['portfolio_analysis_complete'] and both['portfolio_hypothetical_pnl_krw'] is None
    assert client.post('/analyze',json=dict(positions=position,shocks={'fx_pct':-100})).status_code==422
    assert client.post('/analyze',json=dict(positions=[dict(asset_id='999999',value_krw=100)],shocks={})).status_code==422
    # Every active stock-shock pair must use the learned linear coefficient exactly.
    checked=0
    for asset,shock_list in b['support'].items():
        q=b['snapshot'][b['snapshot'].asset.eq(asset)].copy();q[SHOCKS]=0
        beta,_,_=b['engine'].coefficients(q);base=b['engine'].predict(q)[0]
        for shock in shock_list:
            j=SHOCKS.index(shock)
            for magnitude in [-1,1,2]:
                changed=q.copy();changed[shock]=magnitude
                np.testing.assert_allclose(b['engine'].predict(changed)[0]-base,beta[0,j]*magnitude,atol=1e-8)
            checked+=1
    out=Path(path).parent;(out/'api_verification.json').write_text(json.dumps(dict(passed=True,checked_stock_shock_pairs=checked,supported_scope_endpoint=True,unsupported_is_null_not_zero=True,incomplete_portfolio_total_null=True,diagnostic_accounting_exact=True,A_invariant_to_shocks=True,global_coefficient_default=True,invalid_input_rejected=True,cloud_changed=False),indent=2),encoding='utf8')
    (out/'partial_analysis_example.json').write_text(json.dumps(mixed,ensure_ascii=False,indent=2),encoding='utf8');print('Selected service API checks passed')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('bundle');run(p.parse_args().bundle)
