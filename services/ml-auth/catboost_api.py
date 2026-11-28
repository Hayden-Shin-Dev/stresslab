"""Additive routes; reuse the validated atomic feature snapshot reader."""
import os
from fastapi import APIRouter,HTTPException
from pydantic import BaseModel,ConfigDict,Field
from typing import Literal
import catboost_inference as I

class PredictRequest(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    asset_id:str=Field(pattern=r'^[0-9]{6}$')
    horizon_days:Literal[1,5,20]
    shock_usdkrw_pct:float=Field(ge=-30,le=30)
    shock_us10y_bp:float=Field(ge=-300,le=300)
    shock_wti_pct:float=Field(ge=-80,le=80)
    shock_vix_pt:float=Field(ge=-80,le=80)

class HistoryRequest(PredictRequest):
    snapshot_sha256:str=Field(pattern=r'^[0-9a-f]{64}$')

def context():
    from conditional_api import read_state
    state,sha,age=read_state()
    package=I.load_package(os.environ['STRESSLAB_CATBOOST_PACKAGE_DIR'],os.environ['STRESSLAB_CATBOOST_MANIFEST_SHA256'])
    I.validate_state(state,package[1])
    return package,state,sha,age

def metadata():
    package,state,sha,age=context();m=package[1]
    return {'model':'catboost','engine_model':I.MODEL,'package_id':m['package_id'],
        'supported_assets':m['assets'],'supported_horizon_trading_days':[1,5,20],
        'horizons':[1,5,20],'price_basis':'adjusted','uses_adjusted_basis':True,
        'dataset_version':state['dataset_version'],'training_dataset_version':m['training_dataset_version'],
        'as_of_trading_date':state['as_of_trading_date'],'snapshot_sha256':sha,'age_calendar_days':age,
        'research_only':True,'production_approval':'NOT_APPROVED','historical_availability_verified':False,
        'scenario_inputs_are_assumptions':True,'feature_columns':m['features']}

def compute(req):
    package,state,sha,age=context();m=package[1]
    shocks={k:getattr(req,k) for k in I.SHOCKS}
    p=I.predict(package,state,req.asset_id,req.horizon_days,shocks)
    return {'model':'catboost','engine_model':I.MODEL,'asset_id':req.asset_id,'horizon_days':req.horizon_days,
        'model_package_id':m['package_id'],'manifest_sha256':os.environ['STRESSLAB_CATBOOST_MANIFEST_SHA256'],
        'snapshot_sha256':sha,'source_state_model_package_id':state['model_package_id'],
        'as_of_trading_date':state['as_of_trading_date'],'dataset_version':state['dataset_version'],
        'training_dataset_version':m['training_dataset_version'],'age_calendar_days':age,
        'price_basis':'adjusted','currency':'KRW','horizon_unit':'trading_days','research_only':True,
        'production_approval':'NOT_APPROVED','historical_availability_verified':False,
        'future_market_or_macro_input':True,'scenario_inputs_are_assumptions':True,
        'shocks':shocks,'prediction':p}

def make_router():
    router=APIRouter()
    @router.get('/catboost/metadata')
    def support():
        try:return metadata()
        except Exception:raise HTTPException(503,'CatBoost package/state validation failed') from None
    @router.post('/catboost/predict')
    def predict(req:PredictRequest):
        try:return compute(req)
        except KeyError:raise HTTPException(422,'Unsupported asset/horizon') from None
        except Exception:raise HTTPException(503,'CatBoost package/state validation failed') from None
    @router.post('/catboost/history')
    def history(req:HistoryRequest):
        try:
            package,state,sha,age=context()
            if req.snapshot_sha256!=sha:raise HTTPException(409,'Feature snapshot changed; rerun analysis')
            shocks={k:getattr(req,k) for k in I.SHOCKS}
            cases=I.historical_cases(package,req.asset_id,req.horizon_days,shocks)
            return {'schema':'catboost-history-response-v1','asset_id':req.asset_id,'horizon_days':req.horizon_days,
                'snapshot_sha256':sha,'model_package_id':package[1]['package_id'],'source_split':'train',
                'current_shocks':shocks,'cases':cases,'research_only':True,
                'note':'Closest standardized four-shock Train examples, not forecasts or causal evidence.'}
        except HTTPException:raise
        except KeyError:raise HTTPException(422,'Unsupported asset/horizon') from None
        except Exception:raise HTTPException(503,'CatBoost history unavailable') from None
    return router

def install_existing_routes(app):
    """Dispatch through existing signed paths, with no platform-auth exceptions."""
    import app as legacy
    old_metadata=next(r.endpoint for r in app.routes if getattr(r,'path',None)=='/metadata')
    old_predict=next(r.endpoint for r in app.routes if getattr(r,'path',None)=='/predict/auto')
    class DispatchRequest(legacy.AutoPredictRequest):
        horizon_days:Literal[1,5,20]|None=None
        operation:Literal['predict','catboost_history']='predict'
        snapshot_sha256:str|None=Field(None,pattern=r'^[0-9a-f]{64}$')
    router=APIRouter()
    @router.get('/metadata')
    def combined_metadata():
        value=dict(old_metadata())
        try:value['catboost_multihorizon']=metadata()
        except Exception:value['catboost_multihorizon']={'available':False,'supported_horizon_trading_days':[]}
        return value
    @router.post('/predict/auto')
    def dispatch(req:DispatchRequest):
        if req.horizon_days is None:
            if req.operation!='predict' or req.snapshot_sha256 is not None:raise HTTPException(422,'Supply a supported CatBoost horizon')
            return old_predict(legacy.AutoPredictRequest(**req.model_dump(exclude={'horizon_days','operation','snapshot_sha256'})))
        if req.model!='catboost':raise HTTPException(422,'Multi-horizon dispatch requires CatBoost')
        try:
            body=PredictRequest(asset_id=req.asset_id,horizon_days=req.horizon_days,
                shock_usdkrw_pct=req.shock_fx_pct,shock_us10y_bp=req.shock_us_rate_bp,
                shock_wti_pct=req.shock_wti_pct,shock_vix_pt=req.shock_vix_points)
        except ValueError:raise HTTPException(422,'Invalid CatBoost shock assumptions') from None
        try:
            if req.operation=='catboost_history':
                if not req.snapshot_sha256:raise HTTPException(422,'Pin history to an analysis snapshot')
                package,state,sha,age=context()
                if req.snapshot_sha256!=sha:raise HTTPException(409,'Feature snapshot changed; rerun analysis')
                shocks={k:getattr(body,k) for k in I.SHOCKS}
                return {'schema':'catboost-history-response-v1','asset_id':req.asset_id,'horizon_days':req.horizon_days,
                    'snapshot_sha256':sha,'model_package_id':package[1]['package_id'],'source_split':'train',
                    'current_shocks':shocks,'cases':I.historical_cases(package,req.asset_id,req.horizon_days,shocks),
                    'research_only':True}
            if req.snapshot_sha256 is not None:raise HTTPException(422,'Snapshot pin is for historical lookup only')
            return compute(body)
        except HTTPException:raise
        except KeyError:raise HTTPException(422,'Unsupported asset/horizon') from None
        except Exception:raise HTTPException(503,'CatBoost package/state validation failed') from None
    app.router.routes[:]=[r for r in app.router.routes if getattr(r,'path',None) not in ('/metadata','/predict/auto')]
    app.include_router(router)
    app.openapi_schema=None
