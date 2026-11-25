import copy
import gzip
import hashlib
import json
from datetime import date,timedelta

import pytest
import conditional_history as H

ASSETS=['000270','000660','005380','005930','005935','006400','009150','012330','012450','028260',
        '032830','034020','034730','055550','068270','086790','105560','207940','373220','402340']


def dataset():
    rows=[]
    for aid in ASSETS:
        for h in (1,5,20):
            for i in range(30):
                start=date(2018,1,1)+timedelta(days=i*30)
                rows.append([aid,h,start.isoformat(),(start+timedelta(days=h)).isoformat(),float(i-15)]
                    +[float(i-15)]*4+[float(i)]*6)
    return dict(schema='conditional-history-v1',model_manifest_sha256='a'*64,
        model_package_id='pkg',dataset_version='gold',gold_sha256='b'*64,source_split='train',
        calibration_start='2024-01-01',columns=list(H.COLUMNS),assets=ASSETS,rows=rows,
        train_rows={str(h):{a:30 for a in ASSETS} for h in (1,5,20)})


def load(tmp_path,data):
    content=gzip.compress(json.dumps(data).encode(),mtime=0)
    path=tmp_path/'history.json.gz';path.write_bytes(content)
    H.load_history.cache_clear()
    return H.load_history(str(path),hashlib.sha256(content).hexdigest(),'a'*64)


def test_train_only_reproducible_search_and_no_forced_matches(tmp_path):
    data,groups=load(tmp_path,dataset())
    state=dict(model_package_id='pkg',dataset_version='gold',state_by_horizon={
        str(h):[dict(asset_id=a,**{k:15 for k in H.STATES}) for a in ASSETS] for h in (1,5,20)})
    shocks={k:0. for k in H.SHOCKS}
    result=H.search_history(data,groups,state,'005930',5,shocks,'c'*64)
    assert result['source_split']=='train'
    assert 1<=len(result['cases'])<=5
    assert result['cases'][0]['actual_return_pct']==0.
    assert result['cases'][0]['standardized_shock_distance']==0.
    assert result['distance_is_probability'] is False
    assert result==H.search_history(data,groups,state,'005930',5,shocks,'c'*64)
    for a in result['cases']:
        for b in result['cases']:
            if a is not b:assert not (a['start']<b['end'] and a['end']>b['start'])
    none=H.search_history(data,groups,state,'005930',5,{k:1e6 for k in H.SHOCKS},'c'*64)
    assert none['cases']==[] and none['unavailable_reason']


@pytest.mark.parametrize('change', ['future','duplicate','wrong_split','nan','missing_asset'])
def test_invalid_history_is_blocked(tmp_path,change):
    data=dataset()
    if change=='future':data['rows'][0][3]='2025-01-01'
    if change=='duplicate':data['rows'].append(copy.deepcopy(data['rows'][0]))
    if change=='wrong_split':data['source_split']='test'
    if change=='nan':data['rows'][0][5]=float('nan')
    if change=='missing_asset':data['rows']=[r for r in data['rows'] if r[0]!='000270']
    with pytest.raises(ValueError):load(tmp_path,data)


def test_tampered_bytes_are_blocked(tmp_path):
    path=tmp_path/'history.json.gz';path.write_bytes(b'wrong')
    H.load_history.cache_clear()
    with pytest.raises(ValueError,match='SHA'):H.load_history(str(path),'0'*64,'a'*64)
