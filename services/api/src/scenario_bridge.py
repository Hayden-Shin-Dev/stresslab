"""Persist server-computed conditional runs for the same evidence path as CatBoost."""
import asyncio
import base64
import hashlib
import hmac
import json
import os
from typing import Literal

from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator
from analysis_context import attach_context
from conditional_gateway import validate_result

MODEL = "huber_catboost_hybrid_conditional"
HORIZONS = (1, 5, 20)


class Position(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    asset_id: str = Field(pattern=r"^\d{6}$")
    value_krw: float = Field(gt=0, le=1e13)


class Shocks(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    fx_pct: float = Field(0, ge=-30, le=30)
    us_rate_bp: float = Field(0, ge=-300, le=300)
    wti_pct: float = Field(0, ge=-80, le=80)
    vix_points: float = Field(0, ge=-80, le=80)


class Analysis(BaseModel):
    model_config = ConfigDict(extra="forbid")
    positions: list[Position] = Field(min_length=1, max_length=20)
    shocks: Shocks = Field(default_factory=Shocks)
    analysis_type: Literal["market", "portfolio"] = "market"
    model: Literal["huber_catboost_hybrid_conditional"] = MODEL
    horizon_trading_days: Literal[1, 5, 20] = 5

    @model_validator(mode="after")
    def distinct(self):
        if len({p.asset_id for p in self.positions}) != len(self.positions):
            raise ValueError("동일 종목은 한 번만 선택해 주세요.")
        return self


def scenarios(shocks, horizon):
    return [dict(horizon_days=day, kospi_pct=0,
                 shock_usdkrw_pct=shocks.fx_pct if day == horizon else 0,
                 shock_us10y_bp=shocks.us_rate_bp if day == horizon else 0,
                 shock_wti_pct=shocks.wti_pct if day == horizon else 0,
                 shock_vix_pt=shocks.vix_points if day == horizon else 0) for day in HORIZONS]


async def conditional_result(upstream, address, body):
    before = scenarios(Shocks(), body.horizon_trading_days)
    after = scenarios(body.shocks, body.horizon_trading_days)
    limit = asyncio.Semaphore(4)

    async def one(position):
        async with limit:
            payload = dict(asset_id=position.asset_id)
            baseline = await upstream.call(address + "/predict/scenario", payload=dict(payload, scenarios=before), ml=True)
            shocked = baseline if before == after else await upstream.call(
                address + "/predict/scenario", payload=dict(payload, scenarios=after), ml=True)
            if validate_result(baseline, position.asset_id, before) != validate_result(shocked, position.asset_id, after):
                raise HTTPException(409, "계산 기준이 변경됐습니다. 다시 실행해 주세요.")
        base = next(p for p in baseline["predictions"] if p["horizon_days"] == body.horizon_trading_days)
        pred = next(p for p in shocked["predictions"] if p["horizon_days"] == body.horizon_trading_days)
        if pred["base_close"] != base["base_close"]:
            raise HTTPException(409, "기준 수정종가가 변경됐습니다.")
        b, c, amount = base["point_simple_return_pct"], pred["point_simple_return_pct"], position.value_krw
        row = dict(asset_id=position.asset_id, holding_krw=amount,
                   baseline_model_return_pct=b, scenario_return_pct=c, change_from_baseline_pp=c-b,
                   baseline_pnl_krw=amount*b/100, hypothetical_pnl_krw=amount*c/100,
                   shock_incremental_pnl_krw=amount*(c-b)/100,
                   model_interval_90_return_pct=dict(lower=(pred["lower_90_close"]/pred["base_close"]-1)*100,
                                                     upper=(pred["upper_90_close"]/pred["base_close"]-1)*100),
                   adjusted_basis=pred["base_close"])
        return row, shocked

    rows = await asyncio.gather(*(one(p) for p in body.positions))
    fields = ("model_package_id", "snapshot_sha256", "as_of_trading_date", "dataset_version")
    signatures = {tuple(result[k] for k in fields) for _, result in rows}
    if len(signatures) != 1:
        raise HTTPException(409, "종목 간 계산 기준이 다릅니다. 다시 실행해 주세요.")
    assets = [row for row, _ in rows]
    return dict(model=MODEL, analysis_type=body.analysis_type, horizon_trading_days=body.horizon_trading_days,
                shocks=body.shocks.model_dump(), assets=assets,
                portfolio_hypothetical_pnl_krw=sum(a["hypothetical_pnl_krw"] for a in assets),
                portfolio_shock_incremental_pnl_krw=sum(a["shock_incremental_pnl_krw"] for a in assets),
                model_context={key: rows[0][1][key] for key in fields}, conditional_scenarios=after)


def sign_result(result, original, owner, key):
    payload = dict(owner=owner, request=original, result=result)
    encoded = base64.urlsafe_b64encode(json.dumps(payload,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).decode()
    signature = hmac.new(key.encode(),("whatif-result-recovery-v1:"+encoded).encode(),hashlib.sha256).hexdigest()
    return encoded+"."+signature


def read_receipt(receipt, owner, key):
    try:
        encoded, signature = receipt.rsplit(".", 1)
        expected = hmac.new(key.encode(),("whatif-result-recovery-v1:"+encoded).encode(),hashlib.sha256).hexdigest()
        if not key or not hmac.compare_digest(signature, expected):
            raise ValueError("signature")
        saved = json.loads(base64.urlsafe_b64decode(encoded))
        if saved["owner"] != owner:
            raise HTTPException(404, "본인 분석 결과를 선택해 주세요.")
        return saved
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(422, "분석 결과를 확인할 수 없습니다. 다시 실행해 주세요.") from exc


async def save_result(request, body, result):
    owner = request.state.principal["user_id"]
    key = os.environ["GATEWAY_SHARED_KEY"]
    result["recovery_receipt"] = sign_result(result, body.model_dump(), owner, key)
    reader = request.app.state.deps.reader
    try:
        await reader.save_stress_run(result["analysis_id"], owner, body.model_dump(),
                                     result["ai_context"]["stress_run"], result["ai_context"].get("market_snapshot"))
    except Exception:
        result["ai_handoff"] = dict(ready=False, persisted=False, reason="분석 근거를 저장하지 못했습니다.")
    else:
        result["ai_handoff"] = dict(ready=True, persisted=True)


def install(app):
    @app.post("/api/stress/scenario/analyze")
    async def analyze(body: Analysis, request: Request):
        address = os.environ.get("ML_API_URL", "").rstrip("/")
        if not address:
            raise HTTPException(503, "분석 서버에 연결할 수 없습니다.")
        try:
            result = await asyncio.wait_for(conditional_result(request.app.state.upstream, address, body), timeout=40)
        except asyncio.TimeoutError as exc:
            raise HTTPException(504, "분석이 지연되고 있습니다. 다시 실행해 주세요.") from exc
        market = None
        market_url = os.environ.get("MARKET_STATE_URL", "").rstrip("/")
        if market_url:
            try:
                market = await asyncio.wait_for(request.app.state.upstream.call(market_url+"/current"), timeout=4)
            except (HTTPException, asyncio.TimeoutError):
                pass
        metadata = result["model_context"]
        attach_context(result, metadata, market)
        result["ai_context"]["stress_run"]["analysis_type"] = body.analysis_type
        for asset in result["ai_context"]["stress_run"]["assets"]:
            asset["return_basis"] = "simple"
        if body.analysis_type == "market":
            result["ai_context"]["stress_run"].pop("portfolio", None)
        await save_result(request, body, result)
        return result
