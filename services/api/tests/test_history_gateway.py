import copy
from test_gateway import env,HEADERS
from test_conditional_gateway import RESULT

BODY=dict(asset_id='005930',horizon_days=5,snapshot_sha256=RESULT['snapshot_sha256'],scenarios=RESULT['scenarios'])


def test_history_auth_and_request_binding(env):
    client,upstream,*_=env
    selected=next(s for s in BODY['scenarios'] if s['horizon_days']==5)
    response=dict(schema='conditional-history-response-v1',asset_id='005930',horizon_days=5,
        snapshot_sha256=BODY['snapshot_sha256'],source_split='train',
        current_shocks={k:v for k,v in selected.items() if k.startswith('shock_')},cases=[])
    async def call(url,**kwargs):
        assert url.endswith('/scenario/history') and kwargs['ml'] is True
        return copy.deepcopy(response)
    upstream.call=call
    assert client.post('/api/stress/scenario/history',json=BODY).status_code==403
    assert client.post('/api/stress/scenario/history',json=BODY,headers=HEADERS).status_code==200
    response['snapshot_sha256']='f'*64
    assert client.post('/api/stress/scenario/history',json=BODY,headers=HEADERS).status_code==502


def test_history_request_rejects_duplicate_horizons(env):
    client,*_=env
    body=copy.deepcopy(BODY);body['scenarios']=[body['scenarios'][0]]*3
    assert client.post('/api/stress/scenario/history',json=body,headers=HEADERS).status_code==422
