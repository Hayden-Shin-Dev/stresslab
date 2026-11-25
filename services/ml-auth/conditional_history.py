"""Observed TRAIN examples; never used to fit or adjust a service prediction."""
from datetime import date
from functools import lru_cache
from pathlib import Path
import gzip
import hashlib
import json
import math
from threading import RLock

import numpy as np

SHOCKS=('shock_usdkrw_pct','shock_us10y_bp','shock_wti_pct','shock_vix_pt')
STATES=('kospi_vol20','kospi_trend20','vix_level','us10y_level','usdkrw_trend20','wti_level')
COLUMNS=('asset_id','horizon_days','start','end','actual_return_pct')+SHOCKS+STATES


_LOAD_LOCK=RLock()


@lru_cache(maxsize=1)
def _load_history(path, expected_sha, expected_manifest_sha):
    content=Path(path).read_bytes()
    if hashlib.sha256(content).hexdigest()!=expected_sha:
        raise ValueError('History SHA mismatch')
    data=json.loads(gzip.decompress(content))
    if (data.get('schema')!='conditional-history-v1'
        or data.get('model_manifest_sha256')!=expected_manifest_sha
        or data.get('source_split')!='train'
        or data.get('columns')!=list(COLUMNS)):
        raise ValueError('History contract mismatch')
    groups={}
    seen=set()
    cutoff=date.fromisoformat(data['calibration_start'])
    for values in data.pop('rows'):
        if not isinstance(values,list) or len(values)!=len(COLUMNS):
            raise ValueError('Invalid history row')
        r=dict(zip(COLUMNS,values));key=(r['asset_id'],r['horizon_days'])
        if (r['asset_id'] not in data['assets'] or type(r['horizon_days']) is not int
            or r['horizon_days'] not in (1,5,20)):
            raise ValueError('Invalid asset/horizon')
        start,end=date.fromisoformat(r['start']),date.fromisoformat(r['end'])
        if not start<end<cutoff:
            raise ValueError('Only matured Train observations are allowed')
        unique=key+(r['start'],)
        if unique in seen:raise ValueError('Duplicate history key')
        seen.add(unique)
        for k in ('actual_return_pct',)+SHOCKS+STATES:
            if isinstance(r[k],bool) or not isinstance(r[k],(int,float)) or not math.isfinite(r[k]):
                raise ValueError('Nonfinite history value')
        if r['actual_return_pct']<=-100:raise ValueError('Invalid actual return')
        groups.setdefault(key,[]).append(r)
    expected={(aid,h) for aid in data['assets'] for h in (1,5,20)}
    if len(data['assets'])!=20 or len(set(data['assets']))!=20 or set(groups)!=expected:
        raise ValueError('History must cover 20 assets and 3 horizons')
    for (aid,h),rows in list(groups.items()):
        rows.sort(key=lambda r:r['start'])
        if len(rows)!=data['train_rows'][str(h)][aid]:raise ValueError('History row count mismatch')
        groups[(aid,h)]=dict(start=tuple(r['start'] for r in rows),end=tuple(r['end'] for r in rows),
            actual=np.array([r['actual_return_pct'] for r in rows],dtype=float),
            shocks=np.array([[r[k] for k in SHOCKS] for r in rows],dtype=float),
            states=np.array([[r[k] for k in STATES] for r in rows],dtype=float))
    return data,groups


def load_history(path,expected_sha,expected_manifest_sha):
    # Avoid concurrently parsing the same artifact on the first batch request.
    with _LOAD_LOCK:
        return _load_history(path,expected_sha,expected_manifest_sha)


load_history.cache_clear=_load_history.cache_clear


def search_history(data, groups, state, asset_id, horizon, scenario, snapshot_sha):
    if data['model_package_id']!=state['model_package_id'] or data['dataset_version']!=state['dataset_version']:
        raise ValueError('History/model/state package mismatch')
    group=groups[(asset_id,horizon)]
    count=len(group['start'])
    current=next(r for r in state['state_by_horizon'][str(horizon)] if r['asset_id']==asset_id)
    state_values=group['states']
    state_scale=np.maximum(state_values.std(axis=0),1e-12)
    state_query=np.array([current[k] for k in STATES],dtype=float)
    state_distance=np.sqrt(np.mean(((state_values-state_query)/state_scale)**2,axis=1))
    pool=np.argsort(state_distance,kind='stable')[:min(100,count)]
    shocks=group['shocks']
    scale=np.maximum(shocks.std(axis=0),1e-12)
    query=np.array([scenario[k] for k in SHOCKS],dtype=float)
    distances=np.sqrt(np.mean(((shocks[pool]-query)/scale)**2,axis=1))
    if not np.isfinite(state_distance).all() or not np.isfinite(distances).all():
        raise ValueError('Invalid search inputs')
    ranked=sorted(zip(pool.tolist(),distances.tolist()),key=lambda p:(p[1],group['start'][p[0]]))
    cases=[]
    for index,distance in ranked:
        if distance>1.0:continue
        start,end=group['start'][index],group['end'][index]
        if any(start<other['end'] and end>other['start'] for other in cases):continue
        cases.append(dict(start=start,end=end,actual_return_pct=float(group['actual'][index]),
            actual_shocks={k:float(shocks[index,i]) for i,k in enumerate(SHOCKS)},
            standardized_shock_distance=distance,
            standardized_state_distance=float(state_distance[index])))
        if len(cases)==5:break
    return dict(schema='conditional-history-response-v1',asset_id=asset_id,horizon_days=horizon,
        snapshot_sha256=snapshot_sha,model_package_id=state['model_package_id'],
        dataset_version=state['dataset_version'],source_split='train',
        source_gold_sha256=data['gold_sha256'],source_train_rows=count,
        current_shocks={k:scenario[k] for k in SHOCKS},
        method='Train-only: 6-state standardized RMS nearest 100; 4-shock standardized RMS <= 1; nearest 5 non-overlapping periods',
        distance_is_probability=False,cases=cases,
        unavailable_reason=None if cases else '현재 조건과 충분히 가까운 학습 구간 후보가 없습니다.',
        note='과거 실제 관측이며 현재 모델의 예측 성능이나 동일 충격의 결과를 뜻하지 않습니다. 코스피 가정은 이 4충격 거리의 검색 조건에 포함하지 않습니다.')
