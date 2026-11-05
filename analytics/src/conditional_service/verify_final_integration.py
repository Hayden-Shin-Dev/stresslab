"""Run from the local research root. Read-only data audit and real HTTP tests."""
import hashlib
import itertools
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import numpy as np
import pandas as pd
import requests
from .service_data import available_asof


def main():
    out=Path('reports/service_integration_20261104');out.mkdir(exist_ok=True)
    module=Path(__file__).parent
    manifest=json.loads((module/'final_service_manifest.json').read_text(encoding='utf8'))
    artifact=Path('reports/final_model_20261104/final_service_bundle.joblib').resolve()
    assert hashlib.sha256(artifact.read_bytes()).hexdigest()==manifest['sha256']
    assets=manifest['supported_assets']
    g=pd.read_parquet('reports/support_expansion_20261104/research_input.parquet')
    g=g[g.asset_id.isin(assets)].copy()
    availability=[c for c in g if c.endswith('_available_at')]
    checks=[]
    for a,q in g.groupby('asset_id'):
        q=q.sort_values('trading_date');valid=q.quality_status.eq('valid')
        assert not q.trading_date.duplicated().any()
        assert not q.is_mock.any()
        assert (q.loc[valid,'close']>0).all()
        assert q.loc[valid,'price_basis'].eq('adjusted').all()
        checks.append(dict(asset_id=a,rows=len(q),valid_rows=int(valid.sum()),
            quarantined_rows=int((~valid).sum()),adjustment_versions=sorted(q.adjustment_version.dropna().unique().tolist()),
            nonpositive_valid_prices=int((q.loc[valid,'close']<=0).sum()),
            complete_corporate_action_certification=False))
    source=json.loads(Path('reports/support_expansion_20261104/source_manifest.json').read_text(encoding='utf8'))
    hashes=[]
    for record in source['raw_files']:
        path=Path(record['file'])
        if path.parent.name in assets:
            hashes.append(hashlib.sha256(path.read_bytes()).hexdigest()==record['sha256'])
    assert all(hashes)
    audit=dict(assets=len(assets),rows=len(g),source_hashes_checked=len(hashes),
        source_hash_failures=sum(not x for x in hashes),
        missing_available_at={c:int(g[c].isna().sum()) for c in availability},
        price_checks=checks,prior_20_stock_bridge=json.loads(Path('reports/price_bridge_20261102/current_reference_test.json').read_text()),
        conclusion='Frozen training macro inputs still require point-in-time review. See source_certification.json for independently acquired publication and raw-price evidence.')
    (out/'data_provenance_audit.json').write_text(json.dumps(audit,indent=2),encoding='utf8')
    # A verified older observation is selected; missing metadata never becomes a zero.
    records=[dict(observation_date='2026-10-28',available_at='2026-10-29T09:00:00+09:00',value=10,verified=True),
        dict(observation_date='2026-10-29',available_at='2026-10-30T16:00:00+09:00',value=20,verified=True),
        dict(observation_date='2026-10-30',available_at=None,value=30,verified=True)]
    assert available_asof(records,'2026-10-30T15:30:00+09:00')['value']==10
    assert available_asof(records[1:],'2026-10-30T15:30:00+09:00') is None
    # Request validation through a real HTTP server, not only direct function calls.
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    env=dict(os.environ,STRESSLAB_TIERED_BUNDLE=str(artifact))
    log=(out/'http_server.log').open('w',encoding='utf8')
    proc=subprocess.Popen([sys.executable,'-m','uvicorn','conditional_service.tiered_service:app',
        '--host','127.0.0.1','--port',str(port)],env=env,stdout=log,stderr=log)
    base=f'http://127.0.0.1:{port}'
    tests=[]
    try:
        for _ in range(60):
            try:
                r=requests.get(base+'/support',timeout=3)
                if r.status_code==200:break
            except requests.RequestException:pass
            if proc.poll() is not None:raise RuntimeError('Local test server failed')
            time.sleep(.5)
        r.raise_for_status();assert r.json()['count']==50
        info=requests.get(base+'/model-info',timeout=10).json()
        assert info['artifact']['sha256']==manifest['sha256']
        assert not info['data_status']['latest_market_state']
        positions=[dict(asset_id=a,value_krw=1000000) for a in assets]
        shocks=dict(fx_pct=5,us_rate_bp=100,wti_pct=10,vix_points=5)
        candidate_dates=None
        for n in range(5):
            for keys in itertools.combinations(shocks,n):
                payload=dict(positions=positions,shocks={s:shocks[s] for s in keys})
                response=requests.post(base+'/analyze',json=payload,timeout=120)
                response.raise_for_status();v=response.json()
                assert len(v['assets'])==50
                if candidate_dates is None:candidate_dates=v['market_candidates']
                assert v['market_candidates']==candidate_dates
                for row in v['assets']:
                    assert len(row['sensitivities'])==4
                    assert np.isclose(sum(row['contributions_pp'].values()),row['change_from_baseline_pp'])
                    assert np.isclose(row['scenario_return_pct'],row['baseline_model_return_pct']+row['change_from_baseline_pp'])
                    assert np.isclose(row['hypothetical_pnl_krw'],row['scenario_return_pct']*10000)
                    assert row['analysis_class']=='exploratory'
                assert np.isclose(v['portfolio_hypothetical_pnl_krw'],sum(r['hypothetical_pnl_krw'] for r in v['assets']))
                tests.append(dict(shocks=list(keys),stocks=50,passed=True))
                if n==4:
                    (out/'request.json').write_text(json.dumps(payload,indent=2),encoding='utf8')
                    (out/'response.json').write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf8')
        for name,payload in [('unsupported',dict(positions=[dict(asset_id='NOT_SUPPORTED',value_krw=1)],shocks={})),
            ('duplicate',dict(positions=[positions[0],positions[0]],shocks={})),
            ('missing_positions',dict(shocks={})),
            ('invalid_level',dict(positions=positions[:1],shocks=dict(fx_pct=-100)))]:
            assert requests.post(base+'/analyze',json=payload,timeout=20).status_code==422
            tests.append(dict(case=name,passed=True))
        v=requests.post(base+'/analyze',json=dict(positions=positions,shocks=dict(fx_pct=100,us_rate_bp=1000,wti_pct=200,vix_points=100)),timeout=120).json()
        assert all(r['analysis_class']=='exploratory' for r in v['assets'])
        assert any('extrapolation' in w for r in v['assets'] for w in r['warnings'])
        tests.append(dict(case='extreme_exploratory',stocks=50,passed=True))
        schema=requests.get(base+'/openapi.json',timeout=10).json()
        (out/'openapi.json').write_text(json.dumps(schema,indent=2),encoding='utf8')
    finally:
        proc.terminate();proc.wait(timeout=15);log.close()
    # Missing/incorrect artifact cannot be served.
    from . import final_service
    from fastapi import HTTPException
    from fastapi.testclient import TestClient
    from .api import app as canonical_app
    os.environ['STRESSLAB_TIERED_BUNDLE']=str(artifact)
    final_service.bundle.cache_clear()
    client=TestClient(canonical_app)
    assert client.get('/support').json()['count']==50
    assert client.get('/model-info').json()['artifact']['sha256']==manifest['sha256']
    small=dict(positions=positions[:2],shocks=dict(fx_pct=5,us_rate_bp=100,wti_pct=10,vix_points=5))
    small_response=client.post('/analyze',json=small)
    assert small_response.status_code==200
    (out/'example_request.json').write_text(json.dumps(small,indent=2),encoding='utf8')
    (out/'example_response.json').write_text(json.dumps(small_response.json(),ensure_ascii=False,indent=2),encoding='utf8')
    cached=final_service.bundle()
    # Simulate missing downstream evidence, without writing or changing model artifact.
    saved=cached['calculation_cache'].pop(assets[0])
    try:assert client.post('/analyze',json=small).status_code==503
    finally:cached['calculation_cache'][assets[0]]=saved
    missing_observations=cached.pop('source_observation_dates')
    try:
        status=client.get('/model-info').json()['data_status']
        assert status['features']['fx_trend20']['observation_date'] is None
        assert not status['latest_market_state']
    finally:cached['source_observation_dates']=missing_observations
    original=os.environ.get('STRESSLAB_TIERED_BUNDLE')
    os.environ['STRESSLAB_TIERED_BUNDLE']=str(out/'missing.joblib');final_service.bundle.cache_clear()
    try:
        final_service.bundle();raise AssertionError('Missing model accepted')
    except HTTPException as exc:assert exc.status_code==503
    finally:
        if original is None:os.environ.pop('STRESSLAB_TIERED_BUNDLE',None)
        else:os.environ['STRESSLAB_TIERED_BUNDLE']=original
        final_service.bundle.cache_clear()
    assert hashlib.sha256(artifact.read_bytes()).hexdigest()==manifest['sha256']
    report=dict(passed=True,http_cases=tests,stock_scenario_calculations=850,
        availability_future_and_missing_cases_passed=True,missing_artifact_blocked=True,
        missing_calculation_data_blocked=True,missing_observation_dates_not_imputed=True,
        both_api_entrypoints_use_frozen_artifact=True,
        model_unchanged=True,training_performed=False,azure_modified=False,
        deployment_ready=False,blockers=audit['conclusion'])
    (out/'verification.json').write_text(json.dumps(report,indent=2),encoding='utf8')
    print(json.dumps({k:v for k,v in report.items() if k!='http_cases'}))

if __name__=='__main__':main()
