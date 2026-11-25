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
            d["target_roles"] = list(dict.fromkeys(req.target_roles))
            bundle = await self._bundle(d, req.selected_sources)
        except NotFound as e:
            await self._fail(d["debate_id"], f"근거 없음: {e}")
            return
        await self.store.update_debate(d["debate_id"], status="running")

        await self._meeting(d, bundle, final_attempt)

        msgs = await self.store.list_messages(d["debate_id"])
        await self.store.update_debate(d["debate_id"], status="completed")
        await self.store.add_event(d["debate_id"], f"{d['debate_id']}:completed", "debate.completed", {
            "published": sum(m["status"] == "published" for m in msgs),
            "failed_roles": sorted({m["role"] for m in msgs if m["status"] == "failed"}),
        })

    async def _bundle(self, d, selections=()) -> dict:
        if d.get("evidence_bundle_id"):
            return await self.store.get_bundle(d["evidence_bundle_id"])
        try:
            run = await self.stress.get_run(d["run_id"])
            if "market_snapshot" in run and not d.get("snapshot_id"):
                # 웹 분석 결과: 분석할 때 본 장중 스냅샷을 그대로 씀(없으면 장중 근거 없이 진행)
                run = dict(run)
                snap = run.pop("market_snapshot")
                if snap is None and d["trigger"] == "scheduled":
                    # 정시 회의용 하루 결과(s-...)는 장중 스냅샷 없이 저장됩니다. 회의 시각의 최신 장중 상태를 씁니다.
                    snap = await self.market.get_snapshot(None)
            else:
                snap = await self.market.get_snapshot(d.get("snapshot_id"))
        except NotFound:
            raise
        except Exception as e:
            raise TransientError(f"근거 조회 실패: {type(e).__name__}") from e
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
        from selected_evidence import resolve
        selected = await resolve(selections, snap)
        bundle = ev.build_bundle(d["debate_id"], run, snap, disc, nws, selected)
        await self.store.save_bundle(bundle)
        await self.store.update_debate(d["debate_id"], evidence_bundle_id=bundle["evidence_bundle_id"],
                                       snapshot_id=bundle["snapshot_id"])
        await self.store.add_event(d["debate_id"], f"{d['debate_id']}:evidence", "debate.evidence_ready", {
            "run_id": bundle["run_id"], "snapshot_id": bundle["snapshot_id"],
            "evidence_bundle_id": bundle["evidence_bundle_id"], "state_date": bundle["state_date"],
            "agenda": _agenda(bundle),
            "selected_sources": bundle.get("selected_sources", []),
            "sources": [{"source_id": x["id"], "title": x["title"], "url": x["source_uri"], "excerpt": x["excerpt"], "kind": x.get("kind")} for x in bundle["S_sources"]],
            # 화면의 근거 태그용: 발언의 structured_source_ids(D…)를 이름·값·단위로 보여줌
            "d_public": [{"id": x["id"], "label": x.get("label"), "value": x["value"], "unit": x.get("unit"),
                          "asset_name": x.get("asset_name"), "as_of": x.get("as_of"), "quality": x.get("quality")}
                         for x in bundle["D_sources"]
                         if isinstance(x.get("value"), (int, float)) and not isinstance(x.get("value"), bool)],
            "omitted_assets": bundle["omitted_assets"], "d_count": len(bundle["D_sources"]),
            "disclosure_count": sum(s.get("kind") == "dart_disclosure" for s in bundle["S_sources"]),
            "disclosure_status": bundle["disclosure_status"]["status"],
            "news_status": bundle["news_status"]["status"],
            # 화면이 "어떤 공시를 봤는지" 보여줄 수 있게 제목·날짜·DART 원문 링크를 함께 보냅니다(본문은 넣지 않음).
            # 발언의 rag_source_ids(S1, S2…)는 이 source_id와 같은 값입니다.
            "disclosures": [{"source_id": s["id"], "asset_id": s["asset_id"], "asset_name": s.get("asset_name"),
                             "title": s["title"], "published_date": s.get("published_date"), "url": s["source_uri"]}
                            for s in bundle["S_sources"] if s.get("kind") == "dart_disclosure"],
            # Bing 이용 조건: 화면에 출처 URL과 검색어 URL을 보여줘야 합니다.
            "web_news": [{"source_id": s["id"], "asset_id": s["asset_id"], "asset_name": s.get("asset_name"),
                          "citations": s["citations"], "search_query_urls": s["search_query_urls"]}
                         for s in bundle["S_sources"] if s.get("kind") == "web_news"],
        })
        await self.publisher.flush(d["debate_id"])
        return bundle

    # ------------------------------------------------------------------ 회의 (차례 발언)
    async def _meeting(self, d, bundle, final_attempt):
        """사회자 안건 → 1·2라운드(역할마다 한 번, 반대·일부 수정을 받은 역할이 이어서 답함)
        → 사회자 판정 → 쟁점이 남으면 당사자만 3라운드 → 사회자 결론."""
        did, agenda, order = d["debate_id"], _agenda(bundle), [r for r in c.MEETING_ORDER if r in d.get("target_roles", c.ROLES)]
        turns, last = [], None
        for rnd in range(1, c.BASE_ROUNDS + 1):
            await self.store.add_event(did, f"{did}:round{rnd}", "debate.round",
                                       {"round": rnd, "agenda": agenda if rnd == 1 else None,
                                        "speakers": order, "issue": None})
            await self.publisher.flush(did)
            last = await self._meeting_round(d, bundle, rnd, order, turns, last, agenda, None, final_attempt)
        ck_mid = message_id(did, "checkpoint", "moderator", "SUMMARY")
        ck = await self.store.get_message(ck_mid)
        if ck is None:
            out = await self._summary(d, bundle, final_attempt, mode="checkpoint", agenda=agenda, turns=turns)
            if out is None:          # 이미 결론이 났거나(합의) 요약 실패로 끝남
                return
            issue = (out["disagreements"][0]["issue"] if out["disagreements"] else out["summary_text"])
            ck = {"message_id": ck_mid, "debate_id": did, "round_id": "checkpoint", "phase": "SUMMARY",
                  "role": "moderator", "question_id": None, "reference_message_id": None, "status": "published",
                  "output": out, "error": None, "model_deployment": self.llm.deployment,
                  "prompt_version": self.prompts.version}
            roles = [r for r in c.MEETING_ORDER if r in out["open_issue_roles"] and r in order]
            await self.store.save_message(ck, "debate.round", {"round": c.MAX_ROUNDS, "agenda": None,
                                                               "speakers": roles, "issue": issue})
            await self.publisher.flush(did)
        roles = [r for r in c.MEETING_ORDER if r in ck["output"]["open_issue_roles"] and r in order]
        issue = (ck["output"]["disagreements"][0]["issue"] if ck["output"]["disagreements"] else ck["output"]["summary_text"])
        await self._meeting_round(d, bundle, c.MAX_ROUNDS, roles, turns, last, agenda, issue, final_attempt)
        await self._summary(d, bundle, final_attempt, mode="final", agenda=agenda, turns=turns)

    async def _meeting_round(self, d, bundle, rnd, speakers, turns, last, agenda, issue, final_attempt):
        remaining, turn = list(speakers), 0
        while remaining:
            nxt = next_speaker(remaining, last)
            first = rnd == 1 and turn == 0
            phase = "INITIAL" if first else ("CHALLENGE" if rnd == 1 else "REBUTTAL")
            round_id = f"r{rnd}-t{turn + 1}"
            mid = message_id(d["debate_id"], round_id, nxt, phase)
            msg = await self.store.get_message(mid)
            if msg is None:          # 재배달이면 저장된 발언을 그대로 씀 → 같은 순서가 재현됨
                spoken = [m for m in turns if m["status"] == "published"]
                mine = [m for m in spoken if m["role"] == nxt]
                call = dict(role=nxt, user_message=_turn_prompt(rnd, agenda, last, first, issue),
                            prior_claims=_claims(mine[-1]) if mine else [],
                            recent_history=[_turn_history(m) for m in spoken][-12:])
                try:
                    msg = await self._persona(d, bundle, round_id, phase, mid, **call)
                except TransientError as e:
                    if not final_attempt:
                        raise            # 앞 차례는 저장됐으니 재배달 때 이 차례부터 이어감
                    msg = self._failed_msg(d, round_id, phase, {"role": nxt}, f"TransientError: {str(e)[:200]}")
                if msg["status"] == "published" and msg["output"].get("reply_to"):
                    prev = [m for m in spoken if m["role"] == msg["output"]["reply_to"]]
                    msg["reference_message_id"] = prev[-1]["message_id"] if prev else None
                await self._save(msg)
            turns.append(msg)
            last, turn = msg, turn + 1
            remaining.remove(nxt)
        return last

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
            "participant_roles": d.get("target_roles", list(c.ROLES)),
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
            # 숫자 대조는 묶음 전체 값으로 함: 회의에서 다른 분석가가 말한 수치(그 역할의 근거)를 인용하는 경우가 많음.
            # 인용 가능한 근거 ID는 여전히 이 역할의 것만 허용.
            ok, errors = validate.check_persona(out, role=role, phase=phase, context_version=context_version,
                                                allowed_ids=allowed, evidence=bundle["D_sources"])
            if ok:
                return self._msg(d, round_id, phase, role, mid, question_id, reference_message_id, "published", ok)
            log.warning("검증 실패 %s %s 시도%d: %s", role, phase, attempt + 1, errors)
        return self._msg(d, round_id, phase, role, mid, question_id, reference_message_id, "failed", None,
                         "; ".join(errors)[:500])

    # ------------------------------------------------------------------ 요약
    async def _summary(self, d, bundle, final_attempt, *, mode="final", agenda=None, turns=None):
        """mode=checkpoint: 쟁점이 남았으면 저장하지 않고 결과를 돌려줌(3라운드). 그 밖에는 최종 결론으로 저장하고 None."""
        mid = message_id(d["debate_id"], "summary", "moderator", "SUMMARY")
        if await self.store.get_message(mid):
            return None
        msgs = [m for m in await self.store.list_messages(d["debate_id"]) if m["role"] in c.ROLES]
        # 프롬프트 V1.6: 할 말이 없으면 화면 문장을 비운 '침묵' 응답을 냅니다. 요약에는 실제 발언만 넣습니다.
        published = [m for m in msgs if m["status"] == "published" and not is_silent(m["output"])]
        shocks = {x["metric_id"]: f"{x['value']}{x['unit']}" for x in bundle["D_sources"]
                  if x["metric_id"].startswith("scenario_shock_")}
        summary_input = {
            "debate_id": d["debate_id"], "scenario": shocks, "mode": mode, "can_continue": mode == "checkpoint",
            "agenda": agenda or _agenda(bundle),
            "failed_roles": sorted({m["role"] for m in msgs if m["status"] == "failed"}),
            "silent_roles": sorted({m["role"] for m in msgs if m["status"] == "published" and is_silent(m["output"])}),
            "messages": [{**_turn_history(m), "phase": m["phase"],
                          "response_status": m["output"]["response_status"]} for m in published],
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
            out, errors = validate.check_summary(raw, ids, revised_roles={
                m["role"] for m in summary_input["messages"] if m["stance"] == "revise" or m["view_status"] == "revised"},
                strict_length=attempt == 0)   # 두 번째 시도에서도 길면 그대로 받음(결론이 없는 것보다 나음)
            if out:
                break
        if out and mode == "checkpoint" and not out["converged"] and out["open_issue_roles"]:
            return out
        msg = {"message_id": mid, "debate_id": d["debate_id"], "round_id": "summary", "phase": "SUMMARY",
               "role": "moderator", "question_id": None, "reference_message_id": None,
               "status": "published" if out else "failed", "output": out,
               "error": None if out else "; ".join(errors)[:500],
               "model_deployment": self.llm.deployment, "prompt_version": self.prompts.version}
        await self.store.save_message(msg, "debate.summary", {"message_id": mid, "status": msg["status"],
                                                              **(out or {"error": "요약을 만들지 못했습니다"})})
        await self.publisher.flush(d["debate_id"])
        return None

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
            payload = {**meta, **{k: o[k] for k in o if k not in ("schema_version", "context_version", "tts_text")},
                       "silent": is_silent(o)}   # 화면은 침묵 발언을 말풍선으로 보여주지 않습니다
            await self.store.save_message(msg, "message.created", payload)
        else:
            await self.store.save_message(msg, "message.failed", {**meta, "reason": "검증 또는 생성 실패"})
        await self.publisher.flush(msg["debate_id"])

    async def _fail(self, debate_id, reason):
        await self.store.update_debate(debate_id, status="failed", error=reason[:500])
        await self.store.add_event(debate_id, f"{debate_id}:failed", "debate.failed", {"reason": reason[:200]})


_SHOCK_NAMES = {"scenario_shock_usdkrw": "원/달러 환율", "scenario_shock_us10y": "미국 10년 금리",
                "scenario_shock_wti": "WTI 유가", "scenario_shock_vix": "VIX"}


def _agenda(bundle) -> str:
    """사회자가 던지는 안건 문장 (근거 묶음의 시나리오 충격으로 만듦)."""
    parts = []
    for x in bundle["D_sources"]:
        if x["metric_id"] in _SHOCK_NAMES and isinstance(x.get("value"), (int, float)) and x["value"]:
            v = x["value"]
            num = f"{v:+g}"
            parts.append(f"{_SHOCK_NAMES[x['metric_id']]} {num}{x.get('unit') or ''}")
    # 모델의 충격은 '오늘 대비 5거래일 뒤의 누적 변화'입니다. 지금 움직여 그 수준이 5거래일 뒤까지 이어지는 경우와 같습니다.
    if not parts:
        return "지금 추가 충격이 없다면, 5거래일 뒤 이 포트폴리오를 어떻게 보시나요?"
    return f"지금 {', '.join(parts)}만큼 움직인다면, 5거래일 뒤 이 포트폴리오를 어떻게 보시나요?"


def next_speaker(remaining: list[str], last: Optional[dict]) -> str:
    """반대·일부 수정을 받은 역할이 이어서 답하고, 없으면 고정 순서에서 아직 말하지 않은 역할."""
    if last and last.get("status") == "published":
        o = last["output"]
        if o.get("stance") in ("disagree", "partial") and o.get("reply_to") in remaining:
            return o["reply_to"]
    order = [r for r in c.MEETING_ORDER if r in remaining]
    if last and len(order) > 1 and order[0] == last.get("role"):
        return order[1]
    return order[0]


def _turn_history(m: dict) -> dict:
    o = m["output"]
    return {"message_id": m["message_id"], "role": m["role"], "name": c.PERSONAS[m["role"]]["label"],
            "round": int(m["round_id"][1]) if str(m["round_id"]).startswith("r") and m["round_id"][1:2].isdigit() else None,
            "stance": o.get("stance"), "reply_to": o.get("reply_to"), "view_status": o["view_status"],
            "summary_text": o["summary_text"],
            "claims": [{"claim_id": cl["claim_id"], "statement": cl["statement"],
                        "supersedes_claim_id": cl.get("supersedes_claim_id"), "change_reason": cl.get("change_reason")}
                       for cl in o["claims"]]}


def _turn_prompt(rnd: int, agenda: str, last: Optional[dict], first: bool, issue: Optional[str]) -> str:
    if first:
        return (f"회의를 시작합니다. 안건: {agenda} 당신이 첫 발언자입니다. stance=first, reply_to=null로 "
                "이 포트폴리오를 가장 간단히 보는 관점에서 입장을 밝히십시오. 24·25절 회의 차례 규칙과 17절 말투를 따르십시오.")
    prev = ""
    if last and last.get("status") == "published":
        prev = f" 직전 발언은 {c.PERSONAS[last['role']]['label']}({last['role']})의 '{last['output']['summary_text']}'입니다."
    if issue:
        return (f"회의 {rnd}라운드(마지막)입니다. 안건: {agenda} 사회자가 남긴 쟁점: {issue}{prev} "
                "이 쟁점에 대해 recent_history를 보고 최종 입장을 정리하십시오. 바뀌었다면 stance=revise로 이유를 밝히십시오.")
    return (f"회의 {rnd}라운드입니다. 안건: {agenda}{prev} recent_history의 앞선 발언 중 하나(보통 직전 발언)에 반응하십시오. "
            "stance(agree/disagree/partial/revise)와 reply_to를 정하고, 17절 말투로 2~3문장만 말하십시오. "
            "앞선 반박이 타당하면 stance=revise, view_status=revised로 의견을 바꾸고 supersedes_claim_id·change_reason을 채우십시오.")


def is_silent(output: Optional[dict]) -> bool:
    """프롬프트 V1.6 24절의 무발언 응답: 화면 문장(summary_text, display_text)이 모두 비어 있음."""
    return bool(output) and not (output.get("display_text") or "").strip() and not (output.get("summary_text") or "").strip()


def select_issues(initial: dict, max_issues: int) -> list[dict]:
    """초기 발언의 questions_to_roles에서 쟁점을 고릅니다.
    역할 순서대로 보고, 질문받는 역할마다 하나, 같은 (질문자, 대상) 쌍은 하나, 최대 max_issues개.
    질문받는 역할의 초기 발언이 실패했으면 건너뜁니다."""
    issues, targets = [], set()
    for role in c.ROLES:
        m = initial.get(role)
        if not m or m["status"] != "published" or is_silent(m["output"]):
            continue
        for q in m["output"]["questions_to_roles"]:
            t = q["role"]
            if (t == role or t in targets or not initial.get(t) or initial[t]["status"] != "published"
                    or is_silent(initial[t]["output"])):   # 침묵한 역할에게는 질문을 보내지 않음
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
