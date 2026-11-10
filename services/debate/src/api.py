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
  GET  /healthz

사용자 식별: 지금은 웹앱이 보내는 `X-User-Id` 헤더를 그대로 믿습니다(웹앱 로그인 방식이 정해지면 교체).
중복 방지: 웹앱이 `Idempotency-Key` 헤더를 보내면 같은 키의 재요청은 같은 debate_id·request_id가 되어
          Service Bus 중복 감지가 하나로 막습니다.
정시 회의: 사용자마다 자기 보유 종목 기준의 토론을 따로 엽니다(본인만 조회).
          예약 작업(schedule.py)이 `X-Scheduler-Key`와 함께 POST /scheduled-debates {"slot": "0830"}을 부르면,
          최근 SCHEDULE_ACTIVE_DAYS일 안에 토론을 연 사용자마다 그 사용자의 마지막 run_id로 토론을 큐에 넣습니다.
          (포트폴리오 저장소가 생기면 대상 사용자와 run_id를 그쪽에서 가져오도록 바꿉니다.)

환경변수: SERVICEBUS_NAMESPACE, SERVICEBUS_QUEUE(기본 debate-requests), AZURE_CLIENT_ID,
          PG_HOST, PG_DB(기본 postgres), PG_USER(API 관리 ID 이름),
          WPS_ENDPOINT, WPS_HUB(기본 debate), WPS_TOKEN_MINUTES(기본 60),
          DEFAULT_RUN_ID(기본 stress_run), SCHEDULER_KEY(정시 회의용, 없으면 거부),
          SCHEDULE_ACTIVE_DAYS(기본 7), SCHEDULE_MAX_USERS(기본 50, 시간대마다 모델 비용 상한),
          CORS_ORIGINS(쉼표 구분, 기본 없음)
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Literal, Optional, Protocol
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse
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


class TokenIssuer(Protocol):
    async def token(self, user_id: str, group: str) -> dict: ...


class Deps:
    def __init__(self, queue: Queue, reader: Reader, tokens: TokenIssuer, *, default_run_id: str = "stress_run",
                 scheduler_key: Optional[str] = None, active_days: int = 7, max_users: int = 50):
        self.queue, self.reader, self.tokens = queue, reader, tokens
        self.default_run_id = default_run_id
        self.scheduler_key = scheduler_key
        self.active_days, self.max_users = active_days, max_users


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
class StartBody(BaseModel):
    run_id: Optional[str] = Field(None, description="Stress Engine 결과 ID. 없으면 DEFAULT_RUN_ID")
    snapshot_id: Optional[str] = Field(None, description="시장 상태 스냅샷 ID. 없으면 실행기가 접수 시점 최신값으로 고정")


class ScheduleBody(BaseModel):
    slot: Literal["0830", "1300", "1540"]


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
        yield
        for close in closers:
            await close()

    app = FastAPI(title="whatif debate API", version="1.0", lifespan=lifespan, default_response_class=UTF8JSONResponse)
    app.state.deps = deps
    origins = [o for o in os.environ.get("CORS_ORIGINS", "").split(",") if o]
    if origins:
        from fastapi.middleware.cors import CORSMiddleware
        app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET", "POST"],
                           allow_headers=["Content-Type", "X-User-Id", "Idempotency-Key"])

    def get_deps(request: Request) -> Deps:
        return request.app.state.deps

    def user(x_user_id: str = Header(..., min_length=1, max_length=200, description="웹앱 사용자 ID")) -> str:
        return x_user_id

    async def owned(debate_id: str, user_id: str, d: Deps) -> dict:
        row = await d.reader.debate(debate_id)
        if row is None:
            raise HTTPException(409, "토론이 아직 접수 처리 중입니다. 잠시 후 다시 시도하세요.")
        if row["user_id"] != user_id:
            raise HTTPException(404, "토론을 찾을 수 없습니다.")
        return row

    @app.get("/healthz")
    async def healthz():
        return {"status": "ok"}

    @app.post("/debates", status_code=202)
    async def start(body: StartBody, user_id: str = Depends(user), d: Deps = Depends(get_deps),
                    idempotency_key: Optional[str] = Header(None, max_length=200)):
        if user_id == SYSTEM_USER:
            raise HTTPException(403, "예약된 사용자 ID입니다.")
        debate_id = "d-" + (_key(user_id, idempotency_key) if idempotency_key else uuid.uuid4().hex[:16])
        req = _start_request(debate_id, user_id, "user", None, body.run_id or d.default_run_id, body.snapshot_id)
        await _send(d, req)
        return {"debate_id": debate_id, "request_id": req["request_id"], "status": "accepted",
                "pubsub": await d.tokens.token(user_id, c.group_name(debate_id))}

    @app.get("/debates")
    async def my_debates(limit: int = Query(30, ge=1, le=100), user_id: str = Depends(user),
                         d: Deps = Depends(get_deps)):
        rows = await d.reader.list_debates(user_id, limit)
        return {"debates": [{k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in r.items()}
                            for r in rows]}

    @app.post("/scheduled-debates", status_code=202)
    async def scheduled(body: ScheduleBody, d: Deps = Depends(get_deps),
                        x_scheduler_key: Optional[str] = Header(None)):
        if not d.scheduler_key or not x_scheduler_key or not hmac.compare_digest(x_scheduler_key, d.scheduler_key):
            raise HTTPException(403, "정시 회의 요청은 스케줄러만 보낼 수 있습니다.")
        day = f"{_now().astimezone(KST):%Y%m%d}"
        users = await d.reader.active_users(d.active_days, d.max_users)
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
                "capped": len(users) >= d.max_users}

    @app.post("/debates/{debate_id}/questions", status_code=202)
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

    @app.get("/debates/{debate_id}")
    async def status(debate_id: str, user_id: str = Depends(user), d: Deps = Depends(get_deps)):
        row = await owned(debate_id, user_id, d)
        return {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in row.items() if k != "user_id"}

    @app.get("/debates/{debate_id}/negotiate")
    async def negotiate(debate_id: str, user_id: str = Depends(user), d: Deps = Depends(get_deps)):
        await owned(debate_id, user_id, d)
        return await d.tokens.token(user_id, c.group_name(debate_id))

    @app.get("/debates/{debate_id}/events")
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

    return app


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
                max_users=int(os.environ.get("SCHEDULE_MAX_USERS", "50")))
    log.info("debate API 시작")
    return deps, [queue.close, tokens.close, store.pool.close, aio_cred.close]


app = create_app()
