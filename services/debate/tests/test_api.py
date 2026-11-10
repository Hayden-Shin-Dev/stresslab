"""토론 요청 API 테스트. Azure 없이 가짜 큐·DB·토큰으로 확인합니다."""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import api  # noqa: E402
import contracts as c  # noqa: E402


class FakeQueue:
    def __init__(self):
        self.sent = []

    async def send(self, body, *, session_id, message_id):
        self.sent.append((session_id, message_id, body))


class FakeReader:
    def __init__(self):
        self.rows, self.evts = {}, {}

    async def debate(self, debate_id):
        return self.rows.get(debate_id)

    async def events(self, debate_id, after_seq, limit):
        return [e for e in self.evts.get(debate_id, []) if e["seq"] > after_seq][:limit]

    async def list_debates(self, user_id, limit):
        return [r for r in self.rows.values() if r["user_id"] == user_id][:limit]

    async def active_users(self, days, limit):
        users = {}
        for r in self.rows.values():
            if r.get("trigger", "user") == "user":
                users[r["user_id"]] = {"user_id": r["user_id"], "run_id": r["run_id"]}
        return list(users.values())[:limit]


class FakeTokens:
    async def token(self, user_id, group):
        return {"url": f"wss://x/client/hubs/debate?access_token={user_id}", "group": group, "expires_in_minutes": 60}


@pytest.fixture
def env():
    q, r = FakeQueue(), FakeReader()
    client = TestClient(api.create_app(api.Deps(q, r, FakeTokens(), scheduler_key="secret")))
    return client, q, r


H = {"X-User-Id": "u1"}


def test_start_sends_session_message_and_returns_token(env):
    client, q, _ = env
    res = client.post("/debates", json={}, headers=H)
    assert res.status_code == 202
    body = res.json()
    sid, mid, msg = q.sent[0]
    assert sid == body["debate_id"] and mid == body["request_id"] == f"{sid}-start"
    c.DebateRequest.model_validate(msg)
    assert msg["run_id"] == "stress_run" and msg["user_id"] == "u1"
    assert body["pubsub"]["group"] == f"debate-{sid}"


def test_same_idempotency_key_gives_same_ids(env):
    client, q, _ = env
    a = client.post("/debates", json={}, headers={**H, "Idempotency-Key": "k1"}).json()
    b = client.post("/debates", json={}, headers={**H, "Idempotency-Key": "k1"}).json()
    assert a["debate_id"] == b["debate_id"] and a["request_id"] == b["request_id"]
    other = client.post("/debates", json={}, headers={"X-User-Id": "u2", "Idempotency-Key": "k1"}).json()
    assert other["debate_id"] != a["debate_id"]


def test_user_id_required(env):
    client, _, _ = env
    assert client.post("/debates", json={}).status_code == 422


def test_scheduled_creates_one_debate_per_active_user(env):
    client, q, r = env
    r.rows["d-a"] = {"debate_id": "d-a", "user_id": "u1", "trigger": "user", "status": "completed", "run_id": "run-u1", "snapshot_id": None}
    r.rows["d-b"] = {"debate_id": "d-b", "user_id": "u2", "trigger": "user", "status": "completed", "run_id": "run-u2", "snapshot_id": None}
    body = {"slot": "0830"}
    assert client.post("/scheduled-debates", json=body).status_code == 403
    assert client.post("/scheduled-debates", json=body, headers={"X-Scheduler-Key": "wrong"}).status_code == 403
    res = client.post("/scheduled-debates", json=body, headers={"X-Scheduler-Key": "secret"})
    assert res.status_code == 202 and res.json()["accepted"] == 2
    sent = {m[2]["user_id"]: m[2] for m in q.sent}
    assert sent["u1"]["run_id"] == "run-u1" and sent["u2"]["run_id"] == "run-u2"   # 사용자마다 자기 결과로
    assert all(m["trigger"] == "scheduled" and m["scheduled_slot"] == "0830" for m in sent.values())
    first = {m[0] for m in q.sent}
    client.post("/scheduled-debates", json=body, headers={"X-Scheduler-Key": "secret"})
    assert {m[0] for m in q.sent} == first   # 재시도해도 같은 debate_id
    assert client.post("/scheduled-debates", json={"slot": "0900"}, headers={"X-Scheduler-Key": "secret"}).status_code == 422


def test_user_cannot_use_system_id_and_lists_only_own(env):
    client, _, r = env
    assert client.post("/debates", json={}, headers={"X-User-Id": "system"}).status_code == 403
    r.rows["d-a"] = {"debate_id": "d-a", "user_id": "u1", "trigger": "user", "status": "completed", "run_id": "x", "snapshot_id": None}
    r.rows["d-b"] = {"debate_id": "d-b", "user_id": "u2", "trigger": "user", "status": "completed", "run_id": "y", "snapshot_id": None}
    ids = [d["debate_id"] for d in client.get("/debates", headers=H).json()["debates"]]
    assert ids == ["d-a"]


def test_question_checks_owner_and_status(env):
    client, q, r = env
    q_body = {"text": "금리만 보면?", "target_roles": ["macro", "risk"]}
    assert client.post("/debates/d-1/questions", json=q_body, headers=H).status_code == 409   # 아직 접수 전
    r.rows["d-1"] = {"debate_id": "d-1", "user_id": "u1", "status": "completed", "run_id": "r1", "snapshot_id": "s1"}
    assert client.post("/debates/d-1/questions", json=q_body, headers={"X-User-Id": "u2"}).status_code == 404
    res = client.post("/debates/d-1/questions", json=q_body, headers=H)
    assert res.status_code == 202
    sid, mid, msg = q.sent[-1]
    assert sid == "d-1" and msg["type"] == "user_question" and msg["run_id"] == "r1" and msg["snapshot_id"] == "s1"
    c.DebateRequest.model_validate(msg)
    r.rows["d-1"]["status"] = "failed"
    assert client.post("/debates/d-1/questions", json=q_body, headers=H).status_code == 409
    assert client.post("/debates/d-1/questions", json={"text": "x", "target_roles": ["boss"]},
                       headers=H).status_code == 422


def test_events_after_seq(env):
    client, _, r = env
    r.rows["d-1"] = {"debate_id": "d-1", "user_id": "u1", "status": "running", "run_id": "r1", "snapshot_id": None}
    r.evts["d-1"] = [{"seq": i, "event_id": f"e{i}", "type": "message.published", "payload": {}, "created_at": "t"}
                     for i in (1, 2, 3)]
    body = client.get("/debates/d-1/events?after_seq=1", headers=H).json()
    assert [e["seq"] for e in body["events"]] == [2, 3] and body["next_after_seq"] == 3
    assert client.get("/debates/d-1/events", headers={"X-User-Id": "u2"}).status_code == 404
    assert client.get("/debates/d-1/negotiate", headers=H).json()["group"] == "debate-d-1"


def test_queue_failure_returns_503():
    class Broken(FakeQueue):
        async def send(self, *a, **k):
            raise RuntimeError("down")
    client = TestClient(api.create_app(api.Deps(Broken(), FakeReader(), FakeTokens())))
    assert client.post("/debates", json={}, headers=H).status_code == 503


def test_schedule_script_posts_scheduled_request(monkeypatch):
    import io
    import json as _json
    import schedule
    seen = {}

    class Res(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout):
        seen["url"], seen["body"], seen["headers"] = req.full_url, _json.loads(req.data), dict(req.header_items())
        return Res(b'{"slot": "0830", "users": 2, "accepted": 2, "failed": 0, "capped": false}')

    monkeypatch.setattr(schedule.urllib.request, "urlopen", fake_urlopen)
    out = schedule.request("0830", "https://api.example/", "k")
    assert out["accepted"] == 2
    assert seen["url"] == "https://api.example/scheduled-debates"
    assert seen["body"] == {"slot": "0830"}
    assert seen["headers"]["X-scheduler-key"] == "k"
    with pytest.raises(ValueError):
        schedule.request("0900", "https://api.example", "k")


def test_json_responses_declare_utf8_charset(env):
    client, _, _ = env
    res = client.post("/debates", json={}, headers=H)
    assert res.headers["content-type"] == "application/json; charset=utf-8"
