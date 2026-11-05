"""저장소. 운영은 PostgreSQL(PostgresStore), 테스트는 메모리(MemoryStore).

이벤트는 발언과 같은 트랜잭션에 넣고(outbox), 발행은 저장 뒤 publisher가 합니다.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional, Protocol

from psycopg.types.json import Jsonb


def _now():
    return datetime.now(timezone.utc)


class Store(Protocol):
    async def ensure_debate(self, req) -> dict: ...
    async def claim_request(self, req) -> bool: ...
    async def finish_request(self, request_id: str) -> None: ...
    async def get_debate(self, debate_id: str) -> Optional[dict]: ...
    async def update_debate(self, debate_id: str, **fields) -> None: ...
    async def save_bundle(self, bundle: dict) -> None: ...
    async def get_bundle(self, evidence_bundle_id: str) -> Optional[dict]: ...
    async def get_message(self, message_id: str) -> Optional[dict]: ...
    async def list_messages(self, debate_id: str) -> list[dict]: ...
    async def save_message(self, msg: dict, event_type: str, event_payload: dict) -> None: ...
    async def add_event(self, debate_id: str, event_id: str, type_: str, payload: dict) -> None: ...
    async def pending_events(self, debate_id: str) -> list[dict]: ...
    async def mark_published(self, debate_id: str, seq: int) -> None: ...


# ---------------------------------------------------------------------------
class MemoryStore:
    def __init__(self):
        self.debates, self.requests, self.bundles, self.messages, self.events = {}, {}, {}, {}, {}

    async def ensure_debate(self, req):
        d = self.debates.setdefault(req.debate_id, {
            "debate_id": req.debate_id, "user_id": req.user_id, "trigger": req.trigger,
            "scheduled_slot": req.scheduled_slot, "run_id": req.run_id, "snapshot_id": req.snapshot_id,
            "evidence_bundle_id": None, "status": "accepted", "error": None, "last_seq": 0})
        return dict(d)

    async def claim_request(self, req):
        r = self.requests.setdefault(req.request_id, {"processed_at": None, "debate_id": req.debate_id})
        return r["processed_at"] is None

    async def finish_request(self, request_id):
        self.requests[request_id]["processed_at"] = _now()

    async def get_debate(self, debate_id):
        d = self.debates.get(debate_id)
        return dict(d) if d else None

    async def update_debate(self, debate_id, **fields):
        self.debates[debate_id].update(fields)

    async def save_bundle(self, bundle):
        self.bundles.setdefault(bundle["evidence_bundle_id"], json.loads(json.dumps(bundle, default=str)))

    async def get_bundle(self, evidence_bundle_id):
        return self.bundles.get(evidence_bundle_id)

    async def get_message(self, message_id):
        return self.messages.get(message_id)

    async def list_messages(self, debate_id):
        return [m for m in self.messages.values() if m["debate_id"] == debate_id]

    async def save_message(self, msg, event_type, event_payload):
        if msg["message_id"] in self.messages:
            return
        self.messages[msg["message_id"]] = dict(msg)
        await self.add_event(msg["debate_id"], f"{msg['message_id']}:{event_type}", event_type, event_payload)

    async def add_event(self, debate_id, event_id, type_, payload):
        if event_id in self.events:
            return
        d = self.debates[debate_id]
        d["last_seq"] += 1
        self.events[event_id] = {"debate_id": debate_id, "seq": d["last_seq"], "event_id": event_id,
                                 "type": type_, "payload": payload, "created_at": _now(), "published_at": None}

    async def pending_events(self, debate_id):
        return sorted((e for e in self.events.values() if e["debate_id"] == debate_id and e["published_at"] is None),
                      key=lambda e: e["seq"])

    async def mark_published(self, debate_id, seq):
        for e in self.events.values():
            if e["debate_id"] == debate_id and e["seq"] == seq:
                e["published_at"] = _now()


# ---------------------------------------------------------------------------
class PostgresStore:
    """psycopg 비동기 연결 풀. 관리 ID 토큰을 비밀번호로 씁니다."""

    def __init__(self, pool):
        self.pool = pool

    @classmethod
    async def connect(cls, host: str, db: str, user: str, credential, min_size=1, max_size=4, port: int = 5432):
        """Microsoft 문서 방식: 연결을 새로 만들 때마다 Entra 토큰을 비밀번호로 넣습니다.
        시작할 때 한 번 직접 연결해 보고, 실패하면 원인을 그대로 올립니다(풀은 오류를 한 줄로 줄여 기록함)."""
        import psycopg
        from psycopg_pool import AsyncConnectionPool

        scope = "https://ossrdbms-aad.database.windows.net/.default"
        base = {"host": host, "port": port, "dbname": db, "user": user, "sslmode": "require", "connect_timeout": 15}

        class EntraConnection(psycopg.AsyncConnection):
            @classmethod
            async def connect(cls, conninfo="", **kwargs):
                # 토큰은 SDK가 만료 전까지 캐시합니다. 동기 호출이지만 새 연결을 만들 때만 실행됩니다.
                kwargs["password"] = credential.get_token(scope).token
                return await super().connect(conninfo, **kwargs)

        first = await EntraConnection.connect(**base)   # 실패하면 여기서 전체 오류가 보임
        await first.close()
        pool = AsyncConnectionPool(conninfo="", connection_class=EntraConnection, kwargs=base,
                                   min_size=min_size, max_size=max_size, open=False)
        await pool.open(wait=True, timeout=30)
        return cls(pool)

    async def _one(self, sql, args=()):
        async with self.pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(sql, args)
            row = await cur.fetchone()
            cols = [d.name for d in cur.description] if cur.description else []
        return dict(zip(cols, row)) if row else None

    async def _exec(self, sql, args=()):
        async with self.pool.connection() as conn:
            await conn.execute(sql, args)

    async def ensure_debate(self, req):
        await self._exec("""INSERT INTO debate (debate_id, user_id, trigger, scheduled_slot, run_id, snapshot_id)
                            VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (debate_id) DO NOTHING""",
                         (req.debate_id, req.user_id, req.trigger, req.scheduled_slot, req.run_id, req.snapshot_id))
        return await self.get_debate(req.debate_id)

    async def claim_request(self, req):
        await self._exec("""INSERT INTO debate_request (request_id, debate_id, type, payload)
                            VALUES (%s,%s,%s,%s) ON CONFLICT (request_id) DO NOTHING""",
                         (req.request_id, req.debate_id, req.type, Jsonb(req.model_dump(mode="json"))))
        row = await self._one("SELECT processed_at FROM debate_request WHERE request_id=%s", (req.request_id,))
        return row["processed_at"] is None

    async def finish_request(self, request_id):
        await self._exec("UPDATE debate_request SET processed_at=now() WHERE request_id=%s", (request_id,))

    async def get_debate(self, debate_id):
        return await self._one("SELECT * FROM debate WHERE debate_id=%s", (debate_id,))

    async def update_debate(self, debate_id, **fields):
        allowed = {"snapshot_id", "evidence_bundle_id", "status", "error"}
        if not set(fields) <= allowed:
            raise ValueError(fields)
        sets = ", ".join(f"{k}=%s" for k in fields) + ", updated_at=now()"
        await self._exec(f"UPDATE debate SET {sets} WHERE debate_id=%s", (*fields.values(), debate_id))

    async def save_bundle(self, bundle):
        await self._exec("""INSERT INTO evidence_bundle (evidence_bundle_id, debate_id, payload, sha256)
                            VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                         (bundle["evidence_bundle_id"], bundle["debate_id"], Jsonb(bundle), bundle["sha256"]))

    async def get_bundle(self, evidence_bundle_id):
        row = await self._one("SELECT payload FROM evidence_bundle WHERE evidence_bundle_id=%s", (evidence_bundle_id,))
        return row["payload"] if row else None

    async def get_message(self, message_id):
        return await self._one("SELECT * FROM debate_message WHERE message_id=%s", (message_id,))

    async def list_messages(self, debate_id):
        async with self.pool.connection() as conn, conn.cursor() as cur:
            await cur.execute("SELECT * FROM debate_message WHERE debate_id=%s ORDER BY created_at", (debate_id,))
            cols = [d.name for d in cur.description]
            return [dict(zip(cols, r)) for r in await cur.fetchall()]

    async def save_message(self, msg, event_type, event_payload):
        async with self.pool.connection() as conn:
            async with conn.transaction():
                cur = await conn.execute(
                    """INSERT INTO debate_message (message_id, debate_id, round_id, phase, role, question_id,
                           reference_message_id, status, output, error, model_deployment, prompt_version)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (message_id) DO NOTHING""",
                    (msg["message_id"], msg["debate_id"], msg["round_id"], msg["phase"], msg["role"],
                     msg.get("question_id"), msg.get("reference_message_id"), msg["status"],
                     Jsonb(msg["output"]) if msg.get("output") is not None else None, msg.get("error"),
                     msg.get("model_deployment"), msg.get("prompt_version")))
                if cur.rowcount:
                    await self._add_event(conn, msg["debate_id"], f"{msg['message_id']}:{event_type}",
                                          event_type, event_payload)

    async def add_event(self, debate_id, event_id, type_, payload):
        async with self.pool.connection() as conn:
            async with conn.transaction():
                await self._add_event(conn, debate_id, event_id, type_, payload)

    @staticmethod
    async def _add_event(conn, debate_id, event_id, type_, payload):
        exists = await (await conn.execute("SELECT 1 FROM debate_event WHERE event_id=%s", (event_id,))).fetchone()
        if exists:
            return
        seq = (await (await conn.execute(
            "UPDATE debate SET last_seq=last_seq+1, updated_at=now() WHERE debate_id=%s RETURNING last_seq",
            (debate_id,))).fetchone())[0]
        await conn.execute("INSERT INTO debate_event (debate_id, seq, event_id, type, payload) VALUES (%s,%s,%s,%s,%s)",
                           (debate_id, seq, event_id, type_, Jsonb(payload)))

    async def pending_events(self, debate_id):
        async with self.pool.connection() as conn, conn.cursor() as cur:
            await cur.execute("""SELECT debate_id, seq, event_id, type, payload, created_at FROM debate_event
                                 WHERE debate_id=%s AND published_at IS NULL ORDER BY seq""", (debate_id,))
            cols = [d.name for d in cur.description]
            return [dict(zip(cols, r)) for r in await cur.fetchall()]

    async def mark_published(self, debate_id, seq):
        await self._exec("UPDATE debate_event SET published_at=now() WHERE debate_id=%s AND seq=%s", (debate_id, seq))
