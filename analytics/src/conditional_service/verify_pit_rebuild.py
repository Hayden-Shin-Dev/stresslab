"""Real HTTP validation of the corrected, separately versioned frozen model."""
import hashlib,itertools,json,os,socket,subprocess,sys,time
from pathlib import Path
import numpy as np
import requests

OUT=Path('reports/pit_rebuild_20261105')

def main():
    artifact=(OUT/'final_service_bundle.joblib').resolve()
    manifest_path=(OUT/'final_service_manifest.json').resolve()
    manifest=json.loads(manifest_path.read_text());before=hashlib.sha256(artifact.read_bytes()).hexdigest()
    assert before==manifest['sha256']
    env=dict(os.environ,STRESSLAB_TIERED_BUNDLE=str(artifact),STRESSLAB_MODEL_MANIFEST=str(manifest_path),STRESSLAB_REQUIRE_CERTIFIED_DATA='1')
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    log=(OUT/'integration_http.log').open('w',encoding='utf8')
    proc=subprocess.Popen([sys.executable,'-m','uvicorn','conditional_service.tiered_service:app','--host','127.0.0.1','--port',str(port)],env=env,stdout=log,stderr=log)
    base=f'http://127.0.0.1:{port}';tests=[]
    positions=[dict(asset_id=a,value_krw=1000000) for a in manifest['supported_assets']]
    shock=dict(fx_pct=5,us_rate_bp=100,wti_pct=10,vix_points=5)
    try:
        for _ in range(90):
            try:
                r=requests.get(base+'/support',timeout=2)
                if r.status_code==200:break
            except requests.RequestException:pass
            if proc.poll() is not None:raise RuntimeError('Candidate HTTP server exited')
            time.sleep(.5)
        r.raise_for_status();assert r.json()['count']==50
        info=requests.get(base+'/model-info',timeout=10).json();status=info['data_status']
        assert status['verified_asof_state_available'] and not status['deployment_blockers']
        assert not status['latest_market_state']
        assert all(v['available_at'] is None for v in status['features'].values())
        candidates=None
        for n in range(5):
            for keys in itertools.combinations(shock,n):
                request=dict(positions=positions,shocks={k:shock[k] for k in keys})
                response=requests.post(base+'/analyze',json=request,timeout=180);response.raise_for_status();v=response.json()
                assert len(v['assets'])==50 and v['publication_verified']
                assert v['analysis_flow']['state_publication_certified']
                if candidates is None:candidates=v['market_candidates']
                assert v['market_candidates']==candidates
                for row in v['assets']:
                    assert set(row['sensitivities'])==set(shock)
                    assert np.isclose(sum(row['contributions_pp'].values()),row['change_from_baseline_pp'])
                    assert np.isclose(row['scenario_return_pct'],row['baseline_model_return_pct']+row['change_from_baseline_pp'])
                    assert np.isclose(row['hypothetical_pnl_krw'],row['scenario_return_pct']*10000)
                    assert np.isclose(sum(row['shock_contribution_pnl_krw'].values()),row['shock_incremental_pnl_krw'])
                    for k,c in row['sensitivities'].items():
                        assert np.isclose(sum(c['components'].values()),c['coefficient_pp_per_unit'])
                        assert np.isclose(c['coefficient_pp_per_unit']*request['shocks'].get(k,0),row['contributions_pp'][k])
                    assert all(e['response_end_date']<v['state_date'] for e in row['historical_examples'])
                assert np.isclose(v['portfolio_hypothetical_pnl_krw'],sum(x['hypothetical_pnl_krw'] for x in v['assets']))
                tests.append(dict(shocks=list(keys),stocks=50,passed=True))
                if n==4:
                    (OUT/'request.json').write_text(json.dumps(request,indent=2),encoding='utf8')
                    (OUT/'response.json').write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf8')
        r=requests.post(base+'/analyze',json=dict(positions=positions,shocks=dict(fx_pct=100,us_rate_bp=1000,wti_pct=200,vix_points=100)),timeout=180)
        r.raise_for_status();v=r.json();assert any('extrapolation' in w for row in v['assets'] for w in row['warnings'])
        assert all(row['analysis_class']=='exploratory' for row in v['assets'])
        for payload in [dict(positions=[dict(asset_id='INVALID',value_krw=1)],shocks={}),dict(positions=positions[:1]*2,shocks={}),dict(positions=positions[:1],shocks=dict(fx_pct=-100))]:
            assert requests.post(base+'/analyze',json=payload,timeout=10).status_code==422
        (OUT/'model-info.json').write_text(json.dumps(info,ensure_ascii=False,indent=2),encoding='utf8')
        (OUT/'openapi.json').write_text(json.dumps(requests.get(base+'/openapi.json',timeout=10).json(),indent=2),encoding='utf8')
    finally:proc.terminate();proc.wait(timeout=20);log.close()
    # Evidence tampering/missing observation must fail closed, not silently use an old field.
    os.environ.update({k:env[k] for k in ['STRESSLAB_TIERED_BUNDLE','STRESSLAB_MODEL_MANIFEST','STRESSLAB_REQUIRE_CERTIFIED_DATA']})
    from . import final_service
    final_service.MANIFEST=manifest_path;final_service.bundle.cache_clear()
    from fastapi.testclient import TestClient
    from .api import app
    client=TestClient(app);bundle=final_service.bundle();small=dict(positions=positions[:2],shocks=shock)
    assert client.post('/analyze',json=small).status_code==200
    for key in ['pit_provenance','data_certification','source_observation_dates']:
        saved=bundle.pop(key)
        try:assert client.post('/analyze',json=small).status_code==503
        finally:bundle[key]=saved
    saved=bundle['pit_provenance']['observations']['korea_3y']['known_by']
    bundle['pit_provenance']['observations']['korea_3y']['known_by']='2099-01-01T00:00:00+09:00'
    try:assert client.post('/analyze',json=small).status_code==503
    finally:bundle['pit_provenance']['observations']['korea_3y']['known_by']=saved
    assert hashlib.sha256(artifact.read_bytes()).hexdigest()==before
    decision=json.loads((OUT/'rebuild_decision.json').read_text())
    report=dict(passed=True,stock_scenario_calculations=850,shock_cases=tests,
        same_market_candidates_for_all_shocks=True,contribution_and_pnl_arithmetic_passed=True,
        missing_and_future_evidence_blocked=True,extreme_scenario_exploratory=True,
        data_deployment_blockers_resolved=True,local_service_candidate=decision['performance_gate_passed'],
        live_snapshot_update_not_deployed=True,azure_changed=False,gold_changed=False,operating_model_changed=False)
    (OUT/'integration_verification.json').write_text(json.dumps(report,indent=2),encoding='utf8')
    print(json.dumps({k:v for k,v in report.items() if k!='shock_cases'}))

if __name__=='__main__':main()
