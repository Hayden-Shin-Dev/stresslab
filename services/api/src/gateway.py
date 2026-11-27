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
import logging
from datetime import datetime
from typing import Literal, Optional

import httpx
from fastapi import Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator
from analysis_context import attach_context

# 2026-11-11 민철 추가: 기존 토론/보유종목/큐 처리 코드를 공통 API에서 재사용합니다.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "debate" / "src"))
from api import create_app as create_debate_app, parse_client_principal
from api import KST, ScheduleBody, _key, _schedule_targets, _send, _start_request

log = logging.getLogger("gateway")


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
    horizon_trading_days: Literal[1, 5, 20] = 5

    @model_validator(mode="after")
    def unique_assets(self):
        if len({p.asset_id for p in self.positions}) != len(self.positions):
            raise ValueError("동일 종목을 중복 입력할 수 없습니다.")
        if self.model == "ridge" and self.horizon_trading_days != 5:
            raise ValueError("Ridge는 5거래일만 지원합니다.")
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
        if request.url.path == "/internal/scheduled-debates":
            # 예약 작업 전용. APIM에 노출하지 않으며, 처리 함수가 X-Scheduler-Key를 확인합니다.
            response = await call_next(request)
            response.headers["Cache-Control"] = "no-store"
            return response
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
        # 분석 ID(a-...) 토론은 토론 API가 저장 여부와 본인 결과인지 확인합니다(없으면 404).
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

    async def persist(request: Request, body: "AnalyzeRequest", out: dict):
        """분석 결과를 stress_run 테이블에 저장(변경 불가). 토론은 이 analysis_id로 POST /api/debates."""
        deps = getattr(request.app.state, "deps", None)
        reader = getattr(deps, "reader", None)
        principal = getattr(request.state, "principal", None) or {}
        save = getattr(reader, "save_stress_run", None)
        if save is None or not principal.get("user_id"):
            return
        try:
            await save(out["analysis_id"], principal["user_id"], body.model_dump(),
                       out["ai_context"]["stress_run"], out["ai_context"].get("market_snapshot"))
        except Exception as exc:   # 저장 실패해도 계산 결과는 돌려줌(토론만 못 함)
            out["ai_handoff"].update(ready=False, persisted=False, reason=f"결과 저장 실패: {type(exc).__name__}")
            return
        out["ai_handoff"] = {"ready": True, "status": "persisted", "persisted": True,
                             "debate_request": {"method": "POST", "path": "/api/debates",
                                                "body": {"run_id": out["analysis_id"]}}}

    async def compute(upstream, body: "AnalyzeRequest") -> dict:
        """ML 계산 + 장중 상태 붙이기. 웹 분석과 정시 회의가 같이 씁니다(저장은 호출한 쪽에서)."""
        metadata = await upstream.call(ml_url + "/metadata", ml=True)
        horizon = body.horizon_trading_days
        if horizon != 5 and horizon not in (metadata.get("supported_horizon_trading_days") or []):
            raise HTTPException(422, {"code": "unsupported_horizon", "horizon_trading_days": horizon})
        point_field = f"point_log_return_{horizon}d_pct"
        lower_field = f"lower_90_log_return_{horizon}d_pct"
        upper_field = f"upper_90_log_return_{horizon}d_pct"
        unsupported = [p.asset_id for p in body.positions if p.asset_id not in metadata["supported_assets"]]
        if unsupported:
            raise HTTPException(422, {"code": "unsupported_assets", "asset_ids": unsupported})
        # 2026-11-12 민철 추가: 계산 전후 입력 해시로 같은 날짜의 갱신도 감지합니다.
        before = await upstream.call(ml_url + "/snapshot/metadata", ml=True)
        snapshot_keys = ("dataset_version", "as_of_trading_date", "sha256")
        if any(not before.get(k) for k in snapshot_keys):
            raise HTTPException(502, "ML 입력 스냅샷의 버전·기준일·해시를 확인할 수 없습니다.")
        values = body.shocks.model_dump()
        shocks = {"shock_fx_pct": values["fx_pct"], "shock_us_rate_bp": values["us_rate_bp"],
                  "shock_wti_pct": values["wti_pct"], "shock_vix_points": values["vix_points"]}

        async def asset(p):
            common = {"asset_id": p.asset_id, "model": body.model}
            if horizon != 5:
                common["horizon_trading_days"] = horizon
            stress = await upstream.call(ml_url + "/predict/auto", payload={**common, **shocks}, ml=True)
            base = (stress if not any(shocks.values()) else await upstream.call(
                ml_url + "/predict/auto", payload={**common, **{k: 0 for k in shocks}}, ml=True))
            signature = lambda r: tuple(r.get(k) for k in ("package_id", "dataset_version", "feature_as_of_trading_date"))
            if signature(base) != signature(stress):
                raise HTTPException(409, "계산 중 모델 또는 입력 버전이 변경됐습니다. 다시 요청하세요.")
            for result in (base, stress):
                if result.get("asset_id") != p.asset_id or result.get("model") != body.model:
                    raise HTTPException(502, "모델 응답의 종목 또는 모델이 요청과 다릅니다.")
                if result.get("horizon_trading_days", 5) != horizon:
                    raise HTTPException(502, "모델 응답의 거래일이 요청과 다릅니다.")
                required=("package_id", "dataset_version", "feature_as_of_trading_date",
                    point_field, lower_field, upper_field)
                if any(result.get(k) is None for k in required):
                    raise HTTPException(502, "모델 응답의 필수값이 누락됐습니다.")
            c, b = (simple_return(x[point_field]) for x in (stress, base))
            lo, hi = (simple_return(stress[k]) for k in (lower_field, upper_field))
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
        after = await upstream.call(ml_url + "/snapshot/metadata", ml=True)
        if any(before.get(k) != after.get(k) for k in snapshot_keys):
            raise HTTPException(409, "계산 중 ML 입력 스냅샷이 갱신됐습니다. 다시 요청하세요.")
        if any(r["model_output"]["feature_as_of_trading_date"] != before["as_of_trading_date"]
               or r["model_output"]["dataset_version"] != before["dataset_version"]
               or r["model_output"]["package_id"] != metadata.get("package_id") for r in rows):
            raise HTTPException(409, "ML 계산 결과와 입력 스냅샷의 기준이 다릅니다.")
        result = {"api_version": "1.1", "model": body.model, "horizon_trading_days": horizon,
                "shocks": values, "assets": rows,
                "portfolio_hypothetical_pnl_krw": sum(r["hypothetical_pnl_krw"] for r in rows),
                "portfolio_shock_incremental_pnl_krw": sum(r["shock_incremental_pnl_krw"] for r in rows),
                "research_only": True, "production_approval": "NOT_APPROVED",
                "interval_note": "종목별 모델 구간입니다. 포트폴리오 손실 한도나 포함률을 보장하지 않습니다."}
        market, market_error = None, None
        market_url = os.environ.get("MARKET_STATE_URL", "").rstrip("/")
        if market_url:
            try:
                market = await asyncio.wait_for(upstream.call(market_url + "/current"), timeout=4)
                if not isinstance(market, dict) or not isinstance(market.get("snapshot"), dict):
                    market, market_error = None, "invalid_market_snapshot"
            except (HTTPException, asyncio.TimeoutError):
                market_error = "market_state_unavailable"
        else:
            market_error = "market_state_not_configured"
        return attach_context(result, before, market, market_error)

    @app.post("/api/stress/analyze")
    async def analyze(body: AnalyzeRequest, request: Request):
        if not ml_url:
            raise HTTPException(503, "ML 주소가 설정되지 않았습니다.")
        upstream = request.app.state.upstream

        async def calculate():
            out = await compute(upstream, body)
            await persist(request, body, out)
            return out
        try:
            return await asyncio.wait_for(calculate(), timeout=35)
        except asyncio.TimeoutError as exc:
            raise HTTPException(504, "분석 시간이 초과됐습니다. 잠시 후 다시 요청하세요.") from exc

    # ------------------------------------------------------------------ 정시 회의 (2026-11-18)
    # 보유 종목을 저장한 사용자는 그날 처음 열리는 정시 회의 때 한 번 ML을 돌려 s-{날짜}-{사용자} 결과로 저장하고,
    # 같은 날 다른 시간대 회의는 그 결과를 다시 씁니다(일별 모델이라 하루 안에서는 값이 같음).
    # 충격 조건은 사용자가 웹에서 마지막으로 직접 돌린 분석의 조건, 없으면 0(무충격).
    async def latest_prices(upstream) -> dict:
        url = os.environ.get("QUOTE_API_URL", "").rstrip("/")
        if not url:
            return {}
        try:
            data = await asyncio.wait_for(upstream.call(url + "/latest"), timeout=6)
        except Exception:
            return {}
        out = {}
        for q in (data or {}).get("quotes") or []:
            try:
                price = float(q["price"])
                if q.get("is_mock") is False and q.get("asset_id") and math.isfinite(price) and price > 0:
                    out[q["asset_id"]] = price
            except (TypeError, ValueError, KeyError):
                continue
        return out

    async def daily_run(upstream, deps, user_id: str, day: str, prices: dict, supported: set) -> tuple[str, str]:
        run_id = f"s-{day}-{_key(user_id)}"
        if await deps.reader.stress_run(run_id):
            return run_id, "reused"
        positions = []
        for h in await deps.reader.holdings(user_id):
            if h["asset_id"] not in supported:
                continue
            shares, price = h.get("shares"), prices.get(h["asset_id"])
            value = float(shares) * price if shares and price else float(h["amount_krw"])
            positions.append({"asset_id": h["asset_id"], "value_krw": round(value)})
        positions = sorted(positions, key=lambda p: -p["value_krw"])[:20]
        if not positions:
            raise ValueError("ML이 지원하는 보유 종목이 없습니다.")
        last = await deps.reader.last_user_run(user_id)
        req = (last or {}).get("request") or {}
        body = AnalyzeRequest(positions=positions, shocks=req.get("shocks") or {}, model=req.get("model") or "catboost")
        out = await asyncio.wait_for(compute(upstream, body), timeout=35)
        out["ai_context"]["stress_run"]["run_id"] = run_id
        request_doc = {**body.model_dump(), "scheduled_day": day,
                       "shocks_from_run_id": last["run_id"] if last else None}
        # 장중 스냅샷은 저장하지 않습니다 → 실행기가 회의 시각의 최신 장중 상태를 붙입니다.
        await deps.reader.save_stress_run(run_id, user_id, request_doc, out["ai_context"]["stress_run"], None)
        return run_id, "computed"

    @app.post("/internal/scheduled-debates", status_code=202)
    async def scheduled_debates(body: ScheduleBody, request: Request, x_scheduler_key: Optional[str] = Header(None)):
        deps = request.app.state.deps
        if not deps.scheduler_key or not x_scheduler_key or not hmac.compare_digest(x_scheduler_key, deps.scheduler_key):
            raise HTTPException(403, "정시 회의 요청은 스케줄러만 보낼 수 있습니다.")
        upstream = request.app.state.upstream
        day = datetime.now(KST).strftime("%Y%m%d")
        users = await _schedule_targets(deps)
        holders = [u for u in users if u["source"] == "holding"]
        prices, supported = {}, set()
        if holders and ml_url:
            prices = await latest_prices(upstream)
            try:
                supported = set((await upstream.call(ml_url + "/metadata", ml=True))["supported_assets"])
            except Exception as exc:
                log.warning("정시 회의: ML 메타데이터 조회 실패 %r", exc)
        gate = asyncio.Semaphore(int(os.environ.get("SCHEDULE_ML_CONCURRENCY", "4")))
        stats = {"computed": 0, "reused": 0, "fallback": 0}

        async def one(u):
            run_id = u.get("run_id") or deps.default_run_id
            if u["source"] == "holding":
                try:
                    if not supported:
                        raise RuntimeError("ML을 사용할 수 없습니다.")
                    async with gate:
                        run_id, how = await daily_run(upstream, deps, u["user_id"], day, prices, supported)
                    stats[how] += 1
                except Exception as exc:
                    # ML 실패: 사용자의 마지막 분석 결과로 회의(없으면 기본 결과). 다음 시간대에 다시 계산을 시도합니다.
                    log.warning("정시 회의: %s ML 계산 실패, 이전 결과 사용 %r", _key(u["user_id"]), exc)
                    last = await deps.reader.last_user_run(u["user_id"])
                    run_id = last["run_id"] if last else deps.default_run_id
                    stats["fallback"] += 1
            debate_id = f"s-{day}-{body.slot}-{_key(u['user_id'])}"
            await _send(deps, _start_request(debate_id, u["user_id"], "scheduled", body.slot, run_id, None))
            return debate_id

        results = await asyncio.gather(*(one(u) for u in users), return_exceptions=True)
        ids = [r for r in results if isinstance(r, str)]
        failed = len(results) - len(ids)
        if failed and not ids:
            raise HTTPException(503, "정시 회의 요청을 하나도 접수하지 못했습니다.")
        return {"slot": body.slot, "date_kst": day, "users": len(users), "accepted": len(ids), "failed": failed,
                "holding_users": len(holders), "capped": len(users) >= deps.max_users, "ml_runs": stats}

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

    from market_regime_routes import router as market_regime_router
    app.include_router(market_regime_router)
    return app


app = create_app()
