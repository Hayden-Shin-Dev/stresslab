"""Native pure-CatBoost 1/5/20-day conditional inference; no Huber or news AI."""
from pathlib import Path
from functools import lru_cache
import hashlib,json,math
import numpy as np
import pandas as pd
from catboost import CatBoostRegressor

MODEL='catboost_multi_horizon_conditional'
HORIZONS=(1,5,20)
SHOCKS=['shock_usdkrw_pct','shock_us10y_bp','shock_wti_pct','shock_vix_pt']
STATES=['kospi_vol20','kospi_trend20','vix_level','us10y_level','usdkrw_trend20','wti_level']

@lru_cache(maxsize=2)
def load_package(root,expected_sha):
    root=Path(root);content=(root/'manifest.json').read_bytes()
    if hashlib.sha256(content).hexdigest()!=expected_sha:raise ValueError('CatBoost manifest SHA mismatch')
    m=json.loads(content)
    if (m['model']!=MODEL or m['horizons']!=list(HORIZONS) or m['features']!=SHOCKS+STATES
        or m['research_only'] is not True or m['production_approval']!='NOT_APPROVED'
        or m['historical_availability_verified'] is not False):raise ValueError('CatBoost package contract mismatch')
    for name,sha in m['files'].items():
        if Path(name).name!=name or hashlib.sha256((root/name).read_bytes()).hexdigest()!=sha:raise ValueError('CatBoost artifact SHA mismatch')
    models={}
    for h in HORIZONS:
        for aid in m['assets']:
            for q in (10,50,90):
                model=CatBoostRegressor();model.load_model(str(root/f'catboost_{aid}_{h}d_q{q}.cbm'))
                if model.feature_names_!=m['features']:raise ValueError('CatBoost feature order mismatch')
                models[h,aid,q]=model
    calibration=json.loads((root/'calibration.json').read_text())
    return root,m,models,calibration

def validate_state(state,manifest):
    if (state['snapshot_version']!=manifest['snapshot_contract'] or state['research_only'] is not True
        or state['historical_availability_verified'] is not False
        or state['dataset_version'] not in manifest['allowed_snapshot_datasets']):raise ValueError('State contract mismatch')
    # The snapshot is a feature source, not this model's artifact. Both identities
    # are exposed separately; do not relabel a hybrid package as CatBoost.
    for h in HORIZONS:
        rows=state['state_by_horizon'][str(h)]
        if len(rows)!=20 or {r['asset_id'] for r in rows}!=set(manifest['assets']):raise ValueError('All 20 state assets required')
        for r in rows:
            if r.get('horizon')!=h or any(isinstance(r.get(k),bool) or not isinstance(r.get(k),(int,float)) or not math.isfinite(r[k]) for k in ['base_close']+STATES):raise ValueError('Invalid state feature')
            if r['base_close']<=0:raise ValueError('Invalid base close')

def predict(package,state,asset_id,horizon,shocks):
    root,m,models,calibration=package
    validate_state(state,m)
    if horizon not in HORIZONS or asset_id not in m['assets']:raise KeyError('Unsupported asset/horizon')
    if set(shocks)!=set(SHOCKS) or any(isinstance(v,bool) or not isinstance(v,(float,int)) or not math.isfinite(v) for v in shocks.values()):raise ValueError('Four finite shock assumptions required')
    if shocks['shock_usdkrw_pct']<=-100 or shocks['shock_wti_pct']<=-100:raise ValueError('Percentage shock must exceed -100')
    r=next(r for r in state['state_by_horizon'][str(horizon)] if r['asset_id']==asset_id)
    frame=pd.DataFrame([{**{k:r[k] for k in STATES},**shocks}],columns=m['features'])
    p={q:float(models[horizon,asset_id,q].predict(frame,thread_count=2)[0]) for q in (10,50,90)}
    center=p[50];low=min(p.values());high=max(p.values());close=float(r['base_close'])
    result={'asset_id':asset_id,'horizon_days':horizon,'base_close':close,'point_log_return_pct':center,
        'point_simple_return_pct':100*math.expm1(center/100),'predicted_close':close*math.exp(center/100)}
    for tag in (80,90):
        correction=calibration[str(horizon)][asset_id]['offsets_log_pp'][str(tag)]
        for side,value in [('lower',low-correction),('upper',high+correction)]:
            result[f'{side}_{tag}_log_return_pct']=value
            result[f'{side}_{tag}_close']=close*math.exp(value/100)
    if any(not math.isfinite(v) for v in result.values() if not isinstance(v,str)):raise ValueError('Nonfinite CatBoost output')
    return result

@lru_cache(maxsize=4)
def history_rows(root,asset_id,horizon):
    # This file contains only Train examples; never search calibration/Test.
    path=Path(root)/f'history_{asset_id}_{horizon}d.json'
    if path.exists():return json.loads(path.read_text())
    return [r for r in json.loads((Path(root)/'history.json').read_text()) if r['asset_id']==asset_id and r['horizon_days']==horizon]

def historical_cases(package,asset_id,horizon,shocks):
    root,m,*_=package
    if asset_id not in m['assets'] or horizon not in HORIZONS:raise KeyError('Unsupported asset/horizon')
    rows=history_rows(str(root),asset_id,horizon)
    x=np.array([[r['actual_shocks'][k] for k in SHOCKS] for r in rows],dtype=float)
    scale=np.maximum(np.std(x,axis=0),1e-6);query=np.array([shocks[k] for k in SHOCKS])
    distances=np.sqrt(np.mean(((x-query)/scale)**2,axis=1));ordered=np.argsort(distances)
    chosen=[]
    for i in ordered:
        row=rows[int(i)]
        if row['end']>='2024-01-01':raise ValueError('Non-Train history detected')
        if any(not(row['end']<a['start'] or row['start']>a['end']) for a in chosen):continue
        chosen.append({**row,'distance':float(distances[i])})
        if len(chosen)==5:break
    return chosen
