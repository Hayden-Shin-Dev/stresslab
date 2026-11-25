"""Authenticated common-API bridge for the three-horizon conditional model."""
import asyncio
import math
from typing import Literal

from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Scenario(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    horizon_days: Literal[1, 5, 20]
    kospi_pct: float = Field(gt=-100)
    shock_usdkrw_pct: float = Field(gt=-100)
    shock_us10y_bp: float
    shock_wti_pct: float = Field(gt=-100)
    shock_vix_pt: float


class ConditionalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    asset_ids: list[str] = Field(min_length=1, max_length=20)
    scenarios: list[Scenario] = Field(min_length=3, max_length=3)

    @model_validator(mode="after")
    def distinct_inputs(self):
        if len(set(self.asset_ids)) != len(self.asset_ids):
            raise ValueError("Duplicate assets")
        if any(len(a) != 6 or not a.isascii() or not a.isdigit() for a in self.asset_ids):
            raise ValueError("Use six-digit string asset IDs")
        if {s.horizon_days for s in self.scenarios} != {1, 5, 20}:
            raise ValueError("Supply horizons 1, 5, 20 exactly once")
        return self


class HistoryRequest(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    asset_id:str=Field(pattern=r'^[0-9]{6}$')
    scenarios:list[Scenario]=Field(min_length=3,max_length=3)
    horizon_days:Literal[1,5,20]
    snapshot_sha256:str=Field(pattern=r'^[0-9a-f]{64}$')

    @model_validator(mode='after')
    def horizons_once(self):
        if {s.horizon_days for s in self.scenarios}!={1,5,20}:
            raise ValueError('Supply each horizon once')
        return self


def validate_result(result, asset_id, scenarios):
    """Do not let an upstream contract error become a chart or price."""
    def reject():
        raise HTTPException(502, "조건부 모델 응답 검증에 실패했습니다.")

    if not isinstance(result, dict):
        reject()
    if (result.get("asset_id") != asset_id
        or result.get("model") != "huber_catboost_hybrid_conditional"
        or result.get("research_only") is not True
        or result.get("scenario_inputs_are_assumptions") is not True
        or result.get("production_approval") != "NOT_APPROVED"
        or result.get("price_basis") != "adjusted"
        or result.get("currency") != "KRW"
        or result.get("horizon_unit") != "trading_days"
        or result.get("scenarios") != scenarios):
        reject()
    signature = tuple(result.get(k) for k in (
        "snapshot_sha256", "model_package_id", "as_of_trading_date", "dataset_version"))
    if any(not isinstance(v, str) or not v for v in signature):
        reject()
    rows = result.get("predictions")
    if (not isinstance(rows, list) or len(rows) != 3
        or any(not isinstance(r, dict) for r in rows)
        or any(type(r.get("horizon_days")) is not int for r in rows)
        or {r.get("horizon_days") for r in rows} != {1, 5, 20}):
        reject()
    keys = ("base_close", "predicted_close", "point_simple_return_pct",
            "lower_80_close", "upper_80_close", "lower_90_close", "upper_90_close")
    for row in rows:
        if row.get("asset_id") != asset_id:
            reject()
        if any(isinstance(row.get(k), bool) or not isinstance(row.get(k), (int, float))
               or not math.isfinite(row[k]) for k in keys):
            reject()
        if any(row[k] <= 0 for k in keys if k != "point_simple_return_pct"):
            reject()
        if not (row["lower_90_close"] <= row["lower_80_close"]
                <= row["predicted_close"] <= row["upper_80_close"] <= row["upper_90_close"]):
            reject()
        if not math.isclose(row["predicted_close"] / row["base_close"] * 100 - 100,
                            row["point_simple_return_pct"], abs_tol=1e-6):
            reject()
    if len({r["base_close"] for r in rows}) != 1:
        reject()
    return signature


def install(app, ml_url):
    # These routes inherit gateway.py's APIM key and signed-in-user checks.
    @app.get("/api/stress/scenario/support")
    async def support(request: Request):
        if not ml_url:
            raise HTTPException(503, "ML 주소가 설정되지 않았습니다.")
        return await request.app.state.upstream.call(ml_url + "/scenario/metadata", ml=True)

    @app.post('/api/stress/scenario/history')
    async def history(body:HistoryRequest,request:Request):
        if not ml_url:
            raise HTTPException(503,'ML 주소가 설정되지 않았습니다.')
        result=await request.app.state.upstream.call(ml_url+'/scenario/history',payload=body.model_dump(),ml=True)
        if (not isinstance(result,dict) or result.get('schema')!='conditional-history-response-v1'
            or result.get('asset_id')!=body.asset_id or result.get('horizon_days')!=body.horizon_days
            or result.get('snapshot_sha256')!=body.snapshot_sha256 or result.get('source_split')!='train'
            or not isinstance(result.get('cases'),list) or len(result['cases'])>5):
            raise HTTPException(502,'과거 비교 응답이 요청과 다릅니다.')
        chosen=next(s for s in body.scenarios if s.horizon_days==body.horizon_days)
        shocks=('shock_usdkrw_pct','shock_us10y_bp','shock_wti_pct','shock_vix_pt')
        if result.get('current_shocks')!={k:getattr(chosen,k) for k in shocks}:
            raise HTTPException(502,'과거 비교의 충격 조건이 요청과 다릅니다.')
        for case in result['cases']:
            values=[case.get('actual_return_pct')]+[case.get('actual_shocks',{}).get(k) for k in shocks]
            if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in values):
                raise HTTPException(502,'과거 비교 관측값이 올바르지 않습니다.')
        return result

    @app.post("/api/stress/scenario")
    async def scenario(body: ConditionalRequest, request: Request):
        if not ml_url:
            raise HTTPException(503, "ML 주소가 설정되지 않았습니다.")
        scenarios = [s.model_dump() for s in body.scenarios]
        upstream = request.app.state.upstream
        limit = asyncio.Semaphore(4)

        async def one(asset_id):
            async with limit:
                result = await upstream.call(ml_url + "/predict/scenario",
                    payload={"asset_id": asset_id, "scenarios": scenarios}, ml=True)
                signature = validate_result(result, asset_id, scenarios)
                return result, signature

        try:
            results = await asyncio.wait_for(
                asyncio.gather(*(one(a) for a in body.asset_ids)), timeout=35)
        except asyncio.TimeoutError:
            raise HTTPException(504, "조건부 분석 시간이 초과됐습니다. 다시 실행해 주세요.") from None
        if len({sig for _, sig in results}) != 1:
            raise HTTPException(409, "계산 중 입력 스냅샷이 변경됐습니다. 다시 실행해 주세요.")
        return {"model": "huber_catboost_hybrid_conditional", "horizons": [1, 5, 20],
                "results": [r for r, _ in results], "research_only": True,
                "scenario_inputs_are_assumptions": True,
                "ai_handoff": {"ready": False,
                    "reason": "새 모델의 토론·보관소 계약은 아직 연결되지 않았습니다."}}
