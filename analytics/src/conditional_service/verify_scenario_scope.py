"""Check the service presentation against model arithmetic without retraining."""
import hashlib,json,os
from pathlib import Path
import numpy as np
import pandas as pd

def main():
    root=Path(os.environ.get('STRESSLAB_REBUILD_OUT','reports/service_scope_20261105')).resolve()
    os.environ['STRESSLAB_TIERED_BUNDLE']=str(root/'final_service_bundle.joblib')
    os.environ['STRESSLAB_MODEL_MANIFEST']=str(root/'final_service_manifest.json')
    from . import final_service
    final_service.MANIFEST=root/'final_service_manifest.json'
    final_service.bundle.cache_clear()
    from .api import app
    from fastapi.testclient import TestClient
    client=TestClient(app)
    ids=[a['asset_id'] for a in client.get('/support').json()['assets']][:2]
    request={'positions':[{'asset_id':a,'value_krw':v} for a,v in zip(ids,[1000000,3000000])],
             'shocks':{'fx_pct':5,'us_rate_bp':100,'wti_pct':10,'vix_points':5}}
    def call(q):
        r=client.post('/analyze',json=q);assert r.status_code==200,r.text
        v=r.json();s=v['portfolio_summary']
        np.testing.assert_allclose(s['baseline_pnl_krw']+s['incremental_pnl_krw'],s['scenario_pnl_krw'])
        np.testing.assert_allclose(sum(s['shock_contributions_krw'].values()),s['incremental_pnl_krw'],atol=1e-6)
        np.testing.assert_allclose(sum(a['comparison']['scenario_pnl_krw'] for a in v['assets']),s['scenario_pnl_krw'])
        np.testing.assert_allclose(sum(a['portfolio_weight_pct'] for a in v['assets']),100)
        if s['gross_incremental_loss_krw']:
            np.testing.assert_allclose(sum(a['share_of_gross_incremental_loss_pct'] for a in v['assets']),100)
        else:assert all(a['share_of_gross_incremental_loss_pct'] is None for a in v['assets'])
        assert not v['service_scope']['forecast_accuracy_approved']
        return v
    result=call(request)
    zero=call(dict(request,shocks={}))
    assert zero['portfolio_summary']['incremental_pnl_krw']==0
    assert zero['portfolio_summary']['largest_adverse_asset_id'] is None
    opposite=call(dict(request,shocks={k:-v for k,v in request['shocks'].items()}))
    doubled=call(dict(request,positions=[dict(p,value_krw=p['value_krw']*2) for p in request['positions']]))
    assert result['market_candidates']==zero['market_candidates']==opposite['market_candidates']
    for a,b,c in zip(result['assets'],opposite['assets'],doubled['assets']):
        np.testing.assert_allclose(a['change_from_baseline_pp'],-b['change_from_baseline_pp'],atol=1e-10)
        np.testing.assert_allclose(c['hypothetical_pnl_krw'],2*a['hypothetical_pnl_krw'])
        assert a['sensitivities']==c['sensitivities']
    old=pd.read_parquet('reports/pit_rebuild_20261105/rebuilt_predictions.parquet')
    new=pd.read_parquet(root/'rebuilt_predictions.parquet')
    pd.testing.assert_frame_equal(old,new)
    report=dict(passed=True,scope='sensitivity_scenario_only',unequal_holdings_sum=True,
                zero_shock_preserves_baseline=True,opposite_shock_reverses_increment=True,
                holding_scale_preserves_coefficients=True,A_unchanged_by_shocks=True,
                same_corrected_data_retraining_reproduced=True,performance_improved=False,
                local_scenario_integration_ready=True,forecast_performance_approved=False,
                azure_deployed=False)
    for name,value in [('scope_verification.json',report),('example_request.json',request),('example_response.json',result)]:
        (root/name).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(report))

if __name__=='__main__':main()
