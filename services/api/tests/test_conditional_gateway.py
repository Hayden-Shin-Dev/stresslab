import copy
import json
from pathlib import Path

import pytest
from fastapi import HTTPException
from test_gateway import env, HEADERS
from conditional_gateway import ConditionalRequest, validate_result

FIXTURE=Path(__file__).parent/'fixtures/conditional_result.json'
RESULT=json.loads(FIXTURE.read_text(encoding='utf-8-sig'))
BODY={'asset_ids':['005930'],'scenarios':RESULT['scenarios']}


def test_actual_result_and_contract_failures():
    validate_result(RESULT,'005930',BODY['scenarios'])
    for mutate in [
        lambda r:r.update(asset_id='000660'),
        lambda r:r['predictions'].pop(),
        lambda r:r['predictions'][0].update(predicted_close=float('nan')),
        lambda r:r['predictions'][0].update(lower_90_close=1e9),
        lambda r:r.update(scenarios=[]),
    ]:
        bad=copy.deepcopy(RESULT);mutate(bad)
        with pytest.raises(HTTPException):validate_result(bad,'005930',BODY['scenarios'])


def test_invalid_request():
    for bad in [dict(BODY,asset_ids=['005930','005930']),dict(BODY,asset_ids=['5930']),
                dict(BODY,scenarios=BODY['scenarios'][:2])]:
        with pytest.raises(ValueError):ConditionalRequest(**bad)


def test_auth_and_actual_response(env):
    client,upstream,*_=env
    original=upstream.call
    async def call(url,**kwargs):
        if url.endswith('/predict/scenario'):return copy.deepcopy(RESULT)
        if url.endswith('/scenario/metadata'):return {'supported_assets':['005930'],'horizons':[1,5,20]}
        return await original(url,**kwargs)
    upstream.call=call
    assert client.post('/api/stress/scenario',json=BODY).status_code==403
    assert client.post('/api/stress/scenario',json=BODY,headers={'x-stresslab-gateway-key':'test-secret'}).status_code==401
    response=client.post('/api/stress/scenario',json=BODY,headers=HEADERS)
    assert response.status_code==200,response.text
    assert response.json()['results'][0]['predictions']==RESULT['predictions']
    assert response.json()['ai_handoff']['ready'] is False
    assert client.get('/api/stress/scenario/support',headers=HEADERS).status_code==200


def test_mixed_snapshots_block_entire_response(env):
    client,upstream,*_=env
    async def call(url,**kwargs):
        r=copy.deepcopy(RESULT);aid=kwargs['payload']['asset_id'];r['asset_id']=aid
        for row in r['predictions']:row['asset_id']=aid
        if aid=='000660':r['snapshot_sha256']='changed'
        return r
    upstream.call=call
    response=client.post('/api/stress/scenario',json=dict(BODY,asset_ids=['005930','000660']),headers=HEADERS)
    assert response.status_code==409,response.text
