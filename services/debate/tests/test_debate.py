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

    def __init__(self, fail=None, bad=None, leak=None):
        self.calls = []
        self.fail = fail or {}      # role -> 남은 일시 장애 횟수 (None이면 계속)
        self.bad = bad or set()     # 없는 근거 ID를 인용할 역할
        self.leak = leak or set()   # 화면 문장에 내부 ID를 쓸 역할

    async def complete(self, system, user, schema, schema_name):
        data = json.loads(user)
        self.calls.append((schema_name, data))
        if schema_name == "debate_summary":
            ids = [m["message_id"] for m in data["messages"]]
            return {"summary_text": "요약입니다.", "agreements": [{"statement": "환율 충격 영향 확인", "message_ids": ids[:2]}],
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
        return {
            "schema_version": 2, "context_version": data["context_version"], "role": role, "intent": intent,
            "response_status": "ok", "summary_text": f"{role} 요약", "display_text": text, "tts_text": "",
            "view_status": "initial", "claims": [{"claim_id": "c1", "kind": "observation", "statement": "관측됩니다.",
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
    assert t[0] == "debate.accepted" and t[1] == "debate.evidence_ready" and t[-1] == "debate.completed"
    assert t.count("message.created") == 6          # 초기 4 + 반론 2
    assert t.count("debate.summary") == 1
    seqs = [m["seq"] for _, m in sender.sent]
    assert seqs == list(range(1, len(seqs) + 1))     # 빠짐없이 순서대로
    assert {g for g, _ in sender.sent} == {"debate-dbt-1"}
    initial_roles = [m["payload"]["role"] for _, m in sender.sent if m["type"] == "message.created"][:4]
    assert initial_roles == list(c.ROLES)            # 역할 순서대로 공개
    assert run(store.get_debate("dbt-1"))["status"] == "completed"
    # 서버가 인용 합집합으로 출처 배열을 맞춤
    first = next(m for _, m in sender.sent if m["type"] == "message.created")["payload"]
    assert first["structured_source_ids"] == ["D1", "D2"]


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
    assert {m["role"] for m in saved} == {"macro", "market", "portfolio"}   # 성공분은 저장됨
    run(orch.handle(start_req()))                    # 재배달
    msgs = run(store.list_messages("dbt-1"))
    assert len(msgs) == len({m["message_id"] for m in msgs})
    assert types(sender).count("message.created") == 6
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
    macro_calls = [d for n, d in llm.calls if n == "persona_macro" and d["phase"] == "INITIAL"]
    assert len(macro_calls) == 2 and "format_errors" in macro_calls[1]
    failed = [m for m in run(store.list_messages("dbt-1")) if m["role"] == "macro"][0]
    assert failed["status"] == "failed" and "D9999" in failed["error"]


def test_internal_id_leak_is_rejected():
    orch, store, _ = make(FakeLLM(leak={"market"}))
    run(orch.handle(start_req()))
    m = [m for m in run(store.list_messages("dbt-1")) if m["role"] == "market" and m["phase"] == "INITIAL"][0]
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
