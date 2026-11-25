"""Additive scenario API. Existing NB_04 CatBoost endpoints stay unchanged."""
from pathlib import Path
from datetime import date,datetime,timezone
from functools import lru_cache
import hashlib,json,math,os

def read_state():
    backend=os.getenv('STRESSLAB_CONDITIONAL_BACKEND','postgres')
    if backend=='json':
        content=Path(os.environ['STRESSLAB_CONDITIONAL_STATE_PATH']).read_bytes()
        sha=hashlib.sha256(content).hexdigest()
        if sha!=os.environ['STRESSLAB_CONDITIONAL_STATE_SHA256']:raise ValueError('State SHA mismatch')
        state=json.loads(content)
    elif backend=='postgres':
        from postgres_store import PostgresSnapshotStore
        # Header and all 60 states are read in one statement/consistent snapshot.
        with PostgresSnapshotStore.connect() as conn:
            with conn.cursor() as cur:
                cur.execute('''SELECT h.snapshot_sha256,h.snapshot_version,h.dataset_version,h.as_of_trading_date,
                    h.model_package_id,h.model_zip_sha256,h.research_only,h.historical_availability_verified,
                    jsonb_agg(to_jsonb(s) ORDER BY s.horizon_days,s.asset_id) AS states
                    FROM public.research_conditional_snapshots_v4 h
                    JOIN public.research_conditional_states_v4 s USING(snapshot_sha256)
                    WHERE h.is_active GROUP BY h.snapshot_sha256''')
                state=cur.fetchone()
        if not state:raise ValueError('No active conditional snapshot')
        sha=state['snapshot_sha256'];states={str(h):[] for h in (1,5,20)}
        for row in state.pop('states'):
            row={k:v for k,v in row.items() if k!='snapshot_sha256'}
            h=row.pop('horizon_days');row['horizon']=h;states[str(h)].append(row)
        state['state_by_horizon']=states
        state['as_of_trading_date']=str(state['as_of_trading_date'])
    else:raise ValueError('Conditional backend must be json or postgres')
    if state['snapshot_version']!='conditional-v4' or state['research_only'] is not True or state['historical_availability_verified'] is not False:
        raise ValueError('State contract mismatch')
    age=(datetime.now(timezone.utc).date()-date.fromisoformat(state['as_of_trading_date'])).days
    maximum=int(os.getenv('STRESSLAB_CONDITIONAL_MAX_AGE_DAYS','30'))
    if not 0<=maximum<=365 or not 0<=age<=maximum:raise ValueError('State age exceeds limit')
    return state,sha,age

@lru_cache(maxsize=2)
def package(root,manifest_sha):
    # The adjacent module is copied from inference.py, never imported from arbitrary ZIP code.
    import conditional_inference as I
    return I.load_models(root,manifest_sha)

def compute(asset_id,scenarios):
    import conditional_inference as I
    state,sha,age=read_state()
    models,manifest=package(os.environ['STRESSLAB_CONDITIONAL_PACKAGE_DIR'],os.environ['STRESSLAB_CONDITIONAL_MANIFEST_SHA256'])
    if state['model_zip_sha256']!=os.environ['STRESSLAB_CONDITIONAL_PACKAGE_SHA256']:
        raise ValueError('API and Fabric package digests differ')
    if state['dataset_version']!=manifest['dataset_version']:raise ValueError('Dataset version mismatch')
    if asset_id not in manifest['assets']:raise KeyError('Unsupported asset')
    for h in I.HORIZONS:
        rows=state['state_by_horizon'][str(h)]
        if len(rows)!=20 or {r['asset_id'] for r in rows}!=set(manifest['assets']):raise ValueError('State must contain all 20 assets per horizon')
    predictions=I.scenario_outputs(models,state,scenarios,asset_id)
    return dict(model=I.MODEL,asset_id=asset_id,model_package_id=state['model_package_id'],
                snapshot_sha256=sha,as_of_trading_date=state['as_of_trading_date'],age_calendar_days=age,
                dataset_version=manifest['dataset_version'],price_basis='adjusted',currency='KRW',
                horizon_unit='trading_days',research_only=True,production_approval='NOT_APPROVED',
                future_market_or_macro_input=True,scenario_inputs_are_assumptions=True,
                historical_availability_verified=False,real_time=False,
                scenarios=scenarios,predictions=predictions)

def make_router():
    from fastapi import APIRouter,HTTPException
    from pydantic import BaseModel,Field,ConfigDict,model_validator
    from typing import Literal
    class Scenario(BaseModel):
        model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
        horizon_days:Literal[1,5,20]
        kospi_pct:float=Field(gt=-100)
        shock_usdkrw_pct:float=Field(gt=-100)
        shock_us10y_bp:float
        shock_wti_pct:float=Field(gt=-100)
        shock_vix_pt:float
    class Request(BaseModel):
        model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
        asset_id:str=Field(pattern=r'^[0-9]{6}$')
        scenarios:list[Scenario]=Field(min_length=3,max_length=3)
        @model_validator(mode='after')
        def all_horizons(self):
            if {s.horizon_days for s in self.scenarios}!={1,5,20}:raise ValueError('Supply each horizon once')
            return self
    router=APIRouter()
    class HistoryRequest(Request):
        horizon_days:Literal[1,5,20]
        snapshot_sha256:str=Field(pattern=r'^[0-9a-f]{64}$')

    @router.post('/scenario/history')
    def history(req:HistoryRequest):
        try:
            from conditional_history import load_history,search_history
            state,sha,_=read_state()
            if sha!=req.snapshot_sha256:
                raise HTTPException(status_code=409,detail='입력 스냅샷이 변경됐습니다. 예측을 다시 실행해 주세요.')
            _,manifest=package(os.environ['STRESSLAB_CONDITIONAL_PACKAGE_DIR'],os.environ['STRESSLAB_CONDITIONAL_MANIFEST_SHA256'])
            if (state['model_zip_sha256']!=os.environ['STRESSLAB_CONDITIONAL_PACKAGE_SHA256']
                or req.asset_id not in manifest['assets']):
                raise ValueError('Model/state contract mismatch')
            data,groups=load_history(os.environ['STRESSLAB_HISTORY_PATH'],
                os.environ['STRESSLAB_HISTORY_SHA256'],os.environ['STRESSLAB_CONDITIONAL_MANIFEST_SHA256'])
            if data['gold_sha256']!=manifest['gold_sha256']:
                raise ValueError('History Gold differs from training Gold')
            scenario=next(s.model_dump() for s in req.scenarios if s.horizon_days==req.horizon_days)
            return search_history(data,groups,state,req.asset_id,req.horizon_days,scenario,sha)
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(status_code=503,detail='학습 구간의 과거 비교 자료를 사용할 수 없습니다.') from None

    @router.get('/scenario/metadata')
    def metadata():
        try:
            state,sha,age=read_state()
            _,manifest=package(os.environ['STRESSLAB_CONDITIONAL_PACKAGE_DIR'],os.environ['STRESSLAB_CONDITIONAL_MANIFEST_SHA256'])
            if (state['model_zip_sha256']!=os.environ['STRESSLAB_CONDITIONAL_PACKAGE_SHA256']
                or state['dataset_version']!=manifest['dataset_version']):
                raise ValueError('Package/state mismatch')
            for h in (1,5,20):
                rows=state['state_by_horizon'][str(h)]
                if len(rows)!=20 or {r['asset_id'] for r in rows}!=set(manifest['assets']):
                    raise ValueError('Incomplete state')
            return dict(model='huber_catboost_hybrid_conditional',supported_assets=manifest['assets'],
                horizons=[1,5,20],model_package_id=state['model_package_id'],snapshot_sha256=sha,
                as_of_trading_date=state['as_of_trading_date'],research_only=True,
                production_approval='NOT_APPROVED',scenario_inputs_are_assumptions=True)
        except Exception:
            raise HTTPException(status_code=503,detail='Conditional model/state unavailable or validation failed') from None
    @router.post('/predict/scenario')
    def scenario(req:Request):
        try:return compute(req.asset_id,[s.model_dump() for s in req.scenarios])
        except KeyError:raise HTTPException(status_code=404,detail='Unsupported asset') from None
        except Exception:raise HTTPException(status_code=503,detail='Conditional model/state unavailable or validation failed') from None
    return router
