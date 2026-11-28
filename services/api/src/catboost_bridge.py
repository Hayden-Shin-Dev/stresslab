"""Extend current app without overwriting deployed news/storage implementations."""
import asyncio,inspect,math,os,re
from typing import Literal
from fastapi import APIRouter,HTTPException,Request
from pydantic import BaseModel,ConfigDict,Field
from analysis_context import attach_context

ENGINE='catboost_multi_horizon_conditional'
CLIENT_CONTRACT='catboost-multihorizon-v1'
KEYS=('model_package_id','manifest_sha256','snapshot_sha256','as_of_trading_date','dataset_version')

def validate_result(result,asset_id,horizon,shocks):
    def reject():raise HTTPException(502,'CatBoost 응답의 모델·기간·입력·단위를 확인할 수 없습니다.')
    if (not isinstance(result,dict) or result.get('model')!='catboost' or result.get('engine_model')!=ENGINE
        or result.get('asset_id')!=asset_id or result.get('horizon_days')!=horizon
        or result.get('shocks')!=shocks or result.get('research_only') is not True
        or result.get('scenario_inputs_are_assumptions') is not True
        or result.get('production_approval')!='NOT_APPROVED' or result.get('price_basis')!='adjusted'
        or result.get('currency')!='KRW' or result.get('horizon_unit')!='trading_days'):reject()
    if any(not isinstance(result.get(k),str) or not result[k] for k in KEYS):reject()
    if any(not re.fullmatch('[0-9a-f]{64}',result.get(k,'')) for k in ('manifest_sha256','snapshot_sha256')):reject()
    p=result.get('prediction',{})
    if p.get('asset_id')!=asset_id or p.get('horizon_days')!=horizon:reject()
    numbers=['base_close','point_log_return_pct','point_simple_return_pct','predicted_close']
    numbers += [f'{side}_{tag}_{suffix}' for side in ('lower','upper') for tag in (80,90) for suffix in ('close','log_return_pct')]
    if any(isinstance(p.get(k),bool) or not isinstance(p.get(k),(float,int)) or not math.isfinite(p[k]) for k in numbers):reject()
    if p['base_close']<=0 or not(0<p['lower_90_close']<=p['lower_80_close']<=p['predicted_close']<=p['upper_80_close']<=p['upper_90_close']):reject()
    try:
        if not math.isclose(p['base_close']*math.exp(p['point_log_return_pct']/100),p['predicted_close'],rel_tol=1e-9):reject()
        if not math.isclose(100*math.expm1(p['point_log_return_pct']/100),p['point_simple_return_pct'],abs_tol=1e-7):reject()
        for side in ('lower','upper'):
            for tag in (80,90):
                if not math.isclose(p['base_close']*math.exp(p[f'{side}_{tag}_log_return_pct']/100),p[f'{side}_{tag}_close'],rel_tol=1e-9):reject()
    except OverflowError:reject()
    return tuple(result[k] for k in KEYS)

async def compute(upstream,address,body):
    h=body.horizon_trading_days
    values=body.shocks.model_dump()
    shocks={'shock_usdkrw_pct':values['fx_pct'],'shock_us10y_bp':values['us_rate_bp'],
            'shock_wti_pct':values['wti_pct'],'shock_vix_pt':values['vix_points']}
    zero={k:0 for k in shocks};limit=asyncio.Semaphore(4)
    async def one(position):
        common={'asset_id':position.asset_id,'horizon_days':h,'model':'catboost'}
        def wire(values):return {**common,'shock_fx_pct':values['shock_usdkrw_pct'],'shock_us_rate_bp':values['shock_us10y_bp'],
            'shock_wti_pct':values['shock_wti_pct'],'shock_vix_points':values['shock_vix_pt']}
        async with limit:
            before=await upstream.call(address+'/predict/auto',payload=wire(zero),ml=True)
            after=before if shocks==zero else await upstream.call(address+'/predict/auto',payload=wire(shocks),ml=True)
        if validate_result(before,position.asset_id,h,zero)!=validate_result(after,position.asset_id,h,shocks):raise HTTPException(409,'계산 중 입력 또는 모델이 변경됐습니다. 다시 실행해 주세요.')
        b=before['prediction'];p=after['prediction']
        if b['base_close']!=p['base_close']:raise HTTPException(409,'기준 수정종가가 변경됐습니다.')
        baseline=b['point_simple_return_pct'];point=p['point_simple_return_pct'];amount=position.value_krw
        row={'asset_id':position.asset_id,'holding_krw':amount,'adjusted_basis':p['base_close'],
            'baseline_model_return_pct':baseline,'scenario_return_pct':point,'change_from_baseline_pp':point-baseline,
            'baseline_pnl_krw':amount*baseline/100,'hypothetical_pnl_krw':amount*point/100,
            'shock_incremental_pnl_krw':amount*(point-baseline)/100,
            'model_interval_90_return_pct':{'lower':100*(p['lower_90_close']/p['base_close']-1),'upper':100*(p['upper_90_close']/p['base_close']-1)},
            'model_output':after,'shock_contributions_pp':None,'historical_examples':None}
        return row,after
    outputs=await asyncio.gather(*(one(p) for p in body.positions))
    if len({tuple(r[k] for k in KEYS) for _,r in outputs})!=1:raise HTTPException(409,'종목 간 모델·입력 기준이 다릅니다.')
    rows=[row for row,_ in outputs];context={k:outputs[0][1][k] for k in KEYS}
    context.update(price_basis='adjusted',engine_model=ENGINE,training_dataset_version=outputs[0][1]['training_dataset_version'])
    result={'api_version':'catboost-multihorizon-v1','model':'catboost','engine_model':ENGINE,'analysis_type':body.analysis_type,
        'horizon_trading_days':h,'shocks':values,'assets':rows,'uses_adjusted_basis':True,
        'portfolio_hypothetical_pnl_krw':sum(r['hypothetical_pnl_krw'] for r in rows),
        'portfolio_shock_incremental_pnl_krw':sum(r['shock_incremental_pnl_krw'] for r in rows),
        'research_only':True,'production_approval':'NOT_APPROVED','scenario_inputs_are_assumptions':True,
        'interval_note':'2024년 보정의 종목별 명목 구간입니다. 실제 포함률이나 포트폴리오 손실 한도를 보장하지 않습니다.'}
    market=None;market_url=os.getenv('MARKET_STATE_URL','').rstrip('/')
    if market_url:
        try:market=await asyncio.wait_for(upstream.call(market_url+'/current'),timeout=4)
        except (HTTPException,asyncio.TimeoutError):pass
    attach_context(result,context,market)
    for r in result['ai_context']['stress_run']['assets']:r['return_basis']='simple'
    if body.analysis_type=='market':result['ai_context']['stress_run'].pop('portfolio',None)
    return result

class HistoryRequest(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    asset_id:str=Field(pattern=r'^[0-9]{6}$')
    horizon_days:Literal[1,5,20]
    snapshot_sha256:str=Field(pattern=r'^[0-9a-f]{64}$')
    shock_usdkrw_pct:float=Field(ge=-30,le=30)
    shock_us10y_bp:float=Field(ge=-300,le=300)
    shock_wti_pct:float=Field(ge=-80,le=80)
    shock_vix_pt:float=Field(ge=-80,le=80)

def install(app):
    import gateway
    original_analyze=next(r.endpoint for r in app.routes if getattr(r,'path',None)=='/api/stress/analyze')
    original_support=next(r.endpoint for r in app.routes if getattr(r,'path',None)=='/api/stress/support')
    original=inspect.getclosurevars(original_analyze).nonlocals
    if not {'persist','compute'}<=set(original):raise RuntimeError('Deployed gateway integration contract changed')
    legacy_class=gateway.AnalyzeRequest
    class AnalyzeRequest(legacy_class):
        horizon_trading_days:Literal[1,5,20]=5
    # News recalculation and receipt recovery import this class at call time.
    gateway.AnalyzeRequest=AnalyzeRequest
    router=APIRouter()
    @router.get('/api/stress/support')
    async def support(request:Request):
        if os.getenv('STRESSLAB_CATBOOST_MULTI_ENABLED','false').lower()!='true' or request.headers.get('x-stresslab-client-contract')!=CLIENT_CONTRACT:return await original_support(request)
        envelope=await request.app.state.upstream.call(os.environ['ML_API_URL'].rstrip('/')+'/metadata',ml=True)
        value=envelope.get('catboost_multihorizon',{})
        if value.get('engine_model')!=ENGINE or value.get('supported_horizon_trading_days')!=[1,5,20] or len(set(value.get('supported_assets',[])))!=20:raise HTTPException(502,'CatBoost 지원 계약이 다릅니다.')
        return value
    @router.post('/api/stress/analyze')
    async def analyze(body:AnalyzeRequest,request:Request):
        async def calculate():
            if (body.model=='catboost' and os.getenv('STRESSLAB_CATBOOST_MULTI_ENABLED','false').lower()=='true'
                and request.headers.get('x-stresslab-client-contract')==CLIENT_CONTRACT):
                result=await compute(request.app.state.upstream,os.environ['ML_API_URL'].rstrip('/'),body)
            else:
                if body.horizon_trading_days!=5:raise HTTPException(422,'현재 설정의 기존 모델은 5거래일만 지원합니다.')
                result=await original['compute'](request.app.state.upstream,body)
            # Reuse the exact deployed persistence/receipt implementation.
            await original['persist'](request,body,result)
            return result
        try:return await asyncio.wait_for(calculate(),timeout=40)
        except asyncio.TimeoutError:raise HTTPException(504,'분석 시간이 초과됐습니다.') from None
    @router.post('/api/stress/catboost/history')
    async def history(body:HistoryRequest,request:Request):
        if os.getenv('STRESSLAB_CATBOOST_MULTI_ENABLED','false').lower()!='true':raise HTTPException(503,'새 CatBoost가 활성화되지 않았습니다.')
        wire={'model':'catboost','operation':'catboost_history','asset_id':body.asset_id,'horizon_days':body.horizon_days,
            'snapshot_sha256':body.snapshot_sha256,'shock_fx_pct':body.shock_usdkrw_pct,'shock_us_rate_bp':body.shock_us10y_bp,
            'shock_wti_pct':body.shock_wti_pct,'shock_vix_points':body.shock_vix_pt}
        value=await request.app.state.upstream.call(os.environ['ML_API_URL'].rstrip('/')+'/predict/auto',payload=wire,ml=True)
        if (value.get('schema')!='catboost-history-response-v1' or value.get('asset_id')!=body.asset_id or value.get('horizon_days')!=body.horizon_days
            or value.get('snapshot_sha256')!=body.snapshot_sha256 or value.get('source_split')!='train'
            or not isinstance(value.get('cases'),list) or len(value['cases'])>5):raise HTTPException(502,'CatBoost 과거 사례 계약이 다릅니다.')
        return value
    # Replace only these two routes, retaining all authentication middleware and
    # all debate/news/storage/conditional endpoints from the pinned base image.
    app.router.routes[:]=[r for r in app.router.routes if getattr(r,'path',None) not in ('/api/stress/support','/api/stress/analyze')]
    app.include_router(router)
    app.openapi_schema=None
