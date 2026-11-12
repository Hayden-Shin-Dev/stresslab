"""2026-11-12 민철 추가: 실제 AI 근거 생성기와 공통 API 응답의 수치 정합성 검사."""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'debate/src'))
import evidence
from test_gateway import env, BODY, HEADERS


def test_evidence_uses_same_result_and_never_renames_90_to_80(env):
    client, *_ = env
    result = client.post('/api/stress/analyze', json=BODY, headers=HEADERS).json()
    context = result['ai_context']
    bundle = evidence.build_bundle('integration-test', context['stress_run'], context['market_snapshot'])
    values = {d['metric_id']: d['value'] for d in bundle['D_sources']}
    assert values['scenario_shock_usdkrw'] == 5
    assert values['scenario_shock_us10y'] == 100
    assert values['conditional_center_return'] == pytest.approx(result['assets'][0]['scenario_return_pct'])
    assert values['center_pnl'] == pytest.approx(result['assets'][0]['hypothetical_pnl_krw'])
    assert values['portfolio_center_pnl_krw'] == round(result['portfolio_hypothetical_pnl_krw'])
    assert values.get('model_q10_return') is None and values.get('model_q90_return') is None
    assert not any(k.startswith('model_contribution_') for k in values)
    assert result['ai_handoff']['ready'] is False and result['ai_handoff']['persisted'] is False
    assert result['model_context']['historical_availability_verified'] is False


def test_unpersisted_analysis_is_not_silently_sent_to_demo_worker(env):
    client, _, queue, _ = env
    response=client.post('/api/debates',json={'run_id':'a-unpersisted'},headers=HEADERS)
    assert response.status_code==409
    assert response.json()['detail']['code']=='analysis_handoff_not_connected'
    assert queue.sent==[]


def test_intraday_snapshot_is_attached_not_injected_into_ml(env, monkeypatch):
    client, upstream, *_ = env
    monkeypatch.setenv('MARKET_STATE_URL', 'https://market.example/market-state')
    original = upstream.call
    async def with_market(url, **kwargs):
        if url.endswith('/current'):
            return {'snapshot': {'snapshot_id':'m1', 'as_of':datetime.now(timezone.utc).isoformat(),
                                 'quality_status':'unverified', 'market':{}}}
        return await original(url, **kwargs)
    upstream.call = with_market
    result = client.post('/api/stress/analyze', json=BODY, headers=HEADERS).json()
    assert result['market_context']['freshness'] == 'recent'
    assert result['market_context']['snapshot']['quality_status'] == 'unverified'
    assert result['market_context']['applied_to_daily_ml'] is False
    assert result['ai_context']['market_snapshot']['snapshot_id'] == 'm1'
    assert all('market' not in str(payload) for _,payload,_ in upstream.calls if payload)


def test_market_failure_does_not_fabricate_snapshot_or_lose_ml(env, monkeypatch):
    from fastapi import HTTPException
    client, upstream, *_ = env
    monkeypatch.setenv('MARKET_STATE_URL','https://market.example/market-state')
    original = upstream.call
    async def failing(url, **kwargs):
        if url.endswith('/current'): raise HTTPException(503, 'unavailable')
        return await original(url, **kwargs)
    upstream.call = failing
    response = client.post('/api/stress/analyze', json=BODY, headers=HEADERS)
    assert response.status_code == 200
    assert response.json()['market_context']['snapshot'] is None
    assert response.json()['market_context']['error'] == 'market_state_unavailable'


def test_same_date_snapshot_replacement_blocks_result(env):
    client, upstream, *_ = env
    original = upstream.call
    calls = 0
    async def changing(url, **kwargs):
        nonlocal calls
        result = await original(url, **kwargs)
        if url.endswith('/snapshot/metadata'):
            calls += 1
            if calls == 2: result['sha256'] = 'replacement'
        return result
    upstream.call = changing
    assert client.post('/api/stress/analyze',json=BODY,headers=HEADERS).status_code == 409


@pytest.mark.parametrize('seconds,expected',[(600,'stale'),(-30,'unverified')])
def test_snapshot_age_does_not_mislabel_old_or_future_values(env,monkeypatch,seconds,expected):
    client, upstream, *_ = env
    monkeypatch.setenv('MARKET_STATE_URL','https://market.example/market-state')
    original = upstream.call
    async def dated(url,**kwargs):
        if url.endswith('/current'):
            return {'snapshot':{'as_of':(datetime.now(timezone.utc)-timedelta(seconds=seconds)).isoformat()}}
        return await original(url,**kwargs)
    upstream.call = dated
    assert client.post('/api/stress/analyze',json=BODY,headers=HEADERS).json()['market_context']['freshness'] == expected
