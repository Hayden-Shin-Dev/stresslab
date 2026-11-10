"""토론 진행.

debate_start
  1. 근거 묶음 고정 (Stress Engine run + 시장 상태 스냅샷)
  2. 초기 발언: 네 역할 병렬 생성 → 검증 → 역할 순서대로 저장·공개
  3. 쟁점 반론: 초기 발언의 questions_to_roles에서 최대 2개를 골라, 질문받은 역할이 한 번 답함
  4. 요약: 사회자 프롬프트로 합의·이견 정리
user_question
  선택한 역할들이 같은 근거 묶음으로 답함 (질문 접수 때 대상·참조 발언 고정)

재처리 안전: message_id가 (토론, 라운드, 역할, 단계, 질문)으로 정해져 있어, 메시지가 다시 배달되면
이미 저장된 발언은 건너뛰고 남은 단계부터 이어서 진행합니다.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Callable, Optional

import contracts as c
import evidence as ev
import validate
from llm import LLMError
from disclosures import NoDisclosures
from news import NoNews
from sources import NotFound

log = logging.getLogger("debate.orchestrator")


class TransientError(Exception):
    """잠시 뒤 다시 하면 될 수 있는 오류 (모델·조회 서비스 장애). 메시지를 재배달시킵니다."""


def message_id(debate_id, round_id, role, phase, question_id=None) -> str:
    key = "|".join([debate_id, round_id, role, phase, question_id or ""])
    return "m-" + hashlib.sha256(key.encode()).hexdigest()[:20]


class Orchestrator:
    def __init__(self, store, publisher, llm, prompts, stress, market, *, disclosures=None, news=None,
                 max_issues: int = 2,
                 history_limit: int = 6, now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)):
        self.store, self.publisher, self.llm, self.prompts = store, publisher, llm, prompts
        self.stress, self.market = stress, market
        self.disclosures = disclosures or NoDisclosures()
        self.news = news or NoNews()
        self.max_issues, self.history_limit, self.now = max_issues, history_limit, now

    # ------------------------------------------------------------------ 입구
    async def handle(self, req: c.DebateRequest, *, final_attempt: bool = False) -> None:
        await self.store.ensure_debate(req)
        if not await self.store.claim_request(req):
            log.info("이미 처리한 요청 %s", req.request_id)
            return
        try:
            if req.type == "debate_start":
                await self._debate(req, final_attempt)
            else:
                await self._question(req, final_attempt)
        finally:
            await self.publisher.flush(req.debate_id)
        await self.store.finish_request(req.request_id)

    # ------------------------------------------------------------------ 토론
    async def _debate(self, req, final_attempt):
        d = await self.store.get_debate(req.debate_id)
        if d["status"] in ("completed", "failed"):
            return
        await self.store.add_event(d["debate_id"], f"{d['debate_id']}:accepted", "debate.accepted",
                                   {"trigger": d["trigger"], "run_id": d["run_id"]})
        await self.publisher.flush(d["debate_id"])

        try:
            bundle = await self._bundle(d)
        except NotFound as e:
            await self._fail(d["debate_id"], f"근거 없음: {e}")
            return
        await self.store.update_debate(d["debate_id"], status="running")

        initial = await self._round(d, bundle, "r1", "INITIAL",
                                    [dict(role=r, user_message=self._initial_prompt(bundle)) for r in c.ROLES],
                                    final_attempt)
        issues = select_issues(initial, self.max_issues)
        if issues:
            calls = []
            for i, it in enumerate(issues, 1):
                asker = c.PERSONAS[it["asker_role"]]
                target_initial = initial.get(it["target_role"])
                calls.append(dict(
                    role=it["target_role"], question_id=f"issue{i}",
                    reference_message_id=it["asker_message_id"],
                    user_message=f"{asker['name']} {asker['title']}의 질문에 답하십시오: {it['question']}",
                    prior_claims=_claims(target_initial),
                    recent_history=[h for h in (_history(initial[it["asker_role"]]), _history(target_initial)) if h],
                ))
            await self._round(d, bundle, "r2", "REBUTTAL", calls, final_attempt)
        await self._summary(d, bundle, final_attempt)

        msgs = await self.store.list_messages(d["debate_id"])
        await self.store.update_debate(d["debate_id"], status="completed")
        await self.store.add_event(d["debate_id"], f"{d['debate_id']}:completed", "debate.completed", {
            "published": sum(m["status"] == "published" for m in msgs),
            "failed_roles": sorted({m["role"] for m in msgs if m["status"] == "failed"}),
        })

    async def _bundle(self, d) -> dict:
        if d.get("evidence_bundle_id"):
            return await self.store.get_bundle(d["evidence_bundle_id"])
        try:
            run = await self.stress.get_run(d["run_id"])
            snap = await self.market.get_snapshot(d.get("snapshot_id"))
        except NotFound:
            raise
        except Exception as e:
            raise TransientError(f"근거 조회 실패: {type(e).__name__}") from e
        # 공시는 실패해도 토론을 막지 않습니다(DartDisclosures가 오류를 상태로 돌려줌).
        # 공시·뉴스는 동시에 조회하고, 실패해도 토론을 막지 않습니다(각 소스가 오류를 상태로 돌려줌).
        now = self.now()
        disc, nws = await asyncio.gather(self.disclosures.recent(ev.bundle_assets(run), now),
                                         self.news.recent(ev.bundle_asset_names(run), now), return_exceptions=True)
        if isinstance(disc, BaseException):
            log.error("공시 조회 중 예외, 공시 없이 진행: %r", disc)
            disc = {"status": "failed", "window": None, "items": [], "errors": [type(disc).__name__]}
        if isinstance(nws, BaseException):
            log.error("뉴스 조회 중 예외, 뉴스 없이 진행: %r", nws)
            nws = {"status": "failed", "window": None, "items": [], "errors": [type(nws).__name__]}
        bundle = ev.build_bundle(d["debate_id"], run, snap, disc, nws)
        await self.store.save_bundle(bundle)
        await self.store.update_debate(d["debate_id"], evidence_bundle_id=bundle["evidence_bundle_id"],
                                       snapshot_id=bundle["snapshot_id"])
        await self.store.add_event(d["debate_id"], f"{d['debate_id']}:evidence", "debate.evidence_ready", {
            "run_id": bundle["run_id"], "snapshot_id": bundle["snapshot_id"],
            "evidence_bundle_id": bundle["evidence_bundle_id"], "state_date": bundle["state_date"],
            "omitted_assets": bundle["omitted_assets"], "d_count": len(bundle["D_sources"]),
            "disclosure_count": sum(s.get("kind") == "dart_disclosure" for s in bundle["S_sources"]),
            "disclosure_status": bundle["disclosure_status"]["status"],
            "news_status": bundle["news_status"]["status"],
            # Bing 이용 조건: 화면에 출처 URL과 검색어 URL을 보여줘야 합니다.
            "web_news": [{"source_id": s["id"], "asset_id": s["asset_id"], "citations": s["citations"],
                          "search_query_urls": s["search_query_urls"]}
                         for s in bundle["S_sources"] if s.get("kind") == "web_news"],
        })
        await self.publisher.flush(d["debate_id"])
        return bundle

    @staticmethod
    def _initial_prompt(bundle) -> str:
        return ("제공된 시나리오와 근거로 당신의 관점에서 초기 분석을 하십시오. "
                "다른 역할에게 확인할 점이 있으면 questions_to_roles에 하나만 적으십시오.")

    # ------------------------------------------------------------------ 질문
    async def _question(self, req, final_attempt):
        d = await self.store.get_debate(req.debate_id)
        q = req.question
        if not d.get("evidence_bundle_id") or q is None:
            for role in (q.target_roles if q else []):
                await self.store.add_event(d["debate_id"], f"{req.request_id}:{role}:not_ready", "message.failed",
                                           {"role": role, "question_id": q.question_id, "reason": "debate_not_ready"})
            return
        bundle = await self.store.get_bundle(d["evidence_bundle_id"])
        published = [m for m in await self.store.list_messages(d["debate_id"]) if m["status"] == "published"]
        history = [_history(m) for m in published if m["role"] in c.ROLES][-self.history_limit:]
        calls = []
        for role in q.target_roles:
            mine = [m for m in published if m["role"] == role]
            calls.append(dict(role=role, question_id=q.question_id, reference_message_id=q.reference_message_id,
                              user_message=q.text, prior_claims=_claims(mine[-1] if mine else None),
                              recent_history=history))
        await self._round(d, bundle, f"q-{q.question_id}", "USER_ANSWER", calls, final_attempt)

    # ------------------------------------------------------------------ 라운드
    async def _round(self, d, bundle, round_id, phase, calls, final_attempt) -> dict:
        """calls를 병렬로 생성하고, 검증을 통과한 순서와 무관하게 calls 순서대로 저장·공개합니다."""
        async def one(call):
            mid = message_id(d["debate_id"], round_id, call["role"], phase, call.get("question_id"))
            existing = await self.store.get_message(mid)
            if existing:
                return existing, False
            return await self._persona(d, bundle, round_id, phase, mid, **call), True

        results = await asyncio.gather(*(one(cl) for cl in calls), return_exceptions=True)
        by_role, transient = {}, None
        for call, res in zip(calls, results):
            if isinstance(res, BaseException):
                if isinstance(res, TransientError) and not final_attempt:
                    transient = transient or res
                    continue
                res = (self._failed_msg(d, round_id, phase, call, f"{type(res).__name__}: {str(res)[:200]}"), True)
            msg, is_new = res
            if is_new:
                await self._save(msg)
            by_role[call["role"]] = msg
        if transient:   # 성공한 발언은 저장됐으니, 재배달 때 나머지만 다시 만듭니다.
            raise transient
        return by_role

    async def _persona(self, d, bundle, round_id, phase, mid, *, role, user_message, question_id=None,
                       reference_message_id=None, prior_claims=None, recent_history=None) -> dict:
        D, S = ev.for_role(bundle, role)
        context_version = f"{bundle['evidence_bundle_id']}:{round_id}"
        payload = {
            "schema_version": 2, "role": role, "phase": phase,
            "meeting_id": d["debate_id"], "participation_scope_id": d["user_id"], "round_id": round_id,
            "context_version": context_version, "cutoff": self.now().isoformat(),
            "result_version": bundle["run_id"], "live_snapshot_id": bundle["snapshot_id"],
            "evidence_bundle_id": bundle["evidence_bundle_id"], "reference_message_id": reference_message_id,
            "question_id": question_id, "user_message": user_message, "voice_enabled": False,
            "prior_claims": prior_claims or [], "recent_history": recent_history or [],
            "current_datetime": self.now().isoformat(), "user_locale": "ko-KR", "input_mode": "text",
            "memory_consent": False, "consented_memory": {}, "session_summary": None,
            "query_plan": {"allowed_tools": [], "purpose": "서버가 고정한 근거 묶음만 사용"},
            "D_sources": D, "S_sources": S,
        }
        allowed = ev.ids_for_role(bundle, role)
        schema = c.persona_output_schema(role)
        errors = []
        for attempt in range(2):   # 형식 복구는 같은 입력으로 한 번만
            user = json.dumps(payload if attempt == 0 else {**payload, "format_errors": errors},
                              ensure_ascii=False, default=str)
            try:
                out = await self.llm.complete(self.prompts.persona[role], user, schema, f"persona_{role}")
            except LLMError as e:
                errors = [str(e)]
                continue
            except Exception as e:
                raise TransientError(f"모델 호출 실패: {type(e).__name__}") from e
            ok, errors = validate.check_persona(out, role=role, phase=phase, context_version=context_version,
                                                allowed_ids=allowed, evidence=D)
            if ok:
                return self._msg(d, round_id, phase, role, mid, question_id, reference_message_id, "published", ok)
            log.warning("검증 실패 %s %s 시도%d: %s", role, phase, attempt + 1, errors)
        return self._msg(d, round_id, phase, role, mid, question_id, reference_message_id, "failed", None,
                         "; ".join(errors)[:500])

    # ------------------------------------------------------------------ 요약
    async def _summary(self, d, bundle, final_attempt):
        mid = message_id(d["debate_id"], "summary", "moderator", "SUMMARY")
        if await self.store.get_message(mid):
            return
        msgs = [m for m in await self.store.list_messages(d["debate_id"]) if m["role"] in c.ROLES]
        published = [m for m in msgs if m["status"] == "published"]
        shocks = {x["metric_id"]: f"{x['value']}{x['unit']}" for x in bundle["D_sources"]
                  if x["metric_id"].startswith("scenario_shock_")}
        summary_input = {
            "debate_id": d["debate_id"], "scenario": shocks,
            "failed_roles": sorted({m["role"] for m in msgs if m["status"] == "failed"}),
            "messages": [{"message_id": m["message_id"], "role": m["role"], "phase": m["phase"],
                          "summary_text": m["output"]["summary_text"], "view_status": m["output"]["view_status"],
                          "response_status": m["output"]["response_status"],
                          "claims": [{"kind": cl["kind"], "statement": cl["statement"]} for cl in m["output"]["claims"]]}
                         for m in published],
        }
        ids = {m["message_id"] for m in published}
        out, errors = None, ["발언 없음"] if not published else []
        for attempt in range(2 if published else 0):
            try:
                user = json.dumps(summary_input if attempt == 0 else {**summary_input, "format_errors": errors},
                                  ensure_ascii=False)
                raw = await self.llm.complete(self.prompts.moderator, user, c.summary_output_schema(),
                                              "debate_summary")
            except LLMError as e:
                errors = [str(e)]
                continue
            except Exception as e:
                if final_attempt:
                    errors = [type(e).__name__]
                    break
                raise TransientError(f"요약 호출 실패: {type(e).__name__}") from e
            out, errors = validate.check_summary(raw, ids)
            if out:
                break
        msg = {"message_id": mid, "debate_id": d["debate_id"], "round_id": "summary", "phase": "SUMMARY",
               "role": "moderator", "question_id": None, "reference_message_id": None,
               "status": "published" if out else "failed", "output": out,
               "error": None if out else "; ".join(errors)[:500],
               "model_deployment": self.llm.deployment, "prompt_version": self.prompts.version}
        await self.store.save_message(msg, "debate.summary", {"message_id": mid, "status": msg["status"],
                                                              **(out or {"error": "요약을 만들지 못했습니다"})})
        await self.publisher.flush(d["debate_id"])

    # ------------------------------------------------------------------ 저장·도우미
    def _msg(self, d, round_id, phase, role, mid, question_id, reference_message_id, status, output, error=None):
        return {"message_id": mid, "debate_id": d["debate_id"], "round_id": round_id, "phase": phase,
                "role": role, "question_id": question_id, "reference_message_id": reference_message_id,
                "status": status, "output": output, "error": error,
                "model_deployment": self.llm.deployment, "prompt_version": self.prompts.version}

    def _failed_msg(self, d, round_id, phase, call, error):
        mid = message_id(d["debate_id"], round_id, call["role"], phase, call.get("question_id"))
        return self._msg(d, round_id, phase, call["role"], mid, call.get("question_id"),
                         call.get("reference_message_id"), "failed", None, error)

    async def _save(self, msg):
        meta = {"message_id": msg["message_id"], "role": msg["role"], **c.PERSONAS[msg["role"]],
                "phase": msg["phase"], "round_id": msg["round_id"], "question_id": msg["question_id"],
                "reference_message_id": msg["reference_message_id"]}
        if msg["status"] == "published":
            o = msg["output"]
            payload = {**meta, **{k: o[k] for k in o if k not in ("schema_version", "context_version", "tts_text")}}
            await self.store.save_message(msg, "message.created", payload)
        else:
            await self.store.save_message(msg, "message.failed", {**meta, "reason": "검증 또는 생성 실패"})
        await self.publisher.flush(msg["debate_id"])

    async def _fail(self, debate_id, reason):
        await self.store.update_debate(debate_id, status="failed", error=reason[:500])
        await self.store.add_event(debate_id, f"{debate_id}:failed", "debate.failed", {"reason": reason[:200]})


def select_issues(initial: dict, max_issues: int) -> list[dict]:
    """초기 발언의 questions_to_roles에서 쟁점을 고릅니다.
    역할 순서대로 보고, 질문받는 역할마다 하나, 같은 (질문자, 대상) 쌍은 하나, 최대 max_issues개.
    질문받는 역할의 초기 발언이 실패했으면 건너뜁니다."""
    issues, targets = [], set()
    for role in c.ROLES:
        m = initial.get(role)
        if not m or m["status"] != "published":
            continue
        for q in m["output"]["questions_to_roles"]:
            t = q["role"]
            if t == role or t in targets or not initial.get(t) or initial[t]["status"] != "published":
                continue
            issues.append({"asker_role": role, "asker_message_id": m["message_id"], "target_role": t,
                           "question": q["question"], "evidence_refs": q["evidence_refs"]})
            targets.add(t)
            break   # 질문자당 하나
        if len(issues) >= max_issues:
            break
    return issues


def _claims(msg: Optional[dict]) -> list:
    if not msg or msg["status"] != "published":
        return []
    return [{"claim_id": cl["claim_id"], "kind": cl["kind"], "statement": cl["statement"],
             "evidence_refs": cl["evidence_refs"], "message_id": msg["message_id"]} for cl in msg["output"]["claims"]]


def _history(msg: Optional[dict]) -> dict:
    if not msg or msg["status"] != "published":
        return {}
    return {"message_id": msg["message_id"], "role": msg["role"], "phase": msg["phase"],
            "summary_text": msg["output"]["summary_text"]}
