"""Minimal local-only service candidate. Reads a JSON model; no provider credentials."""
import json,os
from pathlib import Path
import numpy as np
from fastapi import FastAPI,HTTPException
from pydantic import BaseModel,Field,ConfigDict

MODEL_PATH=Path(os.environ.get('STRESSLAB_MODEL_PATH',Path(__file__).with_name('model.json')))
app=FastAPI(title='StressLab model candidate',version='1.0')

class Position(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    asset_id:str
    value_krw:float=Field(gt=0)

class Shocks(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    fx_pct:float=0
    us_rate_bp:float=0
    wti_pct:float=Field(default=0,gt=-100)
    vix_change_points:float=0

class Request(BaseModel):
    model_config=ConfigDict(extra='forbid')
    positions:list[Position]=Field(min_length=1,max_length=20)
    shocks:Shocks

def load():return json.loads(MODEL_PATH.read_text(encoding='utf8'))

@app.get('/health')
def health():
    m=load();return dict(status='ok',model_version=m['version'],state_date=m['state_date'],mode=m['status'])

@app.get('/model-info')
def info():
    m=load();return {k:m[k] for k in ['version','status','state_date','train_label_end','calibration_end','reference_assumption','research_metrics','publication_timestamps_verified','lockbox_validated']}

@app.post('/stress')
def stress(request:Request):
    m=load();assets=[p.asset_id for p in request.positions]
    if len(set(assets))!=len(assets):raise HTTPException(422,'같은 종목을 중복 입력하지 마세요.')
    missing=[a for a in assets if a not in m['states']]
    if missing:raise HTTPException(422,{'message':'현재 후보 모델에 없는 종목입니다.','assets':missing})
    s=dict(zip(['shock_fx','shock_rate','shock_oil','shock_vix'],[request.shocks.fx_pct,request.shocks.us_rate_bp,request.shocks.wti_pct,request.shocks.vix_change_points]))
    if request.shocks.fx_pct<=-100:raise HTTPException(422,'환율 변화는 -100%보다 커야 합니다.')
    results=[];sup=m['support'];hist=np.asarray(sup['reference_vectors'])
    for position in request.positions:
        state=m['states'][position.asset_id]
        if state['vix_level']+s['shock_vix']<0:raise HTTPException(422,'입력한 변화로 VIX 수준이 음수가 됩니다.')
        contribution={}
        for shock,change in s.items():
            b=m['coefficients'][position.asset_id][shock];beta=b['common']+b['asset_deviation']+b['trend_interaction']*state['market_trend20']+b['vol_interaction']*state['market_vol20']
            contribution[shock]=float(state['scale']*beta*change)
        center=sum(contribution.values());lo=center+m['residual_q10']*state['scale'];hi=center+m['residual_q90']*state['scale']
        if not np.isfinite([center,lo,hi]).all():raise HTTPException(422,'숫자가 계산 가능한 범위를 넘었습니다.')
        features={**state,**s};x=(np.array([features[c] for c in sup['columns']])-sup['median'])/sup['iqr']
        with np.errstate(over='ignore'):dist=np.linalg.norm(hist-x,axis=1)
        ratio=float(np.partition(dist,2)[:3].mean()/sup['threshold'])
        outside=[k for k,v in s.items() if not sup['marginal_bounds'][k][0]<=v<=sup['marginal_bounds'][k][1]];supported=ratio<=1 and not outside
        pnl=position.value_krw*center/100
        if not np.isfinite(pnl):raise HTTPException(422,'평가금액이 계산 가능한 범위를 넘었습니다.')
        results.append(dict(asset_id=position.asset_id,value_krw=position.value_krw,reference_return_pct=0,model_center_return_pct=center,model_change_from_zero_shocks_pct=center,hypothetical_pnl_krw=pnl,factor_contribution_pp=contribution,historical_calibration_band_pct=[lo,hi],historical_downside_reference_pct=lo,support_label='supported_history' if supported else 'exploratory',support_distance_ratio=ratio if np.isfinite(ratio) else None,outside_historical_marginal=outside,scenario_probability_validated=False,historical_analogues=m['analogues'][position.asset_id]))
    return dict(model_version=m['version'],status='project_demo_candidate',state_date=m['state_date'],train_label_end=m['train_label_end'],calibration_end=m['calibration_end'],input_shocks=request.shocks.model_dump(),reference_assumption=m['reference_assumption'],total_value_krw=sum(p.value_krw for p in request.positions),hypothetical_portfolio_pnl_krw=sum(x['hypothetical_pnl_krw'] for x in results),assets=results,validation=m['research_metrics'],notices=['무충격 기준 수익률을 0%로 둔 시나리오 계산입니다.','요인 기여도는 통계 모델의 분해이며 검증된 인과효과가 아닙니다.','구간은 과거 보정 오차의 참고 범위이며 입력 시나리오의 확률 보장이 아닙니다.','현재 자료는 확정 일별 스냅샷이며 실시간 장중 ML이 아닙니다.','공표 시각과 독립 Lockbox 검증이 남아 있습니다.'])
