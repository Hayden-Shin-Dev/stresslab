"""Azure 없이 토론 실행기 전체 흐름을 검증합니다.

실행: 저장소 최상위에서  python -m pytest services/debate/tests -q
가짜 모델(FakeLLM)이 입력으로 받은 근거 ID만 인용하는 정상 응답을 만듭니다.
Stress Engine 결과는 tail_reliability_20261103/scenario_examples.json(환율 +5%, 금리 +100bp) 6종목,
시장 상태는 contracts/realtime/mock.json의 합성 스냅샷입니다.
"""
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

import contracts as c  # noqa: E402
from llm import LLMError, Prompts  # noqa: E402
from orchestrator import Orchestrator, TransientError  # noqa: E402
from publisher import MemorySender, Publisher  # noqa: E402
from sources import FileMarketStateSource, FileStressSource  # noqa: E402
from store import MemoryStore  # noqa: E402
import worker  # noqa: E402

FIX = Path(__file__).parent / "fixtures"
TARGET = {"macro": "risk", "market": "portfolio", "risk": "macro", "portfolio": "risk"}


class FakeLLM:
    deployment = "fake-deployment"

    def __init__(self, fail=None, bad=None, leak=None, converged=True, revise=None):
        self.calls = []
        self.converged = converged          # False면 2라운드 뒤 사회자가 3라운드를 엶
        self.revise = revise or set()       # 2라운드에서 의견을 바꿀 역할
        self.fail = fail or {}      # role -> 남은 일시 장애 횟수 (None이면 계속)
        self.bad = bad or set()     # 없는 근거 ID를 인용할 역할
        self.leak = leak or set()   # 화면 문장에 내부 ID를 쓸 역할

    async def complete(self, system, user, schema, schema_name):
        data = json.loads(user)
        self.calls.append((schema_name, data))
        if schema_name == "debate_summary":
            ids = [m["message_id"] for m in data["messages"]]
            done = self.converged or not data["can_continue"]
            first = data["messages"][0]
            return {"summary_text": "결과 소폭 이익으로 생각됩니다.", "converged": done,
                    "open_issue_roles": [] if done else ["macro", "risk"],
                    "accepted": [{"statement": "부담은 한 종목에 몰림", "role": first["role"], "message_id": first["message_id"], "reason": "다른 역할도 동의"}],
                    "rejected": [{"statement": "현대차가 결과를 정한다", "role": first["role"], "message_id": first["message_id"],
                                  "rejected_by": "risk" if first["role"] != "risk" else "macro", "reason": "손실이 한 종목에 몰려 있다"}],
                    "changed_views": [
                        {"role": m["role"], "before": "이전", "after": "수정", "reason": "반박 수용", "message_id": m["message_id"]}
                        for m in data["messages"] if m["view_status"] == "revised"],
                    "agreements": [{"statement": "환율 충격 영향 확인", "message_ids": ids[:2]}],
                    "disagreements": [{"issue": "하방 폭", "positions": [
                        {"role": "risk", "message_id": ids[-1], "stance": "보수적"}]}],
                    "next_checks": ["다음 스냅샷"]}
        role = data["role"]
        if role in self.fail:
            left = self.fail[role]
            if left is None or left > 0:
                if left:
                    self.fail[role] = left - 1
                raise ConnectionError("model down")
        d_ids = [x["id"] for x in data["D_sources"]]
        ref = ["D9999"] if role in self.bad else d_ids[:2]
        text = "근거 D1에 따르면" if role in self.leak else f"{role} 관점의 판단입니다."
        persona_data = {k: ([] if v["type"] == "array" else v["enum"][0])
                        for k, v in schema["properties"]["persona_data"]["properties"].items()}
        intent = c.PHASE_INTENT[data["phase"]]
        lone = data["phase"] in ("INITIAL", "USER_ANSWER")
        revising = data["phase"] == "REBUTTAL" and role in self.revise
        return {
            "schema_version": 2, "context_version": data["context_version"], "role": role, "intent": intent,
            "response_status": "ok", "summary_text": f"{role} 요약", "display_text": text, "tts_text": "",
            "view_status": "revised" if revising else "initial",
            "stance": "first" if lone else ("revise" if revising else "disagree"),
            "reply_to": None if lone else TARGET[role],
            "claims": [{"claim_id": "c1", "kind": "observation", "statement": "관측됩니다.",
                                                  "evidence_refs": ref, "supersedes_claim_id": None, "change_reason": None}],
            "structured_source_ids": [], "rag_source_ids": [],
            "uncertainty": {"missing": [], "limitations": [], "next_checks": []},
            "questions_to_roles": ([{"role": TARGET[role], "question": f"{TARGET[role]}에게 질문", "evidence_refs": ref}]
                                   if data["phase"] == "INITIAL" else []),
            "ui_requests": [], "follow_up": None, "persona_data": persona_data,
        }


def make(llm=None, run_dir=FIX):
    store = MemoryStore()
    sender = MemorySender()
    orch = Orchestrator(store, Publisher(store, sender), llm or FakeLLM(), Prompts(),
                        FileStressSource(str(run_dir)), FileMarketStateSource(str(FIX / "market_snapshot.json")),
                        now=lambda: datetime(2026, 11, 4, 5, 0, tzinfo=timezone.utc))
    return orch, store, sender


def start_req(debate_id="dbt-1", request_id="req-1", run_id="stress_run"):
    return c.DebateRequest(type="debate_start", request_id=request_id, debate_id=debate_id, user_id="u1",
                           run_id=run_id, created_at="2026-11-04T05:00:00Z")


def run(coro):
    return asyncio.run(coro)


def types(sender):
    return [m["type"] for _, m in sender.sent]


# ---------------------------------------------------------------------------
def test_full_debate_flow():
    orch, store, sender = make()
    run(orch.handle(start_req()))
    t = types(sender)
    assert t[0] == "debate.accepted" and t[1] == "debate.evidence_ready" and t[2] == "debate.round"
    assert t[-1] == "debate.completed"
    assert t.count("message.created") == 8          # 2라운드 × 4명
    assert t.count("debate.round") == 2 and t.count("debate.summary") == 1   # 합의 → 3라운드 없음
    seqs = [m["seq"] for _, m in sender.sent]
    assert seqs == list(range(1, len(seqs) + 1))     # 빠짐없이 순서대로
    assert {g for g, _ in sender.sent} == {"debate-dbt-1"}
    spoken = [m["payload"] for _, m in sender.sent if m["type"] == "message.created"]
    # 강유나부터, 이후에는 반대를 받은 역할이 이어서 답함(가짜 모델의 반응 대상: TARGET)
    assert [p["role"] for p in spoken] == ["portfolio", "macro", "risk", "market", "portfolio", "risk", "macro", "market"]
    assert spoken[0]["stance"] == "first" and spoken[0]["phase"] == "INITIAL" and spoken[0]["reply_to"] is None
    assert spoken[1]["phase"] == "CHALLENGE" and spoken[4]["phase"] == "REBUTTAL"
    assert spoken[1]["reply_to"] == "risk" and spoken[1]["reference_message_id"] is None   # 아직 말하지 않은 상대
    assert spoken[4]["reference_message_id"] == spoken[2]["message_id"]                   # 신강호의 1라운드 발언에 답함
    ready = next(m for _, m in sender.sent if m["type"] == "debate.evidence_ready")["payload"]
    assert ready["agenda"].endswith("이 포트폴리오를 어떻게 보시나요?") and ready["d_public"]
    assert run(store.get_debate("dbt-1"))["status"] == "completed"
    # 서버가 인용 합집합으로 출처 배열을 맞춤
    first = next(m for _, m in sender.sent if m["type"] == "message.created")["payload"]
    assert len(first["structured_source_ids"]) == 2


def test_each_role_gets_only_its_evidence():
    llm = FakeLLM()
    orch, store, _ = make(llm)
    run(orch.handle(start_req()))
    seen = {d["role"]: {x["metric_id"] for x in d["D_sources"]} for name, d in llm.calls if name.startswith("persona")}
    assert any(m.startswith("intraday_") for m in seen["market"])
    assert not any(m.startswith("intraday_declining") for m in seen["macro"])
    assert "model_q10_return" in seen["risk"] and "model_q10_return" not in seen["portfolio"]
    assert "holding_value" in seen["portfolio"]
    # 충격별 기여는 거시·리스크·포트폴리오가 같이 봄 (단일 충격 질문에 합산값을 쓰지 않도록)
    assert all(any(m.startswith("model_contribution_") for m in seen[r]) for r in ("macro", "risk", "portfolio"))
    assert not any(m.startswith("model_contribution_") for m in seen["market"])


def test_redelivery_is_idempotent():
    orch, store, sender = make()
    run(orch.handle(start_req()))
    n = len(sender.sent)
    run(orch.handle(start_req()))                    # 같은 request_id 재배달
    assert len(sender.sent) == n


def test_transient_error_resumes_without_duplicates():
    llm = FakeLLM(fail={"risk": 1})
    orch, store, sender = make(llm)
    with pytest.raises(TransientError):
        run(orch.handle(start_req()))
    saved = run(store.list_messages("dbt-1"))
    assert [m["role"] for m in saved] == ["portfolio", "macro"]   # 신강호 차례 앞까지는 저장됨
    run(orch.handle(start_req()))                    # 재배달 → 신강호 차례부터 이어감
    msgs = run(store.list_messages("dbt-1"))
    assert len(msgs) == len({m["message_id"] for m in msgs})
    assert types(sender).count("message.created") == 8
    assert run(store.get_debate("dbt-1"))["status"] == "completed"


def test_final_attempt_marks_role_failed_and_finishes():
    llm = FakeLLM(fail={"risk": None})
    orch, store, sender = make(llm)
    run(orch.handle(start_req(), final_attempt=True))
    done = [m for _, m in sender.sent if m["type"] == "debate.completed"][0]
    assert done["payload"]["failed_roles"] == ["risk"]
    assert "message.failed" in types(sender)


def test_unknown_evidence_id_is_rejected_after_one_repair():
    llm = FakeLLM(bad={"macro"})
    orch, store, sender = make(llm)
    run(orch.handle(start_req()))
    macro_calls = [d for n, d in llm.calls if n == "persona_macro" and d["round_id"] == "r1-t2"]
    assert len(macro_calls) == 2 and "format_errors" in macro_calls[1]
    failed = [m for m in run(store.list_messages("dbt-1")) if m["role"] == "macro"][0]
    assert failed["status"] == "failed" and "D9999" in failed["error"]


def test_internal_id_leak_is_rejected():
    orch, store, _ = make(FakeLLM(leak={"market"}))
    run(orch.handle(start_req()))
    m = [m for m in run(store.list_messages("dbt-1")) if m["role"] == "market"][0]
    assert m["status"] == "failed" and "내부 ID" in m["error"]


def test_user_question_after_debate():
    llm = FakeLLM()
    orch, store, sender = make(llm)
    run(orch.handle(start_req()))
    q = c.DebateRequest(type="user_question", request_id="req-2", debate_id="dbt-1", user_id="u1",
                        run_id="stress_run", created_at="2026-11-04T05:05:00Z",
                        question=c.UserQuestion(question_id="Q1", text="금리 충격만 보면?", target_roles=["macro", "risk"]))
    run(orch.handle(q))
    answers = [m["payload"] for _, m in sender.sent if m["type"] == "message.created" and m["payload"]["phase"] == "USER_ANSWER"]
    assert [a["role"] for a in answers] == ["macro", "risk"] and all(a["question_id"] == "Q1" for a in answers)
    call = [d for n, d in llm.calls if n == "persona_macro" and d["phase"] == "USER_ANSWER"][0]
    assert call["prior_claims"] and len(call["recent_history"]) <= 6


def test_prepare_only_freezes_evidence_before_answering():
    llm = FakeLLM()
    orch, store, sender = make(llm)
    run(orch.handle(start_req().model_copy(update={"prepare_only": True})))
    assert types(sender) == ["debate.accepted", "debate.evidence_ready", "debate.completed"]
    assert not llm.calls
    assert run(store.get_debate("dbt-1"))["evidence_bundle_id"]

    question = c.DebateRequest(
        type="user_question", request_id="req-2", debate_id="dbt-1", user_id="u1", run_id="stress_run",
        created_at="2026-11-04T05:05:00Z",
        question=c.UserQuestion(question_id="Q1", text="금리 충격만 보면?", target_roles=["risk"]),
    )
    run(orch.handle(question))
    answers = [event["payload"] for _, event in sender.sent if event["type"] == "message.created"]
    assert [(answer["role"], answer["question_id"], answer["phase"]) for answer in answers] == [
        ("risk", "Q1", "USER_ANSWER")
    ]


def test_missing_stress_run_fails_debate():
    orch, store, sender = make()
    run(orch.handle(start_req(run_id="no-such-run")))
    assert types(sender)[-1] == "debate.failed"
    assert run(store.get_debate("dbt-1"))["status"] == "failed"


# --- worker.process -------------------------------------------------------
class FakeReceiver:
    def __init__(self):
        self.done = []

    async def complete_message(self, m): self.done.append("complete")
    async def abandon_message(self, m): self.done.append("abandon")
    async def dead_letter_message(self, m, reason, error_description): self.done.append(f"dlq:{reason}")


def sb_msg(body, session_id="dbt-1", message_id="req-1", delivery_count=1):
    return _Msg(body, session_id, message_id, delivery_count)


class _Msg:
    def __init__(self, body, session_id, message_id, delivery_count):
        self.body, self.session_id, self.message_id, self.delivery_count = body, session_id, message_id, delivery_count

    def __str__(self):
        return self.body


def test_worker_dead_letters_bad_messages_and_abandons_transient():
    orch, _, _ = make(FakeLLM(fail={"risk": 1}))
    r = FakeReceiver()
    run(worker.process(r, sb_msg("not json"), orch, 5))
    run(worker.process(r, sb_msg(start_req().model_dump_json(), session_id="other"), orch, 5))
    run(worker.process(r, sb_msg(start_req().model_dump_json()), orch, 5))       # 1회째 일시 장애
    run(worker.process(r, sb_msg(start_req().model_dump_json(), delivery_count=2), orch, 5))
    assert r.done == ["dlq:invalid_request", "dlq:id_mismatch", "abandon", "complete"]


def test_numbers_in_text_must_match_evidence():
    import validate as v
    evidence = [
        {"id": "D1", "value": -2.134, "unit": "%"},
        {"id": "D2", "value": -1.4, "unit": "%p"},
        {"id": "D3", "value": 100, "unit": "bp"},
        {"id": "D4", "value": 0.65, "unit": "ratio"},
        {"id": "D5", "value": -85327.3, "unit": "KRW"},
    ]
    ok = "금리 +100bp 가정에서 중심 수익률은 -2.1%, 금리 기여는 -1.4%p입니다. 하락 종목은 65%, 손실은 약 8.5만 원입니다. 하위 10% 기준입니다."
    assert v.unsupported_numbers(ok, evidence) == []
    assert v.unsupported_numbers("-2.909% 하락", [{"id": "D9", "value": -2.909511766, "unit": "%"}]) == []   # 버림
    assert v.unsupported_numbers("중심 수익률은 -3.5%이고 손실은 12억 원입니다.", evidence) == ["-3.5%", "12억 원"]


def test_evidence_items_have_korean_labels():
    import evidence as ev
    assert ev.label_for("conditional_center_return") == "시나리오 예상 수익률"
    assert ev.label_for("intraday_signal_breadth_drop").startswith("장중 시장 경고 신호")
    assert ev.label_for("unknown_metric") == "unknown_metric"


def test_previous_close_evidence_for_held_assets():
    import evidence as ev
    stress = {"run_id": "r1", "assets": [{"asset": "005930", "name": "삼성전자", "conditional_center_return_pct": -1.0,
                                          "holding_krw_example": 1000000}]}
    snap = {"snapshot_id": "s1", "as_of": "2026-11-06T10:00:00+09:00",
            "market": {"mean_return_since_previous_close_pct": -0.8, "previous_close_coverage": 1.0},
            "assets": [{"asset_id": "005930", "return_since_previous_close_pct": -1.2, "return_since_open_pct": -0.5},
                       {"asset_id": "000660", "return_since_previous_close_pct": 0.3}],
            "sectors": [{"sector_id": "semis", "mean_return_since_previous_close_pct": -0.9}]}
    b = ev.build_bundle("d1", stress, snap)
    items = {(d["metric_id"], d.get("asset_id")): d for d in b["D_sources"]}
    asset = items[("intraday_asset_return_since_previous_close", "005930")]
    assert asset["value"] == -1.2 and asset["label"] == "장중 종목 전일 종가 대비 수익률"
    assert set(asset["role_scope"]) == {"market", "portfolio"}
    assert ("intraday_asset_return_since_previous_close", "000660") not in items   # 보유하지 않은 종목은 제외
    assert items[("intraday_mean_return_since_previous_close", None)]["previous_close_coverage"] == 1.0
    assert ("intraday_sector_mean_return_since_previous_close", None) in items
    assert len({d["record_id"] for d in b["D_sources"]}) == len(b["D_sources"])


def test_saved_analysis_uses_its_own_market_snapshot():
    """웹 분석 결과(run에 market_snapshot이 붙어 옴)는 분석 시점 스냅샷으로 토론하고 현재 스냅샷을 다시 읽지 않음."""
    orch, store, sender = make()
    base = json.loads((FIX / "stress_run.json").read_text(encoding="utf-8"))
    pinned = json.loads((FIX / "market_snapshot.json").read_text(encoding="utf-8"))
    pinned["snapshot_id"] = "rt-pinned-at-analysis"

    class SavedRun:
        async def get_run(self, run_id):
            return {**base, "run_id": run_id, "market_snapshot": pinned}

    class NoCurrent:
        async def get_snapshot(self, snapshot_id):
            raise AssertionError("현재 스냅샷을 읽으면 안 됨")

    orch.stress, orch.market = SavedRun(), NoCurrent()
    run(orch.handle(start_req(run_id="a-saved")))
    ready = next(m for _, m in sender.sent if m["type"] == "debate.evidence_ready")
    assert ready["payload"]["snapshot_id"] == "rt-pinned-at-analysis"
    assert types(sender)[-1] == "debate.completed"


def test_scheduled_daily_run_uses_snapshot_at_meeting_time():
    """정시 회의용 하루 결과(s-..., 장중 스냅샷 없이 저장)는 회의 시각의 최신 장중 상태로 토론함."""
    orch, store, sender = make()
    base = json.loads((FIX / "stress_run.json").read_text(encoding="utf-8"))
    now = json.loads((FIX / "market_snapshot.json").read_text(encoding="utf-8"))
    now["snapshot_id"] = "rt-at-1300"
    asked = []

    class DailyRun:
        async def get_run(self, run_id):
            return {**base, "run_id": run_id, "market_snapshot": None}

    class Current:
        async def get_snapshot(self, snapshot_id):
            asked.append(snapshot_id)
            return now

    orch.stress, orch.market = DailyRun(), Current()
    req = c.DebateRequest(type="debate_start", request_id="s-1300-start", debate_id="s-20261104-1300-x", user_id="u1",
                          trigger="scheduled", scheduled_slot="1300", run_id="s-20261104-abc",
                          created_at="2026-11-04T04:00:00Z")
    run(orch.handle(req))
    ready = next(m for _, m in sender.sent if m["type"] == "debate.evidence_ready")
    assert asked == [None] and ready["payload"]["snapshot_id"] == "rt-at-1300"
    assert types(sender)[-1] == "debate.completed"


class SilentLLM(FakeLLM):
    """프롬프트 V1.6 24절: 할 말이 없는 역할은 화면 문장을 모두 비운 JSON을 냄."""
    def __init__(self, silent):
        super().__init__(); self.silent = silent
    async def complete(self, system, user, schema, schema_name):
        out = await super().complete(system, user, schema, schema_name)
        if schema_name != "debate_summary" and json.loads(user)["role"] in self.silent:
            out.update(summary_text="", display_text="", tts_text="", claims=[], structured_source_ids=[],
                       rag_source_ids=[], questions_to_roles=[], ui_requests=[], follow_up=None)
            out["persona_data"] = {k: [] for k in out["persona_data"]}
        return out


def test_silent_role_is_marked_and_left_out_of_summary():
    """프롬프트는 이제 침묵하지 않게 하지만, 모델이 빈 문장을 내면 화면·요약에서 빼는 처리는 남겨 둠."""
    llm = SilentLLM({"portfolio"})
    orch, store, sender = make(llm)
    run(orch.handle(start_req()))
    created = [m["payload"] for _, m in sender.sent if m["type"] == "message.created"]
    silent = [p for p in created if p["silent"]]
    assert {p["role"] for p in silent} == {"portfolio"} and all(not p["display_text"] for p in silent)
    summary_call = next(d for name, d in llm.calls if name == "debate_summary")
    assert "portfolio" not in {m["role"] for m in summary_call["messages"]}
    assert summary_call["silent_roles"] == ["portfolio"]
    assert types(sender)[-1] == "debate.completed"


def test_round_three_only_for_open_issue_roles_when_not_converged():
    llm = FakeLLM(converged=False)
    orch, store, sender = make(llm)
    run(orch.handle(start_req()))
    rounds = [m["payload"] for _, m in sender.sent if m["type"] == "debate.round"]
    assert [r["round"] for r in rounds] == [1, 2, 3]
    assert rounds[2]["speakers"] == ["macro", "risk"] and rounds[2]["issue"] == "하방 폭"
    r3 = [m["payload"] for _, m in sender.sent if m["type"] == "message.created" and m["payload"]["round_id"].startswith("r3")]
    assert sorted(p["role"] for p in r3) == ["macro", "risk"]
    modes = [d["mode"] for n, d in llm.calls if n == "debate_summary"]
    assert modes == ["checkpoint", "final"]
    assert types(sender).count("debate.summary") == 1 and types(sender)[-1] == "debate.completed"
    n = len(sender.sent)
    run(orch.handle(start_req()))                    # 재배달해도 같은 회의
    assert len(sender.sent) == n


def test_revised_view_is_kept_and_reported_by_moderator():
    llm = FakeLLM(revise={"macro"})
    orch, store, sender = make(llm)
    run(orch.handle(start_req()))
    macro_r2 = [m["payload"] for _, m in sender.sent if m["type"] == "message.created"
                and m["payload"]["role"] == "macro" and m["payload"]["phase"] == "REBUTTAL"][0]
    assert macro_r2["stance"] == "revise" and macro_r2["view_status"] == "revised"
    summary = next(m["payload"] for _, m in sender.sent if m["type"] == "debate.summary")
    assert [v["role"] for v in summary["changed_views"]] == ["macro"]
    assert summary["summary_text"].startswith("결과")


def test_next_speaker_follows_disagreement_then_order():
    from orchestrator import next_speaker
    said = lambda role, stance, to: {"status": "published", "role": role, "output": {"stance": stance, "reply_to": to}}
    assert next_speaker(["macro", "market", "risk"], said("portfolio", "first", None)) == "macro"
    assert next_speaker(["market", "risk"], said("macro", "disagree", "risk")) == "risk"
    assert next_speaker(["market", "risk"], said("macro", "agree", "risk")) == "market"
    assert next_speaker(["portfolio", "macro"], said("portfolio", "partial", "risk")) == "macro"   # 같은 사람 연속 금지


def test_stance_needs_reply_target():
    import validate as v
    import copy as cp
    orch, store, sender = make()
    run(orch.handle(start_req()))
    m = next(x for x in run(store.list_messages("dbt-1")) if x["phase"] == "CHALLENGE")
    out = cp.deepcopy(m["output"]); out["reply_to"] = None
    ok, errors = v.check_persona({**out, "schema_version": 2, "context_version": "cv", "tts_text": ""}, role=m["role"],
                                 phase="CHALLENGE", context_version="cv", allowed_ids={"D1", "D2", "D3", "D4", "D5", "D6"})
    assert ok is None and any("reply_to" in e for e in errors)


def test_summary_rejected_by_must_be_another_role():
    from validate import check_summary
    base = {"summary_text": "결과 소폭 이익으로 생각됩니다.", "converged": True, "open_issue_roles": [],
            "accepted": [], "changed_views": [], "agreements": [], "disagreements": [], "next_checks": [],
            "rejected": [{"statement": "현대차가 결과를 정한다", "role": "portfolio", "message_id": "m1",
                          "rejected_by": "risk", "reason": "손실이 한 종목에 몰려 있다"}]}
    out, errs = check_summary(base, {"m1"})
    assert out and not errs
    bad = {**base, "rejected": [{**base["rejected"][0], "rejected_by": "portfolio"}]}
    out, errs = check_summary(bad, {"m1"})
    assert out is None and "rejected_by" in errs[0]


def test_summary_rejects_raw_values_long_text_and_missing_revision():
    from validate import check_summary
    base = {"summary_text": "결과 소폭 이익으로 생각됩니다.", "converged": True, "open_issue_roles": [],
            "accepted": [], "rejected": [], "agreements": [], "disagreements": [], "next_checks": [],
            "changed_views": [{"role": "macro", "before": "환율이 결과를 움직인다", "after": "종목별 차이도 크다",
                               "reason": "근거를 받아들였다", "message_id": "m1"}]}
    assert check_summary(base, {"m1"}, revised_roles={"macro"})[0]
    assert check_summary({**base, "summary_text": "결과 검증 여부가 false라서 어렵습니다."}, {"m1"})[0] is None
    assert check_summary({**base, "summary_text": "결과 " + "가" * 400}, {"m1"})[0] is None
    out, errs = check_summary(base, {"m1"}, revised_roles={"macro", "risk"})
    assert out is None and "risk" in errs[0]


def test_bundle_has_no_raw_flags_or_internal_time_notation():
    import evidence as ev
    stress = json.loads((FIX / "stress_run.json").read_text(encoding="utf-8"))
    snap = json.loads((FIX / "market_snapshot.json").read_text(encoding="utf-8"))
    b = ev.build_bundle("d1", stress, snap)
    for x in b["D_sources"]:
        assert not isinstance(x["value"], bool), x["metric_id"]
        assert not str(x.get("horizon", "")).startswith("D+"), x["horizon"]
        assert "T" not in str(x.get("as_of", "")) or ":" not in str(x.get("as_of", "")), x["as_of"]
    joint = next(x for x in b["D_sources"] if x["metric_id"] == "model_joint_support_certified")
    assert joint["flag_value"] is False and "일반화하기 어려움" in joint["value"]


def test_out_of_range_missing_is_unknown_not_empty():
    import evidence as ev
    from validate import _NO_OUT_OF_RANGE
    assert ev.out_of_range(None)[0].startswith("확인할 수 없음")
    assert ev.out_of_range([])[0].startswith("없음")
    assert ev.out_of_range(["shock_rate"]) == (["미국 10년 금리"], "list")
    stress = {"run_id": "r1", "assets": [{"asset": "005930", "name": "삼성전자", "conditional_center_return_pct": -1.0,
                                          "holding_krw_example": 1000000}]}
    b = ev.build_bundle("d1", stress, None)
    item = next(x for x in b["D_sources"] if x["metric_id"] == "outside_training_marginal_range")
    assert item["value"].startswith("확인할 수 없음")
    assert _NO_OUT_OF_RANGE.search("학습 범위를 벗어난 충격은 없습니다")
    assert _NO_OUT_OF_RANGE.search("이번 충격은 학습 범위 안입니다")
    assert not _NO_OUT_OF_RANGE.search("학습 범위 안인지는 이 결과로 확인할 수 없습니다")



class MeetingStyleLLM(FakeLLM):
    """실제 회의처럼: 1라운드 응답도 rebuttal 의도, 앞 발언 ID를 근거에 섞고, 다른 역할 근거의 수치를 인용."""
    async def complete(self, system, user, schema, schema_name):
        out = await super().complete(system, user, schema, schema_name)
        if schema_name == "debate_summary":
            return out
        data = json.loads(user)
        if data["phase"] == "CHALLENGE":
            out["intent"] = "rebuttal"
            hist = data.get("recent_history") or []
            if hist:
                out["structured_source_ids"] = [hist[-1]["message_id"]]
        if data["role"] == "macro" and data["phase"] != "INITIAL":
            out["display_text"] = f"전체 예상 수익률 {self.pf_return}%를 보시면 판단이 달라집니다."
        return out


def test_meeting_turns_accept_rebuttal_message_refs_and_other_roles_numbers():
    llm = MeetingStyleLLM()
    stress = json.loads((FIX / "stress_run.json").read_text(encoding="utf-8"))
    import evidence as evm
    bundle = evm.build_bundle("x", stress, json.loads((FIX / "market_snapshot.json").read_text(encoding="utf-8")))
    pf = next(x for x in bundle["D_sources"] if x["metric_id"] == "portfolio_center_return")
    assert "macro" not in pf["role_scope"]     # 거시경제 근거에는 없는 값을 인용하는 상황
    llm.pf_return = pf["value"]
    o, store, sender = make(llm)
    run(o.handle(start_req()))
    failed = [r for r in store.messages.values() if r["status"] == "failed"]
    assert not failed, [(r["role"], r["phase"], r["error"]) for r in failed]

def test_selected_news_reaches_roles_and_moderator_without_stress_run(monkeypatch, tmp_path):
    import selected_evidence

    url = "https://publisher.example/article"
    body = "원문에는 회사가 신규 설비 투자를 승인했다는 내용이 담겨 있습니다."

    async def resolve(selections, snapshot):
        assert snapshot is None
        assert [item.id for item in selections] == [url]
        return [{"kind": "news", "id": url, "status": "ready", "title": "설비 투자",
                 "url": url, "content_status": "article", "excerpt": body}]

    class ArticleLLM(FakeLLM):
        async def complete(self, system, user, schema, schema_name):
            response = await super().complete(system, user, schema, schema_name)
            if schema_name != "debate_summary":
                data = json.loads(user)
                refs = [source["id"] for source in data["S_sources"] if source.get("kind") == "selected_news"]
                response["claims"][0]["evidence_refs"] = refs
                for question in response["questions_to_roles"]:
                    question["evidence_refs"] = refs
            return response

    monkeypatch.setenv("DEFAULT_RUN_ID", "stress_run")
    monkeypatch.setattr(selected_evidence, "resolve", resolve)
    orch, store, sender = make(ArticleLLM(), run_dir=tmp_path)
    req = start_req().model_copy(update={"selected_sources": [c.SourceSelection(kind="news", id=url)]})
    run(orch.handle(req))
    roles = [data for kind, data in orch.llm.calls if kind != "debate_summary"]
    assert {data["role"] for data in roles} == set(c.ROLES)
    assert all(any(source["excerpt"] == body for source in data["S_sources"]) for data in roles)
    assert all(not data["D_sources"] for data in roles)
    moderator = [data for kind, data in orch.llm.calls if kind == "debate_summary"]
    assert moderator and moderator[-1]["selected_source_text"][0]["excerpt"] == body
