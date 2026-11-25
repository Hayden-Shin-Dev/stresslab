"""Conditional Huber+CatBoost inference, matching the selected research model.

The historical evaluation used realized future market moves. Service requests
must supply assumed moves, separately for each 1/5/20-trading-day horizon.
"""
from pathlib import Path
import hashlib
import json
import math
import importlib.metadata
import numpy as np
import pandas as pd
import joblib

HORIZONS=(1,5,20)
SHOCKS=['shock_usdkrw_pct','shock_us10y_bp','shock_wti_pct','shock_vix_pt']
STATES=['kospi_vol20','kospi_trend20','vix_level','us10y_level','usdkrw_trend20','wti_level']
STATE_FIELDS=STATES+['scale_kospi','asset_scale','beta_shr','beta_dn_f','beta_up_f',
                    'idio_f','asset_vol20','asset_vol60']
MODEL='huber_catboost_hybrid_conditional'

def design(frame):
    ks=np.maximum(frame.scale_kospi.to_numpy(float),.05)
    scale=np.maximum(frame.asset_scale.to_numpy(float),.05)
    base=np.column_stack([frame[c].to_numpy(float)/ks if c in SHOCKS else frame[c].to_numpy(float)
                          for c in SHOCKS+STATES])
    # Preserve the exact order of barc.feat() and the selected hybrid design().
    extra=np.column_stack([frame.m/ks,frame.m/scale,np.abs(frame.m)/ks,frame.beta_shr,
                           frame.beta_dn_f-frame.beta_up_f,frame.idio_f/scale*np.sqrt(frame.horizon),
                           frame.asset_vol20/frame.asset_vol60.replace(0,np.nan).fillna(1.)])
    interactions=(base[:,:4,None]*base[:,None,4:]).reshape(len(frame),-1)
    result=np.column_stack([base,extra,interactions])
    if result.shape[1]!=41 or not np.isfinite(result).all():
        raise ValueError('Conditional model requires 41 finite design features')
    return result

def predict(model,frame):
    x=design(frame);scale=np.maximum(frame.asset_scale.to_numpy(float),.05)
    huber=model['huber'].predict(x)*scale
    residual=model['catboost'].predict(x,prediction_type='RawFormulaVal')
    center=huber+residual[:,0]*scale;sigma=np.exp(residual[:,1])*scale
    result=pd.DataFrame(dict(center=center,center_huber=huber,
                            catboost_correction=residual[:,0]*scale,sigma=sigma),index=frame.index)
    for level,(below,above) in model['bands'].items():
        tag=int(round(level*100));result[f'lo_{tag}']=center-below*sigma;result[f'hi_{tag}']=center+above*sigma
    if not np.isfinite(result.to_numpy()).all() or (sigma<=0).any():
        raise ValueError('Invalid conditional output')
    return result

def scenario_frame(state,scenario):
    expected={'horizon_days','kospi_pct',*SHOCKS}
    if set(scenario)!=expected:
        raise ValueError('Each horizon requires KOSPI and all four macro assumptions')
    for k,v in scenario.items():
        if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v):
            raise ValueError('Scenario must contain finite numbers')
    if scenario['horizon_days'] not in HORIZONS:
        raise ValueError('Unsupported horizon')
    for k in ('kospi_pct','shock_usdkrw_pct','shock_wti_pct'):
        if scenario[k]<=-100:raise ValueError(k+' must be greater than -100 percent')
    result=pd.DataFrame(state).copy()
    if not result.horizon.eq(scenario['horizon_days']).all():raise ValueError('State horizon mismatch')
    for c in SHOCKS:result[c]=float(scenario[c])
    result['m']=100*np.log1p(scenario['kospi_pct']/100)
    return result

def scenario_outputs(models,snapshot,scenarios,asset_id=None):
    if len(scenarios)!=3 or {s['horizon_days'] for s in scenarios}!={1,5,20}:
        raise ValueError('Supply one scenario for each of 1,5,20 trading days')
    records=[]
    for scenario in sorted(scenarios,key=lambda s:s['horizon_days']):
        h=scenario['horizon_days'];state=snapshot['state_by_horizon'][str(h)]
        if asset_id is not None:state=[r for r in state if r['asset_id']==asset_id]
        if not state:raise ValueError('Unsupported asset')
        frame=scenario_frame(state,scenario)
        z=predict(models[h],frame)
        for i,row in frame.iterrows():
            p=z.loc[i];close=float(row.base_close)
            record=dict(asset_id=row.asset_id,horizon_days=h,base_close=close,
                        point_log_return_pct=float(p.center),point_simple_return_pct=float(100*np.expm1(p.center/100)),
                        predicted_close=float(close*np.exp(p.center/100)))
            for tag in (80,90):
                for side,short in [('lower','lo'),('upper','hi')]:
                    value=float(p[f'{short}_{tag}'])
                    record[f'{side}_{tag}_log_return_pct']=value
                    record[f'{side}_{tag}_close']=float(close*np.exp(value/100))
            if not all(isinstance(v,str) or np.isfinite(v) for v in record.values()):raise ValueError('Nonfinite price output')
            records.append(record)
    return records

def load_models(root,expected_manifest_sha256):
    root=Path(root);content=(root/'manifest.json').read_bytes()
    if hashlib.sha256(content).hexdigest()!=expected_manifest_sha256:raise ValueError('Manifest SHA mismatch')
    manifest=json.loads(content)
    if (manifest.get('model')!=MODEL or manifest.get('future_market_or_macro_input') is not True
        or manifest.get('research_only') is not True or manifest.get('production_approval')!='NOT_APPROVED'):
        raise ValueError('Conditional package contract mismatch')
    for name in ('numpy','pandas','scikit-learn','catboost','joblib'):
        if importlib.metadata.version(name)!=manifest['versions'][name]:
            raise ValueError('Model/API library versions differ: '+name)
    models={}
    for h in HORIZONS:
        name=f'model_{h}d.joblib'
        if hashlib.sha256((root/name).read_bytes()).hexdigest()!=manifest['files'][name]:raise ValueError('Model SHA mismatch')
        models[h]=joblib.load(root/name)  # trusted project package only
        if models[h]['horizon']!=h or sorted(models[h]['assets'])!=manifest['assets']:raise ValueError('Model horizon/assets mismatch')
    return models,manifest
