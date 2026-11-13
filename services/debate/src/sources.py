"""근거 원본 조회: Stress Engine 결과, 시장 상태 스냅샷.

토론 실행기는 숫자를 계산하지 않고 조회만 합니다.
- Stress Engine: GET {STRESS_ENGINE_URL}/runs/{run_id}  (stress-engine 구현 전에는 파일로 대체)
- 시장 상태 API: GET {MARKET_STATE_URL}/market-state/snapshots/{snapshot_id}
                 snapshot_id가 없으면 GET {MARKET_STATE_URL}/market-state/current 로 접수 시점 최신값을 고정
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional, Protocol

import httpx


class NotFound(Exception):
    """요청한 run이나 스냅샷이 없음. 재시도해도 같은 결과라 토론을 실패 처리합니다."""


class StressSource(Protocol):
    async def get_run(self, run_id: str) -> dict: ...


class MarketStateSource(Protocol):
    async def get_snapshot(self, snapshot_id: Optional[str]) -> Optional[dict]: ...


class HttpStressSource:
    def __init__(self, base_url: str, timeout: float = 20.0):
        self._http = httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=timeout)

    async def get_run(self, run_id):
        r = await self._http.get(f"/runs/{run_id}")
        if r.status_code == 404:
            raise NotFound(f"stress run {run_id}")
        r.raise_for_status()   # 5xx·timeout은 예외 → 메시지 재전달로 재시도
        return r.json()


class FileStressSource:
    """stress-engine이 생기기 전 개발용: {dir}/{run_id}.json"""

    def __init__(self, directory: str):
        self._dir = Path(directory)

    async def get_run(self, run_id):
        f = self._dir / f"{run_id}.json"
        if not f.exists():
            raise NotFound(f"stress run file {f}")
        return json.loads(f.read_text(encoding="utf-8"))


class PostgresStressSource:
    """웹 분석 결과(stress_run 테이블, run_id 'a-...'). 분석 시점 장중 스냅샷을 run["market_snapshot"]에 붙여
    돌려줍니다(토론이 분석과 같은 스냅샷을 쓰도록). 테이블에 없으면 fallback(개발용 파일 등)."""

    def __init__(self, store, fallback=None):
        self._store, self._fallback = store, fallback

    async def get_run(self, run_id):
        async with self._store.pool.connection() as conn, conn.cursor() as cur:
            await cur.execute("SELECT result, market_snapshot FROM stress_run WHERE run_id=%s", (run_id,))
            row = await cur.fetchone()
        if row:
            run = dict(row[0])
            run["market_snapshot"] = row[1]
            return run
        if self._fallback:
            return await self._fallback.get_run(run_id)
        raise NotFound(f"stress run {run_id}")


class HttpMarketStateSource:
    def __init__(self, base_url: str, timeout: float = 15.0):
        self._http = httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=timeout)

    async def get_snapshot(self, snapshot_id):
        if snapshot_id:
            r = await self._http.get(f"/market-state/snapshots/{snapshot_id}")
            if r.status_code == 404:
                raise NotFound(f"snapshot {snapshot_id}")
            r.raise_for_status()
            return r.json()["snapshot"]
        r = await self._http.get("/market-state/current")
        if r.status_code == 503:   # 아직 스냅샷 없음(장 시작 전 재기동 등) → 장중 근거 없이 진행
            return None
        r.raise_for_status()
        return r.json()["snapshot"]


class FileMarketStateSource:
    def __init__(self, path: Optional[str]):
        self._path = Path(path) if path else None

    async def get_snapshot(self, snapshot_id):
        if not self._path:
            return None
        return json.loads(self._path.read_text(encoding="utf-8"))
