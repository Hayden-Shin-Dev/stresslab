import base64
import json
import math
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'services/api/src'))
sys.path.insert(0, str(ROOT / 'services/debate/tests'))
import gateway
from test_api import FakeQueue, FakeReader, FakeTokens
from api import Deps

PRINCIPAL = base64.b64encode(json.dumps({'identityProvider':'aad','userId':'gateway-test',
    'userRoles':['authenticated'],'userDetails':'integration-test'}).encode()).decode()
HEADERS = {'x-stresslab-gateway-key':'test-secret','x-ms-client-principal':PRINCIPAL}
BODY = {'positions':[{'asset_id':'005930','value_krw':1000000}], 'shocks':{'fx_pct':5,'us_rate_bp':100}}

class FakeUpstream:
    def __init__(self): self.calls=[]; self.drift=False
    async def close(self): pass
    async def call(self,url,*,payload=None,ml=False):
        self.calls.append((url,payload,ml))
        if url.endswith('/snapshot/metadata'):
            return {'dataset_version':'g1','as_of_trading_date':'2026-11-09','sha256':'snapshot-1',
                    'historical_availability_verified':False,'real_time':False}
        if url.endswith('/metadata'): return {'supported_assets':['005930','005380'],'package_id':'v1'}
        changed=any(payload[k] for k in payload if k.startswith('shock_'))
        return {'asset_id':payload['asset_id'],'model':payload['model'],
                'point_log_return_5d_pct':-10 if changed else 1,
                'lower_90_log_return_5d_pct':-20,'upper_90_log_return_5d_pct':3,
                'package_id':'v1','dataset_version':'g1',
                'feature_as_of_trading_date':'2026-11-09' if changed or not self.drift else '2026-11-10'}

@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv('ML_API_URL','https://ml.example')
    monkeypatch.delenv('MARKET_STATE_URL',raising=False)
    q,r,u=FakeQueue(),FakeReader(),FakeUpstream()
    app=gateway.create_app(Deps(q,r,FakeTokens()),u,'test-secret')
    with TestClient(app) as client: yield client,u,q,r

def test_forged_identity_and_direct_bypass_rejected(env):
    c,*_=env
    assert c.get('/healthz').status_code==200
    assert c.post('/api/stress/analyze',json=BODY,headers={'x-ms-client-principal':PRINCIPAL}).status_code==403
    assert c.get('/api/me',headers={'x-stresslab-gateway-key':'test-secret'}).status_code==401

def test_log_conversion_and_unchanged_shocks(env):
    c,u,*_=env
    res=c.post('/api/stress/analyze',json=BODY,headers=HEADERS)
    assert res.status_code==200,res.text
    j=res.json();a=j['assets'][0]
    assert a['hypothetical_pnl_krw']==pytest.approx(1e6*math.expm1(-.1))
    assert a['baseline_pnl_krw']+a['shock_incremental_pnl_krw']==pytest.approx(a['hypothetical_pnl_krw'])
    assert j['model']=='catboost'
    prediction=next(payload for _,payload,_ in u.calls if payload)
    assert prediction['shock_wti_pct']==0 and prediction['shock_vix_points']==0
    assert a['shock_contributions_pp'] is None

def test_portfolio_aggregates_asset_pnl_not_intervals(env):
    c,*_=env
    body={**BODY,'positions':BODY['positions']+[{'asset_id':'005380','value_krw':2000000}]}
    j=c.post('/api/stress/analyze',json=body,headers=HEADERS).json()
    assert j['portfolio_hypothetical_pnl_krw']==pytest.approx(3e6*math.expm1(-.1))
    assert 'portfolio_interval' not in j

def test_input_errors(env):
    c,u,*_=env
    for body in [dict(BODY,positions=[{'asset_id':'373220','value_krw':1}]),
                 dict(BODY,positions=BODY['positions']*2),dict(BODY,model='arbitrary')]:
        assert c.post('/api/stress/analyze',json=body,headers=HEADERS).status_code==422

def test_snapshot_drift_blocks_mixed_result(env):
    c,u,*_=env;u.drift=True
    assert c.post('/api/stress/analyze',json=BODY,headers=HEADERS).status_code==409

def test_original_holdings_and_queue_preserved(env):
    c,u,q,r=env
    h=c.put('/api/me/holdings',headers=HEADERS,json={'holdings':[{'asset_id':'005930','amount_krw':1000000}]})
    assert h.status_code==200,h.text
    assert c.get('/api/me/holdings',headers=HEADERS).json()['total_krw']==1000000
    res=c.post('/api/debates',headers=HEADERS,json={})
    assert res.status_code==202,res.text
    assert q.sent[0][2]['user_id']=='aad:gateway-test'
    assert c.post('/api/scheduled-debates',headers=HEADERS,json={'slot':'0830'}).status_code==403

def test_bad_model_output_is_not_financial_result():
    for v in [float('nan'),float('inf'),1001]:
        with pytest.raises(gateway.HTTPException):gateway.simple_return(v)

def test_malformed_principal_rejected(env):
    c,*_=env
    headers={**HEADERS,'x-ms-client-principal':base64.b64encode(b'[]').decode()}
    assert c.get('/api/me',headers=headers).status_code==401

def test_private_results_not_cached(env):
    c,*_=env
    assert c.get('/api/me',headers=HEADERS).headers['cache-control']=='no-store'

def test_missing_version_not_accepted(env):
    c,u,*_=env
    original=u.call
    async def missing(*a,**kw):
        j=await original(*a,**kw)
        if 'package_id' in j:del j['package_id']
        return j
    u.call=missing
    assert c.post('/api/stress/analyze',json=BODY,headers=HEADERS).status_code==502
