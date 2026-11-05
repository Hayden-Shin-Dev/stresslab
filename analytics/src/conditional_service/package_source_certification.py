"""Package source evidence and verify serving guards; never train or mutate Gold."""
import hashlib,json,os
from pathlib import Path
from .service_data import available_asof

def main():
    root=Path('reports/service_certification_20261104')
    module=Path(__file__).parent
    p=json.loads((root/'publication_audit.json').read_text())
    c=json.loads((root/'corporate_adjustment_audit.json').read_text())
    e=json.loads((root/'ecos_dated_evidence.json').read_text())
    assert hashlib.sha256(Path('data/research/service_certification_20261104/bok/20261029.html').read_bytes()).hexdigest()==e['sha256']
    m=json.loads((module/'final_service_manifest.json').read_text())
    artifact=Path('reports/final_model_20261104/final_service_bundle.joblib')
    assert hashlib.sha256(artifact.read_bytes()).hexdigest()==m['sha256']
    collection=json.loads(Path('data/research/service_certification_20261104/raw_collection_status.json').read_text())
    assert collection['status']=='complete' and collection['completed']==collection['total']
    assert all(r.get('status')==200 for r in collection['results'])
    latest=p['latest']
    latest['korea_3y']=dict(status='frozen_value_not_certified',observation_date='2026-10-29',value=3.766,safe_previous_observation=e)
    cutoff='2026-10-30T15:30:00+09:00'
    assert available_asof([e],cutoff)==e
    assert available_asof([dict(e,known_by='2026-10-31T00:00:00+09:00')],cutoff) is None
    assert available_asof([dict(e,verified=False)],cutoff) is None
    rate=latest['us_treasury_10y']['safe_previous_observation']
    assert rate['observation_date']<'2026-10-29'
    r=dict(rate,verified=True,availability_basis='official_vintage_date_upper_bound')
    assert available_asof([r],cutoff)==r and r['available_at'] is None
    proof=dict(model_sha256=m['sha256'],gold_sha256=hashlib.sha256(Path('reports/support_expansion_20261104/research_input.parquet').read_bytes()).hexdigest(),
        model_basis_date='2026-10-30',latest_macro_evidence=latest,
        price_adjustment_validation_passed=c['price_adjustment_validation_passed'],
        official_krx_request_segments=collection['total'],price_assets=c['assets'],checked_return_pairs=sum(x['checked_return_pairs'] for x in c['summary']),
        price_mismatches=len(c['errors']),corporate_event_type_ledger_complete=False,
        price_scope=c['scope'],publication_precision=p['availability_precision'],publication_evidence_limit=p['evidence_limit'],
        historical_training_inputs_certified=False,production_approved=False,
        model_changed=False,gold_changed=False,training_performed=False)
    out=module/'service_evidence'
    for name,data in [('source_certification.json',proof),('publication_audit.json',p),('corporate_adjustment_audit.json',c),('macro_correction_plan.json',json.loads((root/'macro_correction_plan.json').read_text()))]:
        (out/name).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf8')
    from fastapi.testclient import TestClient
    from .api import app
    client=TestClient(app)
    response=client.get('/model-info')
    assert response.status_code==200
    data=response.json()['data_status']
    assert data['source_certification']['model_sha256']==m['sha256']
    assert not data['latest_market_state']
    assert data['source_certification']['price_adjustment_validation_passed']==c['price_adjustment_validation_passed']
    if c['price_adjustment_validation_passed']:
        assert data['corporate_action_status']=='official_reference_price_return_continuity_verified_50_stocks'
    previous=os.environ.get('STRESSLAB_REQUIRE_CERTIFIED_DATA')
    os.environ['STRESSLAB_REQUIRE_CERTIFIED_DATA']='1'
    try:
        request=dict(positions=[dict(asset_id=m['supported_assets'][0],value_krw=1000000)],shocks=dict(fx_pct=5))
        blocked=client.post('/analyze',json=request)
        assert blocked.status_code==503 and blocked.json()['detail']['code']=='data_certification_required'
    finally:
        if previous is None:os.environ.pop('STRESSLAB_REQUIRE_CERTIFIED_DATA',None)
        else:os.environ['STRESSLAB_REQUIRE_CERTIFIED_DATA']=previous
    example=json.loads((out/'example_request.json').read_text())
    response=client.post('/analyze',json=example)
    assert response.status_code==200 and response.json()['portfolio_analysis_class']=='exploratory'
    (out/'example_response.json').write_text(json.dumps(response.json(),ensure_ascii=False,indent=2),encoding='utf8')
    (root/'serving_guard_verification.json').write_text(json.dumps(dict(passed=True,certified_mode_blocks_unverified_model=True,future_excluded=True,unknown_excluded=True,date_precision_preserved=True,model_hash_unchanged=True),indent=2))
    (out/'serving_guard_verification.json').write_bytes((root/'serving_guard_verification.json').read_bytes())
    print(json.dumps(dict(price_passed=c['price_adjustment_validation_passed'],pairs=proof['checked_return_pairs'],serving_guards=True)))

if __name__=='__main__':main()
