"""토론 실행기의 계약: 큐 메시지, 페르소나 출력, 요약 출력, Web PubSub 이벤트.

이 파일이 기준입니다. contracts/debate/*.schema.json은 `python export_contracts.py`로 여기서 생성합니다.
페르소나 출력 스키마는 Azure OpenAI structured outputs(strict)에 그대로 넣을 수 있게
모든 키를 required로 두고 additionalProperties=false로 닫습니다.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

# 페르소나 역할 코드. 화면 이름과 인물은 PERSONAS 참고.
ROLES = ("macro", "market", "risk", "portfolio")
PERSONAS = {
    "macro": {"name": "김진우", "title": "거시경제 분석가"},
    "market": {"name": "윤서연", "title": "장중 시장상태 분석가"},
    "risk": {"name": "신강호", "title": "리스크 분석가"},
    "portfolio": {"name": "강유나", "title": "포트폴리오 분석가"},
}
PHASES = ("INITIAL", "CHALLENGE", "REBUTTAL", "LIVE_REVIEW", "USER_ANSWER")
PHASE_INTENT = {
    "INITIAL": "initial_analysis",
    "CHALLENGE": "challenge",
    "REBUTTAL": "rebuttal",
    "LIVE_REVIEW": "live_review",
    "USER_ANSWER": "user_answer",
}
FALLBACK_INTENTS = ("insufficient_data", "clarify", "unsupported")


# ---------------------------------------------------------------------------
# 1. 큐 메시지 (debate-requests, 세션 큐)
#    SessionId = debate_id, MessageId = request_id 로 보냅니다.
# ---------------------------------------------------------------------------
class UserQuestion(BaseModel):
    question_id: str
    text: str = Field(min_length=1, max_length=2000)
    target_roles: list[Literal["macro", "market", "risk", "portfolio"]] = Field(min_length=1)
    reference_message_id: Optional[str] = None


class DebateRequest(BaseModel):
    """FastAPI(유저 요청)와 Functions 타이머(정시 회의)가 큐에 넣는 메시지."""
    schema_version: Literal["1.0"] = "1.0"
    type: Literal["debate_start", "user_question"]
    request_id: str                       # 중복 접수 방지 키 = Service Bus MessageId
    debate_id: str                        # = Service Bus SessionId
    user_id: str
    trigger: Literal["user", "scheduled"] = "user"
    scheduled_slot: Optional[Literal["0830", "1300", "1540"]] = None
    run_id: str                           # Stress Engine 결과 ID (같은 run이면 숫자는 고정)
    snapshot_id: Optional[str] = None     # 시장 상태 스냅샷 ID. 없으면 접수 시점 최신값으로 고정
    created_at: datetime
    question: Optional[UserQuestion] = None   # type=user_question일 때만


# ---------------------------------------------------------------------------
# 2. 페르소나 출력 (schema_version 2) — 역할별 persona_data만 다름
# ---------------------------------------------------------------------------
def _str_list(desc: str) -> dict:
    return {"type": "array", "items": {"type": "string"}, "description": desc}


def _enum(values, desc: str) -> dict:
    return {"type": "string", "enum": list(values), "description": desc}


PERSONA_DATA = {  # 프롬프트 V1.5 키 (portfolio의 tail_contributions → pnl_contributions, VaR/ES 미제공이라서)
    "macro": {
        "scenario_conditions": _str_list("사용자가 정한 충격 조건과 가정(미입력 0 처리 포함)"),
        "gold_state_summary": _str_list("확정 일별 시장 상태 요약"),
        "transmission_channels": _str_list("금리·환율·유가·VIX가 종목에 닿는 경로 (인과 단정 금지)"),
        "support_range_flags": _str_list("학습 범위 밖·드문 조합 등 지원 범위 주의"),
        "next_checks": _str_list("다음에 확인할 조건"),
    },
    "market": {
        "snapshot_status": _str_list("장중 스냅샷 기준시각·장 상태·유효 종목 수·품질"),
        "market_flow": _str_list("관측 종목 평균 흐름 (5분, 시가 대비, 전일 대비)"),
        "breadth_and_sectors": _str_list("하락 종목 비율과 업종 흐름"),
        "risk_signals": _str_list("장중 경고 신호, 종목 간 상관·동반 하락"),
        "data_quality_flags": _str_list("관측 범위·품질·지연 주의사항"),
    },
    "risk": {
        "asset_distribution": _str_list("종목별 중심값과 q10/q90 (확률 승인 여부 포함)"),
        "tail_reference": _str_list("보수적 하방 참고선과 그 의미"),
        "similar_regimes": _str_list("비슷한 과거 구간의 실제 수익률·충격"),
        "model_limits": _str_list("모델 한계 (학습 범위 밖, 조합 미검증, 공표시각 미인증 등)"),
        "support_flags": _str_list("지원 범위·데이터 품질 플래그"),
    },
    "portfolio": {
        "portfolio_metrics": _str_list("전체 보유 금액, 전체 예상 손익·수익률"),
        "pnl_contributions": _str_list("예상 손익이 몰린 종목과 그 몫·비중"),
        "holding_valuation": _str_list("보유 금액 기준과 장중 가격 변화 관련 주의"),
        "risk_method": _str_list("손익 계산 방식과 해석 기준"),
        "availability_flags": _str_list("제공되지 않은 자료와 계산 범위 밖 종목"),
    },
}


def _obj(props: dict, desc: str = "") -> dict:
    o = {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}
    if desc:
        o["description"] = desc
    return o


def persona_output_schema(role: str) -> dict:
    """역할 하나의 출력 스키마 (strict)."""
    if role not in ROLES:
        raise ValueError(role)
    other_roles = [r for r in ROLES if r != role]
    claim = _obj({
        "claim_id": {"type": "string"},
        "kind": _enum(("observation", "interpretation", "hypothesis"), "관측·해석·가설"),
        "statement": {"type": "string"},
        "evidence_refs": _str_list("근거 묶음의 실제 D/S ID"),
        "supersedes_claim_id": {"type": ["string", "null"]},
        "change_reason": {"type": ["string", "null"]},
    })
    question = _obj({
        "role": _enum(other_roles, "질문 대상 역할"),
        "question": {"type": "string"},
        "evidence_refs": _str_list("근거 묶음의 실제 D/S ID"),
    })
    ui_request = _obj({
        "type": _enum(("OPEN_SOURCE_PANEL", "SUGGEST_ROLE_TARGET", "REQUIRE_CURRENT_DATA"), "앱에 제안하는 동작"),
        "refs": _str_list("OPEN_SOURCE_PANEL일 때 근거 ID, 아니면 빈 배열"),
        "role": {"type": ["string", "null"], "description": "SUGGEST_ROLE_TARGET일 때 역할"},
        "reason": {"type": ["string", "null"]},
    })
    props = {
        "schema_version": {"type": "integer", "enum": [2]},
        "context_version": {"type": "string"},
        "role": {"type": "string", "enum": [role]},
        "intent": _enum(tuple(PHASE_INTENT.values()) + FALLBACK_INTENTS, "응답 의도"),
        "response_status": _enum(("ok", "insufficient_data", "needs_clarification", "data_conflict", "unsupported"), "응답 상태"),
        "summary_text": {"type": "string", "description": "화면 요약, 80자 안팎"},
        "display_text": {"type": "string", "description": "전체 답변. 내부 ID(D1, S1) 노출 금지"},
        "tts_text": {"type": "string"},
        "view_status": _enum(("initial", "maintained", "revised", "deferred"), "관점 상태"),
        "claims": {"type": "array", "items": claim},
        "structured_source_ids": _str_list("실제 사용한 D ID"),
        "rag_source_ids": _str_list("실제 사용한 S ID"),
        "uncertainty": _obj({
            "missing": _str_list("부족한 자료"),
            "limitations": _str_list("해석 한계"),
            "next_checks": _str_list("다음 확인 조건"),
        }),
        "questions_to_roles": {"type": "array", "items": question},
        "ui_requests": {"type": "array", "items": ui_request},
        "follow_up": {"type": ["string", "null"]},
        "persona_data": _obj(PERSONA_DATA[role]),
    }
    return _obj(props, f"{PERSONAS[role]['name']} {PERSONAS[role]['title']} 응답 v2")


# ---------------------------------------------------------------------------
# 3. 요약(사회자) 출력 — 서버 소유 프롬프트
# ---------------------------------------------------------------------------
def summary_output_schema() -> dict:
    position = _obj({
        "role": _enum(ROLES, "역할"),
        "message_id": {"type": "string"},
        "stance": {"type": "string"},
    })
    return _obj({
        "summary_text": {"type": "string", "description": "회의 요약 2~4문장"},
        "agreements": {"type": "array", "items": _obj({
            "statement": {"type": "string"},
            "message_ids": _str_list("근거가 된 발언 ID"),
        })},
        "disagreements": {"type": "array", "items": _obj({
            "issue": {"type": "string"},
            "positions": {"type": "array", "items": position},
        })},
        "next_checks": _str_list("다음에 확인할 조건"),
    }, "토론 요약")


# ---------------------------------------------------------------------------
# 4. Web PubSub 이벤트 (hub=debate, group=debate-{debate_id})
#    DB에 저장(outbox)한 뒤 seq 순서로 보냅니다. 재접속 시 after_seq로 다시 받습니다.
# ---------------------------------------------------------------------------
EVENT_TYPES = (
    "debate.accepted",        # 요청 접수
    "debate.evidence_ready",  # 근거 묶음 고정 (run_id, snapshot_id, evidence_bundle_id)
    "message.created",        # 페르소나 발언 1건 (검증 통과)
    "message.failed",         # 특정 역할 발언 실패 (보류 표시용)
    "debate.summary",         # 요약
    "debate.completed",
    "debate.failed",
)


class DebateEvent(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    debate_id: str
    seq: int                  # 토론 안에서 1부터 증가
    event_id: str             # 화면 중복 표시 방지
    type: Literal[*EVENT_TYPES]
    created_at: datetime
    payload: dict


def group_name(debate_id: str) -> str:
    return f"debate-{debate_id}"
