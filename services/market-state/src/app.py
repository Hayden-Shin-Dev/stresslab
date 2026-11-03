"""whatif 시장 상태 API.

1. 매분 Eventhouse의 market_state_latest()에서 "마지막 저장 as_of - 5분" 이후 스냅샷을 모두 읽습니다.
   시작 직후에는 오늘 장 시작(09:00 KST)부터 읽어 빠진 이력을 채웁니다.
2. 계약 v2 스키마로 검증하고, 같은 스냅샷이나 이전 시각 스냅샷은 버립니다.
3. PostgreSQL에 이력(market_state_snapshot)과 최신값(market_state_latest)을 저장합니다.
   접속은 관리 ID의 Entra 토큰을 사용합니다(비밀번호 없음).
4. 최신값이 앞으로 갔고 이번에 처음 저장됐을 때만 Web PubSub(market_state hub)으로 발행합니다.
   브라우저는 POST /market-state/negotiate로 수신 전용 주소를 받고, 접속 직후 GET /market-state/current로 현재값을 채웁니다.

API는 요청 시 계산하지 않고 저장본을 반환합니다.

환경변수
  KUSTO_QUERY_URI     Eventhouse Query URI
  KUSTO_DATABASE      KQL 데이터베이스 이름(GUID)
  AZURE_CLIENT_ID     사용자 할당 관리 ID의 Client ID
  MARKET_STATE_QUERY  {since} 자리표시가 있는 KQL (기본: market_state_latest() 이력 조회)
  OVERLAP_MINUTES     다시 읽을 겹침 구간 (기본 5)
  POLL_OFFSET_SECONDS 매분 몇 초에 조회할지 (기본 30)
  STALE_AFTER_SECONDS 장중 as_of가 이 시간보다 오래되면 stale 표시 (기본 180)
  SCHEMA_PATH         contracts/realtime/schema.json 경로
  PG_HOST             예: psql-whatif-dev.postgres.database.azure.com (없으면 DB 저장 생략)
  PG_DB               데이터베이스 이름 (기본 postgres)
  PG_USER             Entra 역할 이름 = 관리 ID 이름 (id-marketstate-whatif-dev)
  WPS_ENDPOINT        예: https://wps-whatif-dev.webpubsub.azure.com (없으면 발행 생략)
  WPS_HUB             기본 market_state
  WPS_TOKEN_MINUTES   브라우저 연결 토큰 유효 시간 (기본 60)
  ALLOWED_ORIGINS     CORS 허용 주소, 쉼표 구분 (Static Web Apps 주소)
"""
import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import psycopg
from psycopg.types.json import Jsonb
from azure.identity import DefaultAzureCredential
from azure.kusto.data import ClientRequestProperties, KustoClient, KustoConnectionStringBuilder
from azure.messaging.webpubsubservice import WebPubSubServiceClient
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from jsonschema import Draft202012Validator

log = logging.getLogger("market_state")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
# Azure SDK의 HTTP 요청 로그는 매분 반복되므로 경고 이상만 남깁니다.
logging.getLogger("azure").setLevel(logging.WARNING)

QUERY_URI = os.environ["KUSTO_QUERY_URI"]
DATABASE = os.environ["KUSTO_DATABASE"]
# {since}에는 코드가 만든 UTC 시각만 들어갑니다(외부 입력 없음).
QUERY = os.environ.get("MARKET_STATE_QUERY", """market_state_latest()
| where as_of >= datetime({since})
| order by as_of asc
| take 500
| project snapshot, as_of, computed_at""")
OVERLAP = timedelta(minutes=int(os.environ.get("OVERLAP_MINUTES", "5")))
POLL_OFFSET = int(os.environ.get("POLL_OFFSET_SECONDS", "30"))
STALE_AFTER = int(os.environ.get("STALE_AFTER_SECONDS", "180"))
PG_HOST = os.environ.get("PG_HOST")
PG_DB = os.environ.get("PG_DB", "postgres")
PG_USER = os.environ.get("PG_USER", "id-marketstate-whatif-dev")
PG_SCOPE = "https://ossrdbms-aad.database.windows.net/.default"
WPS_ENDPOINT = os.environ.get("WPS_ENDPOINT")          # 없으면 발행 생략
WPS_HUB = os.environ.get("WPS_HUB", "market_state")
WPS_TOKEN_MINUTES = int(os.environ.get("WPS_TOKEN_MINUTES", "60"))
CALL_TIMEOUT = int(os.environ.get("CALL_TIMEOUT_SECONDS", "40"))   # 외부 호출 하나의 최대 대기
ALLOWED_ORIGINS = [o for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o]
KST = timezone(timedelta(hours=9))

# 계약 스키마의 market_state_snapshot 정의로만 검증합니다.
with open(os.environ.get("SCHEMA_PATH", "schema.json"), encoding="utf-8") as f:
    _schema = json.load(f)
_validator = Draft202012Validator(
    {"$ref": "#/$defs/market_state_snapshot", "$defs": _schema["$defs"]}
)

_credential = DefaultAzureCredential(
    managed_identity_client_id=os.environ.get("AZURE_CLIENT_ID")
)
_kusto = KustoClient(
    KustoConnectionStringBuilder.with_azure_token_credential(QUERY_URI, _credential)
)

_wps = (WebPubSubServiceClient(endpoint=WPS_ENDPOINT, hub=WPS_HUB, credential=_credential)
        if WPS_ENDPOINT else None)

state = {
    "published_id": None,    # Web PubSub으로 마지막 발행한 snapshot_id
    "last_publish_ok": None,
    "last_publish_error": None,
    "snapshot": None,        # 마지막으로 받아들인 스냅샷 (v2 원본 그대로)
    "persisted_id": None,    # PostgreSQL에 저장이 끝난 가장 늦은 snapshot_id
    "persisted_as_of": None, # 그 스냅샷의 as_of (다음 조회 기준)
    "backfilled": 0,         # 지난 스냅샷을 이력에 채운 건수
    "last_poll_at": None,
    "last_poll_ok": None,
    "last_error": None,
    "last_db_ok": None,
    "last_db_error": None,
    "rejected": 0,           # 스키마 불일치·과거 시각으로 버린 건수
}


def _parse_ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


# ---------- Eventhouse ----------

def _to_dict(val):
    return json.loads(val) if isinstance(val, str) else val


def _since() -> datetime:
    """마지막 저장 as_of - 겹침. 처음이면 오늘 장 시작(09:00 KST)."""
    if state["persisted_as_of"]:
        return _parse_ts(state["persisted_as_of"]) - OVERLAP
    k = datetime.now(KST).replace(hour=9, minute=0, second=0, microsecond=0)
    return k.astimezone(timezone.utc)


def _fetch(since: datetime) -> list[dict]:
    q = QUERY.format(since=since.strftime("%Y-%m-%dT%H:%M:%SZ"))
    crp = ClientRequestProperties()
    crp.set_option(ClientRequestProperties.request_timeout_option_name, timedelta(seconds=CALL_TIMEOUT))
    primary = _kusto.execute(DATABASE, q, crp).primary_results[0]
    # 같은 snapshot_id가 여러 번 나오면 computed_at이 가장 늦은 것만 씁니다.
    by_id = {}
    for row in primary:
        snap = _to_dict(row["snapshot"])
        sid = snap.get("snapshot_id")
        cur = by_id.get(sid)
        if cur is None or str(snap.get("computed_at")) > str(cur.get("computed_at")):
            by_id[sid] = snap
    return sorted(by_id.values(), key=lambda x: str(x.get("as_of")))


# ---------- PostgreSQL ----------

INSERT_SNAPSHOT = """
INSERT INTO market_state_snapshot
    (snapshot_id, as_of, computed_at, universe_id, quality_status, schema_version, payload)
VALUES (%s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (snapshot_id) DO NOTHING
"""

UPSERT_LATEST = """
INSERT INTO market_state_latest (universe_id, snapshot_id, as_of, quality_status, payload)
VALUES (%s, %s, %s, %s, %s)
ON CONFLICT (universe_id) DO UPDATE SET
    snapshot_id = EXCLUDED.snapshot_id,
    as_of = EXCLUDED.as_of,
    quality_status = EXCLUDED.quality_status,
    payload = EXCLUDED.payload,
    updated_at = now()
WHERE EXCLUDED.as_of > market_state_latest.as_of
"""

SELECT_LATEST = """
SELECT payload FROM market_state_latest ORDER BY as_of DESC LIMIT 1
"""


def _connect():
    # 매번 새 토큰을 넣어 접속합니다. 토큰은 SDK가 캐시하고 만료 전에 갱신합니다.
    token = _credential.get_token(PG_SCOPE).token
    return psycopg.connect(
        host=PG_HOST, port=5432, dbname=PG_DB, user=PG_USER,
        password=token, sslmode="require", connect_timeout=10,
    )


def _persist_many(snaps: list[dict]) -> tuple[list[bool], Exception | None]:
    """한 접속으로 오래된 것부터 저장합니다. 스냅샷마다 커밋합니다.
    반환: (저장 성공한 스냅샷별 '새 행 여부', 실패 시 예외). 실패하면 그 지점에서 멈춥니다."""
    results: list[bool] = []
    try:
        with _connect() as conn:
            for snap in snaps:
                with conn.transaction(), conn.cursor() as cur:
                    cur.execute(INSERT_SNAPSHOT, (
                        snap["snapshot_id"], snap["as_of"], snap["computed_at"],
                        snap["universe_id"], snap["quality_status"], snap["schema_version"],
                        Jsonb(snap),
                    ))
                    inserted = cur.rowcount == 1
                    cur.execute(UPSERT_LATEST, (
                        snap["universe_id"], snap["snapshot_id"], snap["as_of"],
                        snap["quality_status"], Jsonb(snap),
                    ))
                results.append(inserted)
    except Exception as e:
        return results, e
    return results, None


def _load_latest() -> dict | None:
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(SELECT_LATEST)
        row = cur.fetchone()
    return row[0] if row else None


def _publish(snap: dict) -> None:
    # 계약 메시지(market_state_snapshot v2)를 그대로 보냅니다. record_type으로 구분합니다.
    _wps.send_to_all(message=snap, content_type="application/json",
                     connection_timeout=10, read_timeout=20, retry_total=2)


async def on_new_snapshot(snap: dict) -> None:
    """최신값이 실제로 앞으로 갔고 이번에 처음 저장된 경우에만 호출됩니다."""
    log.info("새 스냅샷 %s as_of=%s quality=%s valid=%s/%s",
             snap["snapshot_id"], snap["as_of"], snap["quality_status"],
             snap["valid_asset_count"], snap["expected_asset_count"])
    if _wps is None:
        return
    try:
        await asyncio.wait_for(asyncio.to_thread(_publish, snap), CALL_TIMEOUT)
    except Exception as e:
        # 발행 실패는 재시도하지 않습니다. 다음 분 스냅샷이 대신하고, 화면은 /current로 복구합니다.
        state.update(last_publish_ok=False, last_publish_error=type(e).__name__)
        log.error("Web PubSub 발행 실패 %s: %s %s", snap["snapshot_id"], type(e).__name__, str(e)[:200])
        return
    state.update(published_id=snap["snapshot_id"], last_publish_ok=True, last_publish_error=None)


def _valid(snap: dict) -> bool:
    errors = sorted(_validator.iter_errors(snap), key=lambda e: e.path)
    if errors:
        state["rejected"] += 1
        log.error("스키마 불일치로 버림 %s: %s", snap.get("snapshot_id"), "; ".join(
            f"{'/'.join(map(str, e.path)) or '(root)'}: {e.message}" for e in errors[:5]))
    return not errors


async def poll_once() -> None:
    state["last_poll_at"] = datetime.now(timezone.utc)
    try:
        snaps = await asyncio.wait_for(asyncio.to_thread(_fetch, _since()), CALL_TIMEOUT + 10)
    except Exception as e:
        state.update(last_poll_ok=False, last_error=type(e).__name__)
        log.error("Eventhouse 조회 실패: %s %s", type(e).__name__, str(e)[:200])
        return
    state.update(last_poll_ok=True, last_error=None)
    snaps = [s for s in snaps if _valid(s)]
    if not snaps:
        return

    newest = snaps[-1]
    prev = state["snapshot"]
    advanced = prev is None or _parse_ts(newest["as_of"]) > _parse_ts(prev["as_of"])

    # 1) 이력 저장: 오래된 것부터. 실패하면 멈추고 다음 분에 같은 구간부터 다시 시도합니다.
    newest_inserted = False
    if PG_HOST:
        try:
            results, err = await asyncio.wait_for(asyncio.to_thread(_persist_many, snaps), CALL_TIMEOUT + 10)
        except asyncio.TimeoutError as e:
            results, err = [], e
        for snap, inserted in zip(snaps, results):
            if (state["persisted_as_of"] is None
                    or _parse_ts(snap["as_of"]) > _parse_ts(state["persisted_as_of"])):
                state.update(persisted_id=snap["snapshot_id"], persisted_as_of=snap["as_of"])
            if inserted and snap is not newest:
                state["backfilled"] += 1
                log.info("이력 채움 %s", snap["snapshot_id"])
            if snap is newest:
                newest_inserted = inserted
        if err is None:
            state.update(last_db_ok=True, last_db_error=None)
        else:
            failed = snaps[len(results)]["snapshot_id"]
            state.update(last_db_ok=False, last_db_error=type(err).__name__)
            log.error("PostgreSQL 저장 실패 %s: %s %s", failed, type(err).__name__, str(err)[:200])
        if state["persisted_id"] != newest["snapshot_id"]:
            # 최신 스냅샷이 아직 DB에 없으면 화면 발행을 미룹니다(다음 분에 다시 시도).
            if advanced:
                state["snapshot"] = newest
            return

    # 2) 최신값 갱신과 발행: 시각이 앞으로 갔고, 이번에 처음 저장된 경우만.
    if advanced:
        state["snapshot"] = newest
        if newest_inserted or not PG_HOST:
            await on_new_snapshot(newest)


async def restore_from_db() -> None:
    """재시작 직후 DB의 최신값으로 채워 503을 줄이고 중복 발행을 막습니다."""
    if not PG_HOST:
        return
    try:
        snap = await asyncio.to_thread(_load_latest)
    except Exception as e:
        log.warning("DB 최신값 복원 실패: %s", type(e).__name__)
        return
    if snap:
        state.update(snapshot=snap, persisted_id=snap["snapshot_id"],
                     persisted_as_of=snap["as_of"])
        log.info("DB 최신값 복원 %s", snap["snapshot_id"])


async def poll_loop() -> None:
    try:
        await restore_from_db()
    except Exception:
        log.exception("DB 복원 예외")
    # 시작 직후에는 오늘 장 시작부터 다시 읽어 빠진 이력을 채웁니다(중복은 DB가 거릅니다).
    restored = state["persisted_as_of"]
    state["persisted_as_of"] = None
    try:
        await poll_once()
    except Exception:
        log.exception("시작 조회 예외")
    if state["persisted_as_of"] is None:
        state["persisted_as_of"] = restored
    while True:
        now = datetime.now(timezone.utc)
        nxt = now.replace(second=POLL_OFFSET, microsecond=0)
        if nxt <= now:
            nxt += timedelta(minutes=1)
        await asyncio.sleep((nxt - now).total_seconds())
        try:
            await poll_once()
        except Exception:
            # 한 번의 실패로 루프가 멈추지 않게 합니다. 다음 분에 다시 시도합니다.
            state.update(last_poll_ok=False, last_error="poll_loop_exception")
            log.exception("조회 루프 예외 - 다음 분에 다시 시도합니다")


def _in_session(now: datetime) -> bool:
    k = now.astimezone(KST)
    return k.weekday() < 5 and (9, 0) <= (k.hour, k.minute) <= (15, 30)


@asynccontextmanager
async def lifespan(_: FastAPI):
    task = asyncio.create_task(poll_loop())
    yield
    task.cancel()


app = FastAPI(title="whatif market-state", lifespan=lifespan)
if ALLOWED_ORIGINS:
    app.add_middleware(CORSMiddleware, allow_origins=ALLOWED_ORIGINS,
                       allow_methods=["GET", "POST"], allow_headers=["*"])


@app.post("/market-state/negotiate")
def negotiate():
    """브라우저용 수신 전용 연결 주소. 발행·그룹 참여 권한은 주지 않습니다."""
    if _wps is None:
        raise HTTPException(503, "Web PubSub이 설정되지 않았습니다.")
    token = _wps.get_client_access_token(minutes_to_expire=WPS_TOKEN_MINUTES)
    return {"url": token["url"], "hub": WPS_HUB, "expires_in_minutes": WPS_TOKEN_MINUTES}


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/market-state/status")
def status():
    snap = state["snapshot"]
    lp = state["last_poll_at"]
    return {
        "loop_alive": bool(lp) and (datetime.now(timezone.utc) - lp).total_seconds() < 90,
        "last_poll_at": state["last_poll_at"],
        "last_poll_ok": state["last_poll_ok"],
        "last_error": state["last_error"],
        "rejected": state["rejected"],
        "snapshot_id": snap and snap["snapshot_id"],
        "as_of": snap and snap["as_of"],
        "db_enabled": bool(PG_HOST),
        "persisted_id": state["persisted_id"],
        "persisted_as_of": state["persisted_as_of"],
        "backfilled": state["backfilled"],
        "last_db_ok": state["last_db_ok"],
        "last_db_error": state["last_db_error"],
        "publish_enabled": _wps is not None,
        "published_id": state["published_id"],
        "last_publish_ok": state["last_publish_ok"],
        "last_publish_error": state["last_publish_error"],
    }


@app.get("/market-state/current")
def current():
    snap = state["snapshot"]
    if snap is None:
        raise HTTPException(503, "아직 받은 스냅샷이 없습니다.")
    now = datetime.now(timezone.utc)
    age = (now - _parse_ts(snap["as_of"])).total_seconds()
    # 원본의 quality_status는 바꾸지 않고, API 전달 신선도만 따로 표시합니다.
    return {
        "delivery": {
            "age_seconds": round(age),
            "stale": _in_session(now) and age > STALE_AFTER,
            "last_poll_ok": state["last_poll_ok"],
            "persisted": snap["snapshot_id"] == state["persisted_id"],
        },
        "snapshot": snap,
    }
