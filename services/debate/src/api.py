"""토론 요청 API (ca-debateapi-whatif-dev). 토론 실행기와 같은 이미지, 실행 명령만 다릅니다.

    uvicorn api:app --host 0.0.0.0 --port 8000

웹앱이 사용자 요청을 Service Bus `debate-requests` 큐에 넣고, 화면이 토론 이벤트를 받을 수 있게 합니다.
토론 진행은 하지 않습니다(실행기 담당). DB는 읽기만 합니다.

  POST /debates                          토론 시작 → 202 {debate_id, pubsub}
  GET  /debates                          내 토론 목록 (최신순, 회의록 화면)
  POST /scheduled-debates                정시 회의: 대상 사용자마다 토론 하나씩 (스케줄러 전용)
  POST /debates/{debate_id}/questions    사용자 질문 → 202 {request_id, question_id}
  GET  /debates/{debate_id}/negotiate    Web PubSub 재접속 토큰 (debate-{id} 그룹 자동 참가)
  GET  /debates/{debate_id}/events       놓친 이벤트 다시 받기 (?after_seq=N)
  GET  /debates/{debate_id}              토론 상태
  GET  /me                               로그인 사용자
  GET  /me/holdings                      내 보유 종목
  PUT  /me/holdings                      내 보유 종목 전체 저장 (목록을 통째로 바꿈)
  POST /me/holdings                      종목 1건 추가 (동일 종목은 수량·매입원가 합산)
  DELETE /me/holdings/{asset_id}         내 보유 종목 1개 삭제
  GET  /healthz

모든 경로는 `/api` 접두사로도 열려 있습니다(예: /api/debates). Static Web Apps(Standard)에 이 앱을 연결하면
웹앱의 /api/* 요청이 같은 경로로 전달됩니다.

사용자 식별: Static Web Apps 로그인 뒤 SWA가 붙여 주는 `X-MS-CLIENT-PRINCIPAL` 헤더(base64 JSON)에서
          `{identityProvider}:{userId}`를 user_id로 씁니다. 연결된 앱은 SWA를 거친 요청만 받으므로 이 헤더를
          사용자가 꾸밀 수 없습니다. 연결 전 개발·테스트에서는 ALLOW_DEV_USER_HEADER=true일 때만
          `X-User-Id` 헤더를 받습니다(운영에서는 끄세요).
중복 방지: 웹앱이 `Idempotency-Key` 헤더를 보내면 같은 키의 재요청은 같은 debate_id·request_id가 되어
          Service Bus 중복 감지가 하나로 막습니다.
정시 회의: 사용자마다 자기 보유 종목 기준의 토론을 따로 엽니다(본인만 조회).
          예약 작업(schedule.py)이 `X-Scheduler-Key`와 함께 POST /scheduled-debates {"slot": "0830"}을 부르면,
          대상은 ① 보유 종목을 저장한 사용자(user_holding) ② 최근 SCHEDULE_ACTIVE_DAYS일 안에 토론을 연
          사용자 순서로 최대 SCHEDULE_MAX_USERS명입니다. run_id는 Stress Engine이 연결되기 전까지
          ①은 DEFAULT_RUN_ID, ②는 그 사용자의 마지막 run_id입니다.
          (Stress Engine이 생기면 ①의 보유 종목으로 Stress Engine을 돌려 받은 run_id를 넣도록 바꿉니다.)

환경변수: SERVICEBUS_NAMESPACE, SERVICEBUS_QUEUE(기본 debate-requests), AZURE_CLIENT_ID,
          PG_HOST, PG_DB(기본 postgres), PG_USER(API 관리 ID 이름),
          WPS_ENDPOINT, WPS_HUB(기본 debate), WPS_TOKEN_MINUTES(기본 60),
          DEFAULT_RUN_ID(기본 stress_run), SCHEDULER_KEY(정시 회의용, 없으면 거부),
          SCHEDULE_ACTIVE_DAYS(기본 7), SCHEDULE_MAX_USERS(기본 50, 시간대마다 모델 비용 상한),
          CORS_ORIGINS(쉼표 구분, 기본 없음, SWA 연결 시 불필요),
          ALLOW_DEV_USER_HEADER(기본 false), HOLDINGS_MAX(기본 200),
          ALLOWED_ASSETS(쉼표 구분 종목코드, 있으면 이 종목만 저장 허용. 예: ML 지원 종목),
          DART_API_KEY(OpenDART 인증키, 서버에서만 사용)
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import logging
import os
import re
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Literal, Optional, Protocol
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

import contracts as c

log = logging.getLogger("debate.api")
KST = ZoneInfo("Asia/Seoul")


# ---------------------------------------------------------------------------
# 바깥 의존성 (테스트에서 바꿔 끼움)
# ---------------------------------------------------------------------------

class UTF8JSONResponse(JSONResponse):
    """charset을 명시합니다. Windows PowerShell 5.1은 charset이 없으면 한글을 UTF-8로 읽지 않습니다."""
    media_type = "application/json; charset=utf-8"

class Queue(Protocol):
    async def send(self, body: dict, *, session_id: str, message_id: str) -> None: ...


class Reader(Protocol):
    async def debate(self, debate_id: str) -> Optional[dict]: ...
    async def events(self, debate_id: str, after_seq: int, limit: int) -> list[dict]: ...
    async def list_debates(self, user_id: str, limit: int) -> list[dict]: ...
    async def active_users(self, days: int, limit: int) -> list[dict]: ...
    async def holdings(self, user_id: str) -> list[dict]: ...
    async def replace_holdings(self, user_id: str, items: list[dict]) -> None: ...
    async def add_holding(self, user_id: str, item: dict) -> bool: ...
    async def delete_holding(self, user_id: str, asset_id: str) -> bool: ...
    async def holding_users(self, limit: int) -> list[str]: ...
    async def save_stress_run(self, run_id: str, user_id: str, request: dict, result: dict,
                              market_snapshot: Optional[dict]) -> None: ...
    async def stress_run(self, run_id: str) -> Optional[dict]: ...
    async def last_user_run(self, user_id: str) -> Optional[dict]: ...


class TokenIssuer(Protocol):
    async def token(self, user_id: str, group: str) -> dict: ...


class Deps:
    def __init__(self, queue: Queue, reader: Reader, tokens: TokenIssuer, *, default_run_id: str = "stress_run",
                 scheduler_key: Optional[str] = None, active_days: int = 7, max_users: int = 50,
                 allow_dev_user_header: bool = False, holdings_max: int = 200,
                 allowed_assets: Optional[set[str]] = None):
        self.queue, self.reader, self.tokens = queue, reader, tokens
        self.default_run_id = default_run_id
        self.scheduler_key = scheduler_key
        self.active_days, self.max_users = active_days, max_users
        self.allow_dev_user_header = allow_dev_user_header
        self.holdings_max = holdings_max
        self.allowed_assets = allowed_assets


class ServiceBusQueue:
    def __init__(self, namespace: str, queue: str, credential):
        from azure.servicebus.aio import ServiceBusClient
        self.client = ServiceBusClient(namespace, credential)
        self.sender = self.client.get_queue_sender(queue)

    async def send(self, body, *, session_id, message_id):
        from azure.servicebus import ServiceBusMessage
        await self.sender.send_messages(ServiceBusMessage(
            json.dumps(body, ensure_ascii=False, default=str), session_id=session_id, message_id=message_id,
            content_type="application/json"))

    async def close(self):
        await self.sender.close()
        await self.client.close()


class PostgresReader:
    def __init__(self, store):
        self.store = store   # store.PostgresStore (연결 풀만 씀)
        self._shares = None  # user_holding.shares 열 존재 여부 (처음 저장할 때 확인)

    async def debate(self, debate_id):
        return await self.store._one(
            "SELECT debate_id, user_id, trigger, scheduled_slot, run_id, snapshot_id, evidence_bundle_id, status, "
            "error, last_seq, created_at, updated_at FROM debate WHERE debate_id=%s", (debate_id,))

    async def events(self, debate_id, after_seq, limit):
        async with self.store.pool.connection() as conn, conn.cursor() as cur:
            await cur.execute("SELECT seq, event_id, type, payload, created_at FROM debate_event "
                              "WHERE debate_id=%s AND seq>%s ORDER BY seq LIMIT %s", (debate_id, after_seq, limit))
            cols = [d.name for d in cur.description]
            return [dict(zip(cols, r)) for r in await cur.fetchall()]

    async def _all(self, sql, params):
        async with self.store.pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(sql, params)
            cols = [d.name for d in cur.description]
            return [dict(zip(cols, r)) for r in await cur.fetchall()]

    async def list_debates(self, user_id, limit):
        return await self._all(
            "SELECT debate_id, trigger, scheduled_slot, run_id, snapshot_id, status, created_at, updated_at "
            "FROM debate WHERE user_id=%s ORDER BY created_at DESC LIMIT %s", (user_id, limit))

    async def active_users(self, days, limit):
        # 최근 사용자와 그 사용자가 마지막으로 직접 연 토론의 run_id (정시 회의 결과는 제외)
        return await self._all(
            "SELECT DISTINCT ON (user_id) user_id, run_id, created_at FROM debate "
            "WHERE trigger='user' AND created_at >= now() - make_interval(days => %s) "
            "ORDER BY user_id, created_at DESC LIMIT %s", (days, limit))


    async def save_stress_run(self, run_id, user_id, request, result, market_snapshot):
        from psycopg.types.json import Jsonb
        async with self.store.pool.connection() as conn:
            await conn.execute(
                "INSERT INTO stress_run (run_id, user_id, request, result, market_snapshot) "
                "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (run_id) DO NOTHING",
                (run_id, user_id, Jsonb(request), Jsonb(result),
                 None if market_snapshot is None else Jsonb(market_snapshot)))

    async def stress_run(self, run_id):
        rows = await self._all("SELECT run_id, user_id, created_at FROM stress_run WHERE run_id=%s", (run_id,))
        return rows[0] if rows else None

    async def last_user_run(self, user_id):
        """사용자가 웹에서 마지막으로 직접 돌린 분석(a-...)의 run_id와 요청(충격 조건). 정시 회의가 이 조건을 씁니다."""
        rows = await self._all("SELECT run_id, request, created_at FROM stress_run "
                               "WHERE user_id=%s AND run_id LIKE 'a-%%' ORDER BY created_at DESC LIMIT 1", (user_id,))
        return rows[0] if rows else None

    async def holdings(self, user_id):
        try:
            return await self._all("SELECT asset_id, amount_krw, shares, avg_purchase_price_krw, updated_at FROM user_holding "
                                   "WHERE user_id=%s ORDER BY amount_krw DESC, asset_id", (user_id,))
        except Exception as e:   # 이전 스키마와 호환
            if "avg_purchase_price_krw" not in str(e) and "shares" not in str(e):
                raise
            try:
                return await self._all("SELECT asset_id, amount_krw, shares, updated_at FROM user_holding "
                                       "WHERE user_id=%s ORDER BY amount_krw DESC, asset_id", (user_id,))
            except Exception as inner:
                if "shares" not in str(inner):
                    raise
                return await self._all("SELECT asset_id, amount_krw, updated_at FROM user_holding "
                                       "WHERE user_id=%s ORDER BY amount_krw DESC, asset_id", (user_id,))

    async def add_holding(self, user_id, item):
        async with self.store.pool.connection() as conn:
            async with conn.cursor() as cur:
                # 원자적 합산: 동시 요청도 기존 주수와 매입원가를 잃지 않습니다.
                await cur.execute(
                    "INSERT INTO user_holding (user_id, asset_id, amount_krw, shares, avg_purchase_price_krw) "
                    "VALUES (%s, %s, %s, %s, %s) "
                    "ON CONFLICT (user_id, asset_id) DO UPDATE SET "
                    "shares = user_holding.shares + EXCLUDED.shares, "
                    "avg_purchase_price_krw = (user_holding.shares * user_holding.avg_purchase_price_krw + "
                    "EXCLUDED.shares * EXCLUDED.avg_purchase_price_krw) / (user_holding.shares + EXCLUDED.shares), "
                    "amount_krw = (user_holding.shares + EXCLUDED.shares) * %s, updated_at = now() "
                    "WHERE user_holding.shares IS NOT NULL AND user_holding.avg_purchase_price_krw IS NOT NULL "
                    "RETURNING asset_id",
                    (user_id, item["asset_id"], item["amount_krw"], item["shares"],
                     item["avg_purchase_price_krw"], item["current_price_krw"]))
                return await cur.fetchone() is not None

    async def delete_holding(self, user_id, asset_id):
        async with self.store.pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("DELETE FROM user_holding WHERE user_id=%s AND asset_id=%s RETURNING asset_id", (user_id, asset_id))
                return await cur.fetchone() is not None

    async def replace_holdings(self, user_id, items):
        # 한 트랜잭션: 기존 목록을 지우고 새 목록을 넣음 (중간 상태가 보이지 않음)
        async with self.store.pool.connection() as conn:
            async with conn.transaction():
                async with conn.cursor() as cur:
                    await cur.execute("DELETE FROM user_holding WHERE user_id=%s", (user_id,))
                    if items:
                        try:
                            async with conn.transaction():
                                await cur.executemany(
                                    "INSERT INTO user_holding (user_id, asset_id, amount_krw, shares, avg_purchase_price_krw) VALUES (%s, %s, %s, %s, %s)",
                                    [(user_id, it["asset_id"], it["amount_krw"], it.get("shares"), it.get("avg_purchase_price_krw")) for it in items])
                            self._shares = True
                            return
                        except Exception as e:
                            if "avg_purchase_price_krw" not in str(e) and "shares" not in str(e):
                                raise
                    if items and self._shares is not False:
                        try:
                            async with conn.transaction():   # savepoint: shares 열이 없으면 이 부분만 되돌림
                                await cur.executemany(
                                    "INSERT INTO user_holding (user_id, asset_id, amount_krw, shares) VALUES (%s, %s, %s, %s)",
                                    [(user_id, it["asset_id"], it["amount_krw"], it.get("shares")) for it in items])
                            self._shares = True
                            return
                        except Exception as e:
                            if "shares" not in str(e):
                                raise
                            self._shares = False
                    if items:
                        await cur.executemany(
                            "INSERT INTO user_holding (user_id, asset_id, amount_krw) VALUES (%s, %s, %s)",
                            [(user_id, it["asset_id"], it["amount_krw"]) for it in items])

    async def holding_users(self, limit):
        rows = await self._all("SELECT user_id FROM user_holding GROUP BY user_id "
                               "ORDER BY max(updated_at) DESC LIMIT %s", (limit,))
        return [r["user_id"] for r in rows]


class WebPubSubTokens:
    def __init__(self, endpoint: str, hub: str, credential, minutes: int = 60):
        from azure.messaging.webpubsubservice.aio import WebPubSubServiceClient
        self.client = WebPubSubServiceClient(endpoint=endpoint, hub=hub, credential=credential)
        self.minutes = minutes

    async def token(self, user_id, group):
        # 받기 전용: 그룹 자동 참가만. 클라이언트가 그룹에 보내는 권한(sendToGroup)은 주지 않음
        t = await self.client.get_client_access_token(user_id=user_id, groups=[group],
                                                      minutes_to_expire=self.minutes)
        return {"url": t["url"], "group": group, "expires_in_minutes": self.minutes}

    async def close(self):
        await self.client.close()


# ---------------------------------------------------------------------------
# 요청 본문
# ---------------------------------------------------------------------------
class StartBody(c.StartDebateBody):
    pass


class ScheduleBody(BaseModel):
    slot: Literal["0830", "1300", "1540"]


_ASSET_RE = re.compile(r"^[0-9A-Z]{6}$")


class HoldingItem(BaseModel):
    asset_id: str = Field(description="종목코드 6자리 (예: 005930)")
    amount_krw: float = Field(gt=0, le=1e13, description="보유 금액(원)")
    shares: Optional[int] = Field(None, gt=0, le=10**10, description="보유 주식 수. 있으면 정시 회의 때 현재가 × 주 수로 금액을 다시 계산")
    avg_purchase_price_krw: Optional[float] = Field(None, gt=0, le=10**10)


class HoldingsBody(BaseModel):
    holdings: list[HoldingItem] = Field(max_length=1000)


class HoldingCreate(BaseModel):
    asset_id: str = Field(pattern=r"^\d{6}$")
    shares: int = Field(gt=0, le=10**10)
    avg_purchase_price_krw: int = Field(gt=0, le=10**10)
    current_price_krw: int = Field(gt=0, le=10**10)


class QuestionBody(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    target_roles: list[Literal["macro", "market", "risk", "portfolio"]] = Field(min_length=1)
    reference_message_id: Optional[str] = None


def _key(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]


def _now():
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# 앱
# ---------------------------------------------------------------------------
def create_app(deps: Optional[Deps] = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if app.state.deps is None:
            app.state.deps, closers = await _azure_deps()
        else:
            closers = []
        app.state.opendart = None
        dart_key = os.environ.get("DART_API_KEY", "").strip()
        if dart_key:
            from open_dart import OpenDartClient
            app.state.opendart = OpenDartClient(dart_key)
            closers.append(app.state.opendart.close)
        yield
        for close in closers:
            await close()

    app = FastAPI(title="whatif debate API", version="1.0", lifespan=lifespan, default_response_class=UTF8JSONResponse)
    app.state.deps = deps
    app.state.opendart = None
    origins = [o for o in os.environ.get("CORS_ORIGINS", "").split(",") if o]
    if origins:
        from fastapi.middleware.cors import CORSMiddleware
        app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET", "POST", "PUT", "DELETE"],
                           allow_headers=["Content-Type", "X-User-Id", "Idempotency-Key"])

    r = APIRouter()

    def get_deps(request: Request) -> Deps:
        return request.app.state.deps

    def principal(request: Request, d: Deps = Depends(get_deps)) -> dict:
        """SWA 로그인 사용자. 개발 모드에서만 X-User-Id 허용."""
        p = parse_client_principal(request.headers.get("x-ms-client-principal"))
        if p:
            return p
        dev = request.headers.get("x-user-id")
        if d.allow_dev_user_header and dev and 0 < len(dev) <= 200:
            return {"user_id": dev, "provider": "dev", "name": dev}
        raise HTTPException(401, "로그인이 필요합니다.")

    def user(p: dict = Depends(principal)) -> str:
        return p["user_id"]

    def opendart(request: Request):
        client = request.app.state.opendart
        if client is None:
            raise HTTPException(503, "DART 연결 설정이 아직 완료되지 않았습니다.")
        return client

    def dart_error(exc):
        raise HTTPException(exc.status_code, exc.message) from exc

    async def owned(debate_id: str, user_id: str, d: Deps) -> dict:
        row = await d.reader.debate(debate_id)
        if row is None:
            raise HTTPException(409, "토론이 아직 접수 처리 중입니다. 잠시 후 다시 시도하세요.")
        if row["user_id"] != user_id:
            raise HTTPException(404, "토론을 찾을 수 없습니다.")
        return row

    @r.get("/healthz")
    async def healthz():
        return {"status": "ok"}

    @r.get("/news/latest")
    async def news_latest(topic: Literal["politics", "economy", "society"] = "economy",
                          _user_id: str = Depends(user)):
        from news_feed import latest
        try:
            return await latest(topic)
        except RuntimeError as exc:
            raise HTTPException(502, str(exc)) from exc

    @r.get("/news/company")
    async def news_company(company: str = Query(..., min_length=2, max_length=40),
                           _user_id: str = Depends(user)):
        from company_news import latest
        try:
            return await latest(company)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(502, str(exc)) from exc

    @r.get("/dart/companies")
    async def dart_companies(q: str = Query(..., min_length=2, max_length=100),
                             _user_id: str = Depends(user), client=Depends(opendart)):
        from open_dart import OpenDartError
        try:
            companies = await client.search_companies(q)
        except OpenDartError as exc:
            dart_error(exc)
        return {"status": "ok", "query": q, "companies": companies}

    @r.get("/dart/disclosures")
    async def dart_disclosures(corp_code: str = Query(..., pattern=r"^\d{8}$"),
                               bgn_de: Optional[str] = Query(None, pattern=r"^\d{8}$"),
                               end_de: Optional[str] = Query(None, pattern=r"^\d{8}$"),
                               pblntf_ty: Optional[str] = Query(None),
                               page: int = Query(1, ge=1, le=100000),
                               _user_id: str = Depends(user), client=Depends(opendart)):
        from open_dart import PUBLICATION_TYPES, OpenDartError, default_window
        begin, end = default_window()
        begin, end = bgn_de or begin, end_de or end
        try:
            datetime.strptime(begin, "%Y%m%d")
            datetime.strptime(end, "%Y%m%d")
        except ValueError as exc:
            raise HTTPException(422, "조회 날짜가 실제 달력 날짜인지 확인해 주세요.") from exc
        if begin > end:
            raise HTTPException(422, "조회 시작일은 종료일보다 늦을 수 없습니다.")
        if pblntf_ty and pblntf_ty not in PUBLICATION_TYPES:
            raise HTTPException(422, "공시 유형 값이 올바르지 않습니다.")
        try:
            body = await client.disclosures(corp_code=corp_code, begin=begin, end=end,
                                            publication_type=pblntf_ty or "", page=page)
        except OpenDartError as exc:
            dart_error(exc)
        return {"status": "ok", "window": {"from": begin, "to": end},
                "page": page, "total_count": body.get("total_count", "0"),
                "total_page": body.get("total_page", "0"), "list": body.get("list") or []}

    @r.get("/dart/detail/{receipt_no}")
    async def dart_major_detail(receipt_no: str,
                                corp_code: str = Query(..., pattern=r"^\d{8}$"),
                                bgn_de: str = Query(..., pattern=r"^\d{8}$"),
                                end_de: str = Query(..., pattern=r"^\d{8}$"),
                                report_name: str = Query(..., min_length=1, max_length=200),
                                _user_id: str = Depends(user), client=Depends(opendart)):
        from open_dart import OpenDartError
        if not re.fullmatch(r"\d{14}", receipt_no):
            raise HTTPException(422, "접수번호는 숫자 14자리여야 합니다.")
        try:
            datetime.strptime(bgn_de, "%Y%m%d")
            datetime.strptime(end_de, "%Y%m%d")
        except ValueError as exc:
            raise HTTPException(422, "조회 날짜가 실제 달력 날짜인지 확인해 주세요.") from exc
        if bgn_de > end_de:
            raise HTTPException(422, "조회 시작일은 종료일보다 늦을 수 없습니다.")
        try:
            return await client.major_detail(corp_code=corp_code, begin=bgn_de, end=end_de,
                                            receipt_no=receipt_no, report_name=report_name)
        except OpenDartError as exc:
            dart_error(exc)

    @r.get("/dart/financials")
    async def dart_financials(corp_code: str = Query(..., pattern=r"^\d{8}$"),
                              bsns_year: str = Query(..., pattern=r"^20\d{2}$"),
                              reprt_code: str = Query(...), fs_div: str = Query("CFS"),
                              _user_id: str = Depends(user), client=Depends(opendart)):
        from open_dart import REPORT_CODES, OpenDartError
        if reprt_code not in REPORT_CODES:
            raise HTTPException(422, "보고서 유형 값이 올바르지 않습니다.")
        if fs_div not in {"CFS", "OFS"}:
            raise HTTPException(422, "재무제표 구분은 연결(CFS) 또는 별도(OFS)여야 합니다.")
        if int(bsns_year) > datetime.now(KST).year:
            raise HTTPException(422, "사업연도는 현재 연도보다 미래일 수 없습니다.")
        try:
            body = await client.financials(corp_code=corp_code, year=bsns_year,
                                           report_code=reprt_code, statement_type=fs_div)
        except OpenDartError as exc:
            dart_error(exc)
        return {"status": "ok", "corp_code": corp_code, "bsns_year": bsns_year,
                "reprt_code": reprt_code, "fs_div": fs_div,
                "list": body.get("list") or [], "message": body.get("message", "")}

    @r.get("/dart/original/{receipt_no}/preview")
    async def dart_original_preview(receipt_no: str, _user_id: str = Depends(user), client=Depends(opendart)):
        from open_dart import OpenDartError
        if not re.fullmatch(r"\d{14}", receipt_no):
            raise HTTPException(422, "접수번호는 숫자 14자리여야 합니다.")
        try:
            text, markup, truncated = await client.original_preview(receipt_no)
        except OpenDartError as exc:
            dart_error(exc)
        return {"status": "ok", "text": text, "html": markup, "truncated": truncated,
                "message": "미리보기 길이 제한에 따라 일부만 표시합니다." if truncated else ""}

    @r.get("/dart/original/{receipt_no}")
    async def dart_original(receipt_no: str, _user_id: str = Depends(user), client=Depends(opendart)):
        from open_dart import OpenDartError
        if not re.fullmatch(r"\d{14}", receipt_no):
            raise HTTPException(422, "접수번호는 숫자 14자리여야 합니다.")
        try:
            content = await client.original(receipt_no)
        except OpenDartError as exc:
            dart_error(exc)
        return Response(content=content, media_type="application/zip",
                        headers={"Content-Disposition": f'attachment; filename="DART_document_{receipt_no}.zip"'})

    @r.get("/dart/xbrl/{receipt_no}")
    async def dart_xbrl(receipt_no: str, reprt_code: str = Query(...),
                        _user_id: str = Depends(user), client=Depends(opendart)):
        from open_dart import REPORT_CODES, OpenDartError
        if not re.fullmatch(r"\d{14}", receipt_no):
            raise HTTPException(422, "접수번호는 숫자 14자리여야 합니다.")
        if reprt_code not in REPORT_CODES:
            raise HTTPException(422, "보고서 유형 값이 올바르지 않습니다.")
        try:
            content = await client.xbrl(receipt_no, reprt_code)
        except OpenDartError as exc:
            dart_error(exc)
        return Response(content=content, media_type="application/zip",
                        headers={"Content-Disposition": f'attachment; filename="DART_XBRL_{receipt_no}.zip"'})

    @r.post("/debates", status_code=202)
    async def start(body: StartBody, user_id: str = Depends(user), d: Deps = Depends(get_deps),
                    idempotency_key: Optional[str] = Header(None, max_length=200)):
        if user_id == SYSTEM_USER:
            raise HTTPException(403, "예약된 사용자 ID입니다.")
        if body.run_id and body.run_id.startswith("a-"):   # 웹 분석 결과는 저장된 본인 것만
            row = await d.reader.stress_run(body.run_id)
            if row is None or row["user_id"] != user_id:
                raise HTTPException(404, "분석 결과를 찾을 수 없습니다. 분석을 다시 실행하세요.")
        debate_id = "d-" + (_key(user_id, idempotency_key) if idempotency_key else uuid.uuid4().hex[:16])
        req = _start_request(debate_id, user_id, "user", None, body.run_id or d.default_run_id, body.snapshot_id)
        req["target_roles"] = list(dict.fromkeys(body.target_roles))
        req["selected_sources"] = [item.model_dump() for item in body.selected_sources]
        c.DebateRequest.model_validate(req)
        await _send(d, req)
        return {"debate_id": debate_id, "request_id": req["request_id"], "status": "accepted",
                "pubsub": await d.tokens.token(user_id, c.group_name(debate_id))}

    @r.get("/debates")
    async def my_debates(limit: int = Query(30, ge=1, le=100), user_id: str = Depends(user),
                         d: Deps = Depends(get_deps)):
        rows = await d.reader.list_debates(user_id, limit)
        return {"debates": [{k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in r.items()}
                            for r in rows]}

    @r.post("/scheduled-debates", status_code=202)
    async def scheduled(body: ScheduleBody, d: Deps = Depends(get_deps),
                        x_scheduler_key: Optional[str] = Header(None)):
        if not d.scheduler_key or not x_scheduler_key or not hmac.compare_digest(x_scheduler_key, d.scheduler_key):
            raise HTTPException(403, "정시 회의 요청은 스케줄러만 보낼 수 있습니다.")
        day = f"{_now().astimezone(KST):%Y%m%d}"
        users = await _schedule_targets(d)
        ids, failed = [], 0
        for u in users:
            # 같은 날·시간대·사용자는 같은 ID → 작업이 재시도돼도 사용자마다 회의 하나
            debate_id = f"s-{day}-{body.slot}-{_key(u['user_id'])}"
            req = _start_request(debate_id, u["user_id"], "scheduled", body.slot, u.get("run_id") or d.default_run_id, None)
            try:
                await _send(d, req)
                ids.append(debate_id)
            except HTTPException:
                failed += 1
        if failed and not ids:
            raise HTTPException(503, "정시 회의 요청을 하나도 접수하지 못했습니다.")
        return {"slot": body.slot, "date_kst": day, "users": len(users), "accepted": len(ids), "failed": failed,
                "holding_users": sum(u["source"] == "holding" for u in users), "capped": len(users) >= d.max_users}

    @r.post("/debates/{debate_id}/questions", status_code=202)
    async def ask(debate_id: str, body: QuestionBody, user_id: str = Depends(user), d: Deps = Depends(get_deps),
                  idempotency_key: Optional[str] = Header(None, max_length=200)):
        row = await owned(debate_id, user_id, d)
        if row["status"] == "failed":
            raise HTTPException(409, "실패한 토론에는 질문할 수 없습니다. 새 토론을 시작하세요.")
        suffix = _key(idempotency_key) if idempotency_key else uuid.uuid4().hex[:16]
        question = {"question_id": "Q-" + suffix[:12], "text": body.text, "target_roles": body.target_roles,
                    "reference_message_id": body.reference_message_id}
        req = {"type": "user_question", "request_id": f"{debate_id}-q-{suffix}", "debate_id": debate_id,
               "user_id": user_id, "trigger": "user", "run_id": row["run_id"], "snapshot_id": row["snapshot_id"],
               "created_at": _now().isoformat(), "question": question}
        c.DebateRequest.model_validate(req)
        await _send(d, req)
        return {"debate_id": debate_id, "request_id": req["request_id"], "question_id": question["question_id"],
                "status": "accepted"}

    @r.get("/debates/{debate_id}")
    async def status(debate_id: str, user_id: str = Depends(user), d: Deps = Depends(get_deps)):
        row = await owned(debate_id, user_id, d)
        return {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in row.items() if k != "user_id"}

    @r.get("/debates/{debate_id}/negotiate")
    async def negotiate(debate_id: str, user_id: str = Depends(user), d: Deps = Depends(get_deps)):
        await owned(debate_id, user_id, d)
        return await d.tokens.token(user_id, c.group_name(debate_id))

    @r.get("/debates/{debate_id}/events")
    async def events(debate_id: str, after_seq: int = Query(0, ge=0), limit: int = Query(200, ge=1, le=500),
                     user_id: str = Depends(user), d: Deps = Depends(get_deps)):
        await owned(debate_id, user_id, d)
        rows = await d.reader.events(debate_id, after_seq, limit)
        # Web PubSub로 보내는 메시지와 같은 모양. 화면은 event_id/seq로 중복을 거릅니다.
        items = [{"schema_version": "1.0", "debate_id": debate_id, "seq": r["seq"], "event_id": r["event_id"],
                  "type": r["type"],
                  "created_at": r["created_at"].isoformat() if hasattr(r["created_at"], "isoformat") else r["created_at"],
                  "payload": r["payload"]} for r in rows]
        return {"debate_id": debate_id, "events": items,
                "next_after_seq": items[-1]["seq"] if items else after_seq}

    @r.get("/me")
    async def me(p: dict = Depends(principal)):
        return p

    @r.get("/me/holdings")
    async def my_holdings(user_id: str = Depends(user), d: Deps = Depends(get_deps)):
        return _holdings_out(await d.reader.holdings(user_id))

    @r.post("/me/holdings", status_code=201)
    async def add_my_holding(body: HoldingCreate, user_id: str = Depends(user), d: Deps = Depends(get_deps)):
        if user_id == SYSTEM_USER:
            raise HTTPException(403, "예약된 사용자 ID입니다.")
        if d.allowed_assets is not None and body.asset_id not in d.allowed_assets:
            raise HTTPException(422, "분석을 지원하지 않는 종목입니다.")
        if body.shares * body.current_price_krw > 1e13:
            raise HTTPException(422, "평가금액 범위를 초과했습니다.")
        existing = await d.reader.holdings(user_id)
        if len(existing) >= d.holdings_max and not any(row["asset_id"] == body.asset_id for row in existing):
            raise HTTPException(422, f"보유 종목은 최대 {d.holdings_max}개까지 저장할 수 있습니다.")
        item = {"asset_id": body.asset_id, "shares": body.shares,
                "avg_purchase_price_krw": body.avg_purchase_price_krw,
                "current_price_krw": body.current_price_krw,
                "amount_krw": body.shares * body.current_price_krw}
        if not await d.reader.add_holding(user_id, item):
            raise HTTPException(409, "기존 보유분에 주수나 평균 매입가가 없어 합산할 수 없습니다. 기존 보유분은 변경하지 않았습니다.")
        return _holdings_out(await d.reader.holdings(user_id))

    @r.delete("/me/holdings/{asset_id}")
    async def remove_my_holding(asset_id: str, user_id: str = Depends(user), d: Deps = Depends(get_deps)):
        if not re.fullmatch(r"\d{6}", asset_id):
            raise HTTPException(422, "종목코드 형식이 아닙니다.")
        if not await d.reader.delete_holding(user_id, asset_id):
            raise HTTPException(404, "보유 목록에서 종목을 찾지 못했습니다.")
        return _holdings_out(await d.reader.holdings(user_id))

    @r.put("/me/holdings")
    async def save_holdings(body: HoldingsBody, user_id: str = Depends(user), d: Deps = Depends(get_deps)):
        if user_id == SYSTEM_USER:
            raise HTTPException(403, "예약된 사용자 ID입니다.")
        items, seen, errors = [], set(), []
        previous = {row["asset_id"]: row for row in await d.reader.holdings(user_id)}
        for i, h in enumerate(body.holdings):
            aid = h.asset_id.strip().upper()
            if not _ASSET_RE.match(aid):
                errors.append(f"{i + 1}번째: 종목코드 형식이 아닙니다 ({h.asset_id})")
            elif aid in seen:
                errors.append(f"{i + 1}번째: 같은 종목이 두 번 있습니다 ({aid})")
            elif d.allowed_assets is not None and aid not in d.allowed_assets:
                errors.append(f"{i + 1}번째: 분석을 지원하지 않는 종목입니다 ({aid})")
            seen.add(aid)
            old = previous.get(aid, {})
            items.append({"asset_id": aid, "amount_krw": round(h.amount_krw),
                          "shares": h.shares if h.shares is not None else old.get("shares"),
                          "avg_purchase_price_krw": h.avg_purchase_price_krw if h.avg_purchase_price_krw is not None else old.get("avg_purchase_price_krw")})
        if len(items) > d.holdings_max:
            errors.append(f"보유 종목은 최대 {d.holdings_max}개까지 저장할 수 있습니다.")
        if errors:
            raise HTTPException(422, {"message": "보유 종목을 저장하지 못했습니다.", "errors": errors[:20]})
        await d.reader.replace_holdings(user_id, items)
        return _holdings_out(await d.reader.holdings(user_id))

    app.include_router(r)
    app.include_router(r, prefix="/api")
    return app


def parse_client_principal(header: Optional[str]) -> Optional[dict]:
    """SWA X-MS-CLIENT-PRINCIPAL(base64 JSON) → {user_id, provider, name, roles}. 형식이 틀리면 None."""
    if not header:
        return None
    try:
        data = json.loads(base64.b64decode(header + "=" * (-len(header) % 4)))
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return None
    provider, uid = data.get("identityProvider"), data.get("userId")
    roles = data.get("userRoles") or []
    if not provider or not uid or "authenticated" not in roles:
        return None
    return {"user_id": f"{provider}:{uid}", "provider": provider, "name": data.get("userDetails"), "roles": roles}


def _holdings_out(rows: list[dict]) -> dict:
    items = [{"asset_id": r["asset_id"], "amount_krw": float(r["amount_krw"]),
              "shares": None if r.get("shares") is None else int(r["shares"]),
              "avg_purchase_price_krw": None if r.get("avg_purchase_price_krw") is None else float(r["avg_purchase_price_krw"]),
              "updated_at": r["updated_at"].isoformat() if hasattr(r.get("updated_at"), "isoformat") else r.get("updated_at")}
             for r in rows]
    return {"holdings": items, "count": len(items), "total_krw": sum(i["amount_krw"] for i in items)}


async def _schedule_targets(d: "Deps") -> list[dict]:
    """정시 회의 대상: 보유 종목 저장 사용자 먼저, 그다음 최근 토론 사용자. 최대 max_users명."""
    out, seen = [], set()
    for uid in await d.reader.holding_users(d.max_users):
        if uid != SYSTEM_USER and uid not in seen:
            seen.add(uid)
            # TODO(Stress Engine): 이 사용자의 보유 종목으로 Stress Engine을 돌려 받은 run_id로 바꿉니다.
            out.append({"user_id": uid, "run_id": d.default_run_id, "source": "holding"})
    if len(out) < d.max_users:
        for u in await d.reader.active_users(d.active_days, d.max_users):
            if u["user_id"] not in seen and len(out) < d.max_users:
                seen.add(u["user_id"])
                out.append({"user_id": u["user_id"], "run_id": u.get("run_id"), "source": "recent"})
    return out


SYSTEM_USER = "system"


def _start_request(debate_id, user_id, trigger, slot, run_id, snapshot_id) -> dict:
    req = {"type": "debate_start", "request_id": f"{debate_id}-start", "debate_id": debate_id, "user_id": user_id,
           "trigger": trigger, "scheduled_slot": slot, "run_id": run_id, "snapshot_id": snapshot_id,
           "created_at": _now().isoformat()}
    c.DebateRequest.model_validate(req)
    return req


async def _send(d: Deps, req: dict) -> None:
    try:
        await d.queue.send(req, session_id=req["debate_id"], message_id=req["request_id"])
    except Exception as e:
        log.exception("큐 전송 실패 %s", req["request_id"])
        raise HTTPException(503, "요청을 접수하지 못했습니다. 잠시 후 다시 시도하세요.") from e


async def _azure_deps():
    from azure.identity import DefaultAzureCredential
    from azure.identity.aio import DefaultAzureCredential as AioCredential
    from store import PostgresStore

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    client_id = os.environ.get("AZURE_CLIENT_ID")
    aio_cred = AioCredential(managed_identity_client_id=client_id)
    store = await PostgresStore.connect(os.environ["PG_HOST"], os.environ.get("PG_DB", "postgres"),
                                        os.environ["PG_USER"], DefaultAzureCredential(managed_identity_client_id=client_id))
    queue = ServiceBusQueue(os.environ["SERVICEBUS_NAMESPACE"], os.environ.get("SERVICEBUS_QUEUE", "debate-requests"),
                            aio_cred)
    tokens = WebPubSubTokens(os.environ["WPS_ENDPOINT"], os.environ.get("WPS_HUB", "debate"), aio_cred,
                             int(os.environ.get("WPS_TOKEN_MINUTES", "60")))
    deps = Deps(queue, PostgresReader(store), tokens, default_run_id=os.environ.get("DEFAULT_RUN_ID", "stress_run"),
                scheduler_key=os.environ.get("SCHEDULER_KEY") or None,
                active_days=int(os.environ.get("SCHEDULE_ACTIVE_DAYS", "7")),
                max_users=int(os.environ.get("SCHEDULE_MAX_USERS", "50")),
                allow_dev_user_header=os.environ.get("ALLOW_DEV_USER_HEADER", "").lower() == "true",
                holdings_max=int(os.environ.get("HOLDINGS_MAX", "200")),
                allowed_assets={a.strip().upper() for a in os.environ["ALLOWED_ASSETS"].split(",") if a.strip()}
                if os.environ.get("ALLOWED_ASSETS") else None)
    if deps.allow_dev_user_header:
        log.warning("ALLOW_DEV_USER_HEADER=true: X-User-Id 헤더를 믿습니다. SWA 연결 후에는 끄세요.")
    log.info("debate API 시작")
    return deps, [queue.close, tokens.close, store.pool.close, aio_cred.close]


app = create_app()
