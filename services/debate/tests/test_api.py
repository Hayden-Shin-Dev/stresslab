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
        self.rows, self.evts, self.hold, self.runs = {}, {}, {}, {}

    async def save_stress_run(self, run_id, user_id, request, result, market_snapshot):
        self.runs.setdefault(run_id, {"run_id": run_id, "user_id": user_id, "request": request,
                                      "result": result, "market_snapshot": market_snapshot})

    async def stress_run(self, run_id):
        return self.runs.get(run_id)

    async def holdings(self, user_id):
        return sorted(self.hold.get(user_id, []), key=lambda h: (-h["amount_krw"], h["asset_id"]))

    async def replace_holdings(self, user_id, items):
        self.hold[user_id] = [{**it, "updated_at": "2026-11-10T06:00:00+00:00"} for it in items]
        if not items:
            self.hold.pop(user_id)

    async def holding_users(self, limit):
        return list(self.hold)[:limit]

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
    client = TestClient(api.create_app(api.Deps(q, r, FakeTokens(), scheduler_key="secret",
                                                allow_dev_user_header=True)))
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
    assert client.post("/debates", json={}).status_code == 401      # 로그인 정보 없음


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
    client = TestClient(api.create_app(api.Deps(Broken(), FakeReader(), FakeTokens(), allow_dev_user_header=True)))
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



# ---------------------------------------------------------------------------- SWA 로그인·보유 종목
import base64  # noqa: E402
import json  # noqa: E402


def swa(user_id="abc123", provider="aad", name="yujin@school", roles=("anonymous", "authenticated")):
    p = {"identityProvider": provider, "userId": user_id, "userDetails": name, "userRoles": list(roles)}
    return {"x-ms-client-principal": base64.b64encode(json.dumps(p).encode()).decode()}


def test_swa_principal_is_user_and_api_prefix_works(env):
    client, q, _ = env
    res = client.get("/api/me", headers=swa())
    assert res.status_code == 200
    assert res.json()["user_id"] == "aad:abc123" and res.json()["name"] == "yujin@school"
    res = client.post("/api/debates", json={}, headers=swa())
    assert res.status_code == 202 and q.sent[-1][2]["user_id"] == "aad:abc123"


def test_dev_header_rejected_unless_enabled():
    q, r = FakeQueue(), FakeReader()
    client = TestClient(api.create_app(api.Deps(q, r, FakeTokens())))
    assert client.get("/api/me", headers={"X-User-Id": "someone"}).status_code == 401
    assert client.get("/api/me", headers=swa()).status_code == 200


def test_broken_or_anonymous_principal_is_rejected():
    client = TestClient(api.create_app(api.Deps(FakeQueue(), FakeReader(), FakeTokens())))
    assert client.get("/api/me", headers={"x-ms-client-principal": "%%%"}).status_code == 401
    assert client.get("/api/me", headers=swa(roles=("anonymous",))).status_code == 401


def test_holdings_save_replace_and_read(env):
    client, _, r = env
    body = {"holdings": [{"asset_id": "005930", "amount_krw": 5000000}, {"asset_id": "000660", "amount_krw": 3e6}]}
    res = client.put("/api/me/holdings", json=body, headers=swa())
    assert res.status_code == 200
    out = res.json()
    assert out["count"] == 2 and out["total_krw"] == 8e6 and out["holdings"][0]["asset_id"] == "005930"
    client.put("/api/me/holdings", json={"holdings": [{"asset_id": "005380", "amount_krw": 1}]}, headers=swa())
    got = client.get("/api/me/holdings", headers=swa()).json()
    assert [h["asset_id"] for h in got["holdings"]] == ["005380"]          # 통째로 바뀜
    assert client.get("/api/me/holdings", headers=swa(user_id="other")).json()["count"] == 0   # 남의 것 안 보임


def test_holdings_validation(env):
    client, _, _ = env
    bad = {"holdings": [{"asset_id": "5930", "amount_krw": 1}, {"asset_id": "005930", "amount_krw": 1},
                        {"asset_id": "005930", "amount_krw": 2}]}
    res = client.put("/api/me/holdings", json=bad, headers=swa())
    assert res.status_code == 422
    errs = res.json()["detail"]["errors"]
    assert "형식" in errs[0] and "두 번" in errs[1]
    assert client.put("/api/me/holdings", json={"holdings": [{"asset_id": "005930", "amount_krw": 0}]},
                      headers=swa()).status_code == 422


def test_holdings_allowed_assets_and_limit():
    client = TestClient(api.create_app(api.Deps(FakeQueue(), FakeReader(), FakeTokens(),
                                                allowed_assets={"005930"}, holdings_max=1)))
    res = client.put("/api/me/holdings", json={"holdings": [{"asset_id": "999999", "amount_krw": 1}]}, headers=swa())
    assert res.status_code == 422 and "지원하지 않는" in res.json()["detail"]["errors"][0]
    two = {"holdings": [{"asset_id": "005930", "amount_krw": 1}, {"asset_id": "000660", "amount_krw": 1}]}
    assert client.put("/api/me/holdings", json=two, headers=swa()).status_code == 422


def test_scheduled_targets_holding_users_first_then_recent(env):
    client, q, r = env
    client.put("/api/me/holdings", json={"holdings": [{"asset_id": "005930", "amount_krw": 1}]}, headers=swa())
    r.rows["d-old"] = {"debate_id": "d-old", "user_id": "u-recent", "trigger": "user", "run_id": "run-x",
                       "status": "completed", "snapshot_id": None}
    res = client.post("/api/scheduled-debates", json={"slot": "1300"}, headers={"X-Scheduler-Key": "secret"})
    assert res.status_code == 202
    out = res.json()
    assert out["users"] == 2 and out["holding_users"] == 1
    sent = {b["user_id"]: b["run_id"] for _, _, b in q.sent}
    assert sent == {"aad:abc123": "stress_run", "u-recent": "run-x"}


def test_analysis_run_id_must_be_saved_and_owned(env):
    client, q, r = env
    assert client.post("/debates", json={"run_id": "a-missing"}, headers=H).status_code == 404
    r.runs["a-x"] = {"run_id": "a-x", "user_id": "u2"}
    assert client.post("/debates", json={"run_id": "a-x"}, headers=H).status_code == 404
    r.runs["a-mine"] = {"run_id": "a-mine", "user_id": "u1"}
    res = client.post("/debates", json={"run_id": "a-mine"}, headers=H)
    assert res.status_code == 202 and q.sent[-1][2]["run_id"] == "a-mine"
