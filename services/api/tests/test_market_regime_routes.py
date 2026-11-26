import base64
import hashlib
import json
import sys
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'services/api/src'))
sys.path.insert(0, str(ROOT / 'services/debate/tests'))
import gateway
import market_regime_routes as mr
from test_api import FakeQueue, FakeReader, FakeTokens
from api import Deps

PRINCIPAL = base64.b64encode(json.dumps({'identityProvider': 'aad', 'userId': 'regime-test',
    'userRoles': ['authenticated'], 'userDetails': 'integration-test'}).encode()).decode()
HEADERS = {'x-stresslab-gateway-key': 'test-secret', 'x-ms-client-principal': PRINCIPAL}
SNAP = '/api/v1/market-regime/snapshot'
HEALTH = '/api/v1/market-regime/health'


def payload_text(**over):
    doc = {'schema': 'market_regime_snapshot', 'schema_version': 1, 'data_mode': 'fabric_gold',
           'as_of': '2026-11-23', 'current': {'regime_code': 'bull', 'regime_name': '상승장'}, **over}
    return json.dumps(doc, ensure_ascii=False, separators=(',', ':'))


def row(text=None, *, version='20261124T120702Z', as_of=date(2026, 11, 23), sha=None, data_mode='fabric_gold'):
    text = payload_text() if text is None else text
    return {'snapshot_version': version, 'as_of': as_of, 'data_mode': data_mode, 'payload_text': text,
            'payload_sha256': sha or hashlib.sha256(text.encode('utf-8')).hexdigest()}


class FakeStore:
    """PostgresStore._one 대역. result가 예외면 던지고, 아니면 그대로 돌려줍니다."""
    def __init__(self, result=None):
        self.result, self.calls = result, []

    async def _one(self, sql, args=()):
        self.calls.append((sql, args))
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


class Clock:
    def __init__(self): self.t = 1000.0
    def monotonic(self): return self.t


class NoUpstream:
    async def close(self): pass


@pytest.fixture
def client(monkeypatch):
    clock = Clock()
    monkeypatch.setattr(mr, 'time', clock)
    store, reader = FakeStore(row()), FakeReader()
    reader.store = store
    app = gateway.create_app(Deps(FakeQueue(), reader, FakeTokens()), NoUpstream(), 'test-secret')
    with TestClient(app) as c:
        yield c, store, clock


def test_snapshot_returns_stored_payload_bytes_and_health_ok(client):
    c, store, _ = client
    r = c.get(SNAP, headers=HEADERS)
    assert r.status_code == 200, r.text
    assert r.headers['content-type'].startswith('application/json')
    assert r.content == payload_text().encode('utf-8')
    assert hashlib.sha256(r.content).hexdigest() == row()['payload_sha256']
    h = c.get(HEALTH, headers=HEADERS)
    assert h.status_code == 200
    assert h.json() == {'status': 'ok', 'as_of': '2026-11-23', 'snapshot_version': '20261124T120702Z'}
    sql = store.calls[0][0]
    assert "data_mode = 'fabric_gold'" in sql and 'ORDER BY as_of DESC, created_at DESC LIMIT 1' in sql


def test_routes_require_gateway_key_and_login(client):
    c, store, _ = client
    assert c.get(SNAP, headers={'x-ms-client-principal': PRINCIPAL}).status_code == 403
    assert c.get(HEALTH, headers={'x-stresslab-gateway-key': 'test-secret'}).status_code == 401
    assert store.calls == []


@pytest.mark.parametrize('bad_row', [
    row(sha='0' * 64),                                            # sha256 불일치
    row(payload_text(schema='other_snapshot')),                   # schema 다름
    row(payload_text(schema_version=2)),                          # schema_version 다름
    row(payload_text(schema_version=True)),                       # bool은 1로 보지 않음
    row(payload_text(data_mode='synthetic_fixture')),             # 합성 데이터
    row(data_mode='synthetic_fixture'),                           # 행의 data_mode가 합성
    row('not json'),                                              # JSON 아님
    None,                                                         # 행 없음
], ids=['sha', 'schema', 'version', 'bool-version', 'synthetic-payload', 'synthetic-row', 'not-json', 'no-row'])
def test_rejected_rows_give_503_without_cache(client, bad_row):
    c, store, _ = client
    store.result = bad_row
    r = c.get(SNAP, headers=HEADERS)
    assert r.status_code == 503
    assert r.json()['detail'] == {'code': 'market_regime_unavailable'}
    assert c.get(HEALTH, headers=HEADERS).json() == {'status': 'unavailable', 'as_of': None, 'snapshot_version': None}


def test_db_error_without_cache_is_503_and_hides_detail(client):
    c, store, _ = client
    store.result = RuntimeError('password=secret host=db')
    r = c.get(SNAP, headers=HEADERS)
    assert r.status_code == 503
    assert 'secret' not in r.text


def test_missing_store_is_503(client):
    c, store, _ = client
    del c.app.state.deps.reader.store
    assert c.get(SNAP, headers=HEADERS).status_code == 503
    assert c.get(HEALTH, headers=HEADERS).json()['status'] == 'unavailable'


def test_cache_five_minutes_then_refresh(client):
    c, store, clock = client
    assert c.get(SNAP, headers=HEADERS).status_code == 200
    clock.t += 299
    assert c.get(HEALTH, headers=HEADERS).json()['status'] == 'ok'
    assert len(store.calls) == 1
    newer = payload_text(as_of='2026-11-24')
    store.result = row(newer, version='20261125T120000Z', as_of=date(2026, 11, 24))
    clock.t += 2
    assert c.get(SNAP, headers=HEADERS).content == newer.encode('utf-8')
    assert len(store.calls) == 2
    assert c.get(HEALTH, headers=HEADERS).json()['snapshot_version'] == '20261125T120000Z'


@pytest.mark.parametrize('failure', [RuntimeError('db down'), TimeoutError(), row(sha='0' * 64)],
                         ids=['db-error', 'timeout', 'invalid-row'])
def test_failure_after_success_serves_last_good(client, failure):
    c, store, clock = client
    good = c.get(SNAP, headers=HEADERS).content
    store.result = failure
    clock.t += 301
    r = c.get(SNAP, headers=HEADERS)
    assert r.status_code == 200 and r.content == good
    assert len(store.calls) == 2
    assert c.get(HEALTH, headers=HEADERS).json()['status'] == 'ok'
    assert len(store.calls) == 2          # 실패 직후 5분 동안은 다시 조회하지 않음
