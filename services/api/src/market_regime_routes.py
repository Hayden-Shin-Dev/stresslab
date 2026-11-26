"""시장국면(MarketRegimeML) 조회 경로.

regime.snapshot에서 data_mode='fabric_gold'인 최신 1행을 읽어 스냅샷 JSON을 그대로 돌려줍니다.
DB는 공통 API의 기존 연결 풀(deps.reader.store)을 씁니다. 새 접속 정보·환경 변수는 없습니다.
응답 구조는 contracts/market-regime/api-v1.md, 참고 구현은 services/market-regime/ 입니다.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from dataclasses import dataclass
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

log = logging.getLogger("gateway.market_regime")

router = APIRouter(prefix="/api/v1/market-regime", tags=["market-regime"])

CACHE_SECONDS = 300
DB_TIMEOUT_SECONDS = 5
LATEST_SQL = ("SELECT snapshot_version, as_of, data_mode, payload_text, payload_sha256 FROM regime.snapshot "
              "WHERE data_mode = 'fabric_gold' ORDER BY as_of DESC, created_at DESC LIMIT 1")


class SnapshotRejected(Exception):
    """조회한 행을 쓸 수 없음. 메시지는 코드만 담습니다(DB 오류 내용은 응답에 넣지 않음)."""


@dataclass(frozen=True)
class Snapshot:
    snapshot_version: str
    as_of: str
    payload_text: str


class _Cache:
    def __init__(self):
        self.good: Optional[Snapshot] = None   # 마지막 정상값
        self.checked_at: Optional[float] = None
        self.lock = asyncio.Lock()

    def fresh(self, now: float) -> bool:
        return self.good is not None and self.checked_at is not None and now - self.checked_at < CACHE_SECONDS


def _validate(row) -> Snapshot:
    if not row:
        raise SnapshotRejected("NO_SNAPSHOT_ROWS")
    text = row.get("payload_text")
    if not isinstance(text, str):
        raise SnapshotRejected("PAYLOAD_MISSING")
    expected = (row.get("payload_sha256") or "").strip().lower()
    if hashlib.sha256(text.encode("utf-8")).hexdigest() != expected:
        raise SnapshotRejected("SNAPSHOT_SHA256_MISMATCH")
    try:
        payload = json.loads(text)
    except ValueError:
        raise SnapshotRejected("PAYLOAD_NOT_JSON") from None
    if (not isinstance(payload, dict) or payload.get("schema") != "market_regime_snapshot"
            or type(payload.get("schema_version")) is not int or payload.get("schema_version") != 1):
        raise SnapshotRejected("SNAPSHOT_SCHEMA_UNSUPPORTED")
    if row.get("data_mode") != "fabric_gold" or payload.get("data_mode") != "fabric_gold":
        raise SnapshotRejected("SYNTHETIC_SNAPSHOT_REFUSED")
    as_of = row.get("as_of")
    return Snapshot(str(row["snapshot_version"]), as_of.isoformat() if hasattr(as_of, "isoformat") else str(as_of), text)


async def _fetch(request: Request) -> Snapshot:
    deps = getattr(request.app.state, "deps", None)
    store = getattr(getattr(deps, "reader", None), "store", None)
    one = getattr(store, "_one", None)
    if one is None:
        raise SnapshotRejected("DB_NOT_CONFIGURED")
    row = await asyncio.wait_for(one(LATEST_SQL), timeout=DB_TIMEOUT_SECONDS)
    return _validate(row)


async def current_snapshot(request: Request) -> Optional[Snapshot]:
    """5분 캐시. 조회 실패·검사 실패면 마지막 정상값, 정상값이 없으면 None."""
    cache = getattr(request.app.state, "market_regime_cache", None)
    if cache is None:
        cache = request.app.state.market_regime_cache = _Cache()
    if cache.fresh(time.monotonic()):
        return cache.good
    async with cache.lock:
        if cache.fresh(time.monotonic()):
            return cache.good
        try:
            cache.good = await _fetch(request)
        except SnapshotRejected as exc:
            log.warning("시장국면 스냅샷 사용 불가: %s (마지막 정상값 %s)", exc,
                        cache.good.snapshot_version if cache.good else "없음")
        except Exception as exc:   # DB 연결·시간 초과 등
            log.warning("시장국면 스냅샷 조회 실패: %s (마지막 정상값 %s)", type(exc).__name__,
                        cache.good.snapshot_version if cache.good else "없음")
        cache.checked_at = time.monotonic()
        return cache.good


@router.get("/snapshot")
async def get_snapshot(request: Request):
    snap = await current_snapshot(request)
    if snap is None:
        raise HTTPException(503, {"code": "market_regime_unavailable"})
    # 저장된 원문을 다시 직렬화하지 않고 그대로 보냅니다(sha256 유지).
    return Response(content=snap.payload_text.encode("utf-8"), media_type="application/json; charset=utf-8")


@router.get("/health")
async def get_health(request: Request):
    snap = await current_snapshot(request)
    if snap is None:
        return {"status": "unavailable", "as_of": None, "snapshot_version": None}
    return {"status": "ok", "as_of": snap.as_of, "snapshot_version": snap.snapshot_version}
