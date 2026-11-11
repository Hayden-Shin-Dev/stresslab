"""공통 서비스 API. 모델 학습과 Fabric 코드는 변경하지 않습니다."""
from __future__ import annotations

import asyncio
import hmac
import json
import math
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

import httpx
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

# 2026-11-11 민철 추가: 기존 토론/보유종목/큐 처리 코드를 공통 API에서 재사용합니다.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "debate" / "src"))
from api import create_app as create_debate_app, parse_client_principal


class Shocks(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    fx_pct: float = Field(0, gt=-100)
    us_rate_bp: float = 0
    wti_pct: float = Field(0, gt=-100)
    vix_points: float = 0


class Position(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    asset_id: str = Field(pattern=r"^\d{6}$")
    value_krw: float = Field(gt=0, le=1e13)


class AnalyzeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    positions: list[Position] = Field(min_length=1, max_length=20)
    shocks: Shocks = Field(default_factory=Shocks)
    model: Literal["catboost", "ridge"] = "catboost"

    @model_validator(mode="after")
    def unique_assets(self):
        if len({p.asset_id for p in self.positions}) != len(self.positions):
            raise ValueError("동일 종목을 중복 입력할 수 없습니다.")
        return self


class Upstream:
    def __init__(self):
        self.client = httpx.AsyncClient(timeout=httpx.Timeout(12, connect=4), follow_redirects=False)
        self.credential = None
        self.signer = None
        self.limit = asyncio.Semaphore(6)

    async def call(self, url, *, payload=None, ml=False):
        headers = {}
        body = b"" if payload is None else json.dumps(payload, separators=(",", ":"), allow_nan=False).encode()
        if payload is not None:
            headers["Content-Type"] = "application/json"
        if ml and os.environ.get("ML_SIGNING_KEY_ID"):
            from service_signing import ServiceSigner
            if self.signer is None:
                self.signer = ServiceSigner(self.client)
            async with self.limit:
                try:
                    method = "POST" if payload is not None else "GET"
                    headers["X-StressLab-Service-Token"] = await asyncio.wait_for(
                        self.signer.sign(method, httpx.URL(url).path, body), timeout=8)
                    r = await self.client.request(method, url, content=body, headers=headers)
                    if r.status_code >= 400:
                        raise HTTPException(503, {"code": "upstream_error", "status": r.status_code})
                    return r.json()
                except HTTPException:
                    raise
                except Exception as exc:
                    raise HTTPException(503, {"code": "ml_service_auth_or_transport_unavailable"}) from exc
        if ml:
            if self.credential is None:
                from azure.identity.aio import DefaultAzureCredential
                self.credential = DefaultAzureCredential(managed_identity_client_id=os.environ.get("AZURE_CLIENT_ID"))
            try:
                token = await asyncio.wait_for(self.credential.get_token(os.environ["ML_TOKEN_SCOPE"]), timeout=8)
            except Exception as exc:
                raise HTTPException(503, {"code": "ml_auth_unavailable", "message": "ML 서버 호출 권한을 확인해야 합니다."}) from exc
            headers["Authorization"] = "Bearer " + token.token
        async with self.limit:
            try:
                r = await self.client.request("POST" if payload is not None else "GET", url, json=payload, headers=headers)
                if r.status_code >= 400:
                    # 원격 인증/DB 오류의 본문이나 토큰을 사용자에게 노출하지 않습니다.
                    raise HTTPException(503, {"code": "upstream_error", "status": r.status_code})
                return r.json()
            except (httpx.HTTPError, ValueError) as exc:
                raise HTTPException(503, "분석 서버 응답을 확인할 수 없습니다.") from exc

    async def close(self):
        await self.client.aclose()
        if self.credential:
            await self.credential.close()
        if self.signer:
            await self.signer.close()


def simple_return(log_pct):
    value = float(log_pct)
    if not math.isfinite(value) or abs(value) > 1000:
        raise HTTPException(502, "모델 수익률 출력 범위를 확인해야 합니다.")
    return math.expm1(value / 100) * 100


def create_app(deps=None, upstream=None, gateway_key=None):
    app = create_debate_app(deps)
    app.title = "StressLab common API"
    app.version = "1.0"
    app.state.upstream = upstream
    key = gateway_key if gateway_key is not None else os.environ.get("GATEWAY_SHARED_KEY", "")
    original_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(app):
        if not key:
            raise RuntimeError("GATEWAY_SHARED_KEY is required")
        if app.state.upstream is None:
            app.state.upstream = Upstream()
        async with original_lifespan(app):
            try:
                yield
            finally:
                await app.state.upstream.close()
    app.router.lifespan_context = lifespan

    # 2026-11-11 민철 추가: SWA 전용 헤더는 APIM의 검증된 요청에서만 신뢰합니다.
    # 기존 토론 컨테이너는 변경하지 않으며 새 공통 컨테이너에만 적용합니다.
    @app.middleware("http")
    async def trusted_gateway(request: Request, call_next):
        if request.url.path in ("/healthz", "/api/healthz"):
            return JSONResponse({"status": "ok", "service": "stresslab-common-api"})
        supplied = request.headers.get("x-stresslab-gateway-key", "")
        if not key or not hmac.compare_digest(supplied, key):
            return JSONResponse({"detail": "공통 API는 API Management를 통해 호출해야 합니다."}, status_code=403)
        try:
            principal = parse_client_principal(request.headers.get("x-ms-client-principal"))
        except (AttributeError, TypeError):
            principal = None
        if not principal:
            return JSONResponse({"detail": "로그인이 필요합니다."}, status_code=401)
        if request.url.path.endswith("/scheduled-debates"):
            return JSONResponse({"detail": "예약 작업은 기존 스케줄러 경로를 사용합니다."}, status_code=403)
        request.state.principal = principal
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    ml_url = os.environ.get("ML_API_URL", "").rstrip("/")

    @app.get("/api/stress/support")
    async def support(request: Request):
        if not ml_url:
            raise HTTPException(503, "ML 주소가 설정되지 않았습니다.")
        return await request.app.state.upstream.call(ml_url + "/metadata", ml=True)

    @app.get("/api/stress/snapshot")
    async def snapshot(request: Request):
        return await request.app.state.upstream.call(ml_url + "/snapshot/metadata", ml=True)

    @app.post("/api/stress/analyze")
    async def analyze(body: AnalyzeRequest, request: Request):
        if not ml_url:
            raise HTTPException(503, "ML 주소가 설정되지 않았습니다.")
        upstream = request.app.state.upstream

        async def calculate():
            metadata = await upstream.call(ml_url + "/metadata", ml=True)
            unsupported = [p.asset_id for p in body.positions if p.asset_id not in metadata["supported_assets"]]
            if unsupported:
                raise HTTPException(422, {"code": "unsupported_assets", "asset_ids": unsupported})
            values = body.shocks.model_dump()
            shocks = {"shock_fx_pct": values["fx_pct"], "shock_us_rate_bp": values["us_rate_bp"],
                      "shock_wti_pct": values["wti_pct"], "shock_vix_points": values["vix_points"]}

            async def asset(p):
                common = {"asset_id": p.asset_id, "model": body.model}
                stress = await upstream.call(ml_url + "/predict/auto", payload={**common, **shocks}, ml=True)
                base = (stress if not any(shocks.values()) else await upstream.call(
                    ml_url + "/predict/auto", payload={**common, **{k: 0 for k in shocks}}, ml=True))
                signature = lambda r: tuple(r.get(k) for k in ("package_id", "dataset_version", "feature_as_of_trading_date"))
                if signature(base) != signature(stress):
                    raise HTTPException(409, "계산 중 모델 또는 입력 버전이 변경됐습니다. 다시 요청하세요.")
                for result in (base, stress):
                    if result.get("asset_id") != p.asset_id or result.get("model") != body.model:
                        raise HTTPException(502, "모델 응답의 종목 또는 모델이 요청과 다릅니다.")
                    required=("package_id", "dataset_version", "feature_as_of_trading_date",
                        "point_log_return_5d_pct", "lower_90_log_return_5d_pct", "upper_90_log_return_5d_pct")
                    if any(result.get(k) is None for k in required):
                        raise HTTPException(502, "모델 응답의 필수값이 누락됐습니다.")
                c, b = (simple_return(x["point_log_return_5d_pct"]) for x in (stress, base))
                lo, hi = (simple_return(stress[k]) for k in ("lower_90_log_return_5d_pct", "upper_90_log_return_5d_pct"))
                if lo > hi:
                    raise HTTPException(502, "모델 구간의 하한이 상한보다 큽니다.")
                return {"asset_id": p.asset_id, "holding_krw": p.value_krw,
                        "baseline_model_return_pct": b, "scenario_return_pct": c,
                        "change_from_baseline_pp": c-b, "hypothetical_pnl_krw": p.value_krw*c/100,
                        "baseline_pnl_krw": p.value_krw*b/100, "shock_incremental_pnl_krw": p.value_krw*(c-b)/100,
                        "model_interval_90_return_pct": {"lower": lo, "upper": hi},
                        "shock_contributions_pp": None, "historical_examples": None,
                        "unavailable_fields_reason": "현재 배포 ML API는 충격별 기여도와 과거 사례를 반환하지 않습니다.",
                        "model_output": stress, "_signature": signature(stress)}

            rows = await asyncio.gather(*(asset(p) for p in body.positions))
            if len({r.pop("_signature") for r in rows}) != 1:
                raise HTTPException(409, "종목 간 모델 또는 입력 버전이 다릅니다.")
            return {"api_version": "1.0", "model": body.model, "horizon_trading_days": 5,
                    "shocks": values, "assets": rows,
                    "portfolio_hypothetical_pnl_krw": sum(r["hypothetical_pnl_krw"] for r in rows),
                    "portfolio_shock_incremental_pnl_krw": sum(r["shock_incremental_pnl_krw"] for r in rows),
                    "research_only": True, "production_approval": "NOT_APPROVED",
                    "interval_note": "종목별 모델 구간입니다. 포트폴리오 손실 한도나 포함률을 보장하지 않습니다."}
        try:
            return await asyncio.wait_for(calculate(), timeout=35)
        except asyncio.TimeoutError as exc:
            raise HTTPException(504, "분석 시간이 초과됐습니다. 잠시 후 다시 요청하세요.") from exc

    # 고정 대상만 전달합니다. 사용자가 임의 URL/인증 헤더를 전달할 수 없습니다.
    @app.get("/api/quotes/latest")
    async def quotes(request: Request):
        return await request.app.state.upstream.call(os.environ["QUOTE_API_URL"].rstrip("/") + "/latest")

    @app.post("/api/quotes/negotiate")
    async def quote_token(request: Request):
        return await request.app.state.upstream.call(os.environ["QUOTE_API_URL"].rstrip("/") + "/negotiate", payload={})

    @app.get("/api/market-state/current")
    async def market(request: Request):
        return await request.app.state.upstream.call(os.environ["MARKET_STATE_URL"].rstrip("/") + "/current")

    @app.post("/api/market-state/negotiate")
    async def market_token(request: Request):
        return await request.app.state.upstream.call(os.environ["MARKET_STATE_URL"].rstrip("/") + "/negotiate", payload={})

    return app


app = create_app()
