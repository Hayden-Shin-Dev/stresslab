"""모델 출력 검증. 통과한 발언만 저장·공개합니다.

1. JSON 스키마 (strict 출력이어도 한 번 더 확인)
2. role, context_version이 입력과 같은지
3. intent가 단계(phase)에 맞거나 허용된 대체 값인지
4. 인용한 D/S ID가 이 역할에게 준 근거 안에 있는지 (없는 ID 금지)
5. 화면·음성 문장에 내부 ID(D1, S2 …)가 노출되지 않았는지
6. 음성이 꺼져 있으면 tts_text가 비어 있는지
7. 화면 문장의 숫자(%, %p, bp, pt, 원)가 이 역할에게 준 근거 값과 맞는지
   (반올림·버림 허용, 부호는 "하락/상승"으로 바꿔 말할 수 있어 크기만 비교)

structured_source_ids / rag_source_ids는 서버가 인용 합집합으로 맞춥니다(정규화).
"""
from __future__ import annotations

import copy
import re

from jsonschema import Draft202012Validator

import contracts as c

_ID_LEAK = re.compile(r"(?<![A-Za-z0-9_])[DS]\d{1,4}(?![A-Za-z0-9_])")
_NUM = re.compile(
    r"(?<![0-9A-Za-z.])([+\-−]?\d{1,3}(?:,\d{3})+|[+\-−]?\d+(?:\.\d+)?)\s*"
    r"(%p|%포인트|퍼센트포인트|%|퍼센트|bp|pt|포인트|조\s*원|억\s*원|만\s*원|원)")
# 지표 이름 속 숫자(하위 10%, VaR 95% …)는 검사하지 않음
_NAME_NUM = re.compile(r"(하위|상위|신뢰\s*수준|VaR|ES)\s*\d+(\.\d+)?\s*%?|\d+(\.\d+)?\s*%\s*(VaR|ES|신뢰)")
_KRW = {"원": 1, "만원": 1e4, "억원": 1e8, "조원": 1e12}
_PCT_UNITS = {"%", "%p", "bp", "pt", "ratio", "corr"}


def _numbers(value, out):
    if isinstance(value, bool) or value is None:
        return
    if isinstance(value, (int, float)):
        out.append(float(value))
    elif isinstance(value, dict):
        for v in value.values():
            _numbers(v, out)
    elif isinstance(value, (list, tuple)):
        for v in value:
            _numbers(v, out)


def _candidates(evidence: list[dict]) -> tuple[list[float], list[float]]:
    """근거에서 나올 수 있는 값. (퍼센트류, 원)"""
    pct, krw = [], []
    for it in evidence:
        vals = []
        _numbers(it.get("value"), vals)
        for k, v in it.items():
            if k not in ("value", "id", "metric_id", "label", "record_id", "as_of", "horizon", "unit", "quality"):
                _numbers(v, vals)
        if it.get("unit") == "KRW":
            krw += [abs(v) for v in vals]
        elif it.get("unit") == "mixed":              # DART 상세처럼 원·주·%가 섞인 항목 묶음
            krw += [abs(v) for v in vals]
            pct += [abs(v) for v in vals]
        else:
            pct += [abs(v) for v in vals]
            if it.get("unit") in ("ratio", "corr"):
                pct += [abs(v) * 100 for v in vals]    # 0.65 → 65%
            if it.get("unit") == "%":
                pct += [abs(v) * 100 for v in vals]    # 1%p = 100bp
    return pct, krw


def unsupported_numbers(text: str, evidence: list[dict]) -> list[str]:
    pct, krw = _candidates(evidence)
    bad = []
    for m in _NUM.finditer(_NAME_NUM.sub(" ", text)):
        raw, unit = m.group(1), re.sub(r"\s", "", m.group(2))
        num = abs(float(raw.replace(",", "").replace("−", "-")))
        decimals = len(raw.split(".")[1]) if "." in raw else 0
        if unit in _KRW:
            mult = _KRW[unit]
            tol = 10 ** -decimals * mult + 1   # 반올림·버림 모두 허용 (마지막 자리 1 차이까지)
            ok = any(abs(num * mult - c) <= tol for c in krw)
        else:
            tol = 10 ** -decimals + 1e-9       # -2.9095 → "-2.909%"(버림)도 통과
            ok = any(abs(num - c) <= tol for c in pct)
        if not ok:
            bad.append(m.group(0).strip())
    return bad


_validators = {role: Draft202012Validator(c.persona_output_schema(role)) for role in c.ROLES}
_summary_validator = Draft202012Validator(c.summary_output_schema())


def check_persona(output: dict, *, role: str, phase: str, context_version: str,
                  allowed_ids: set[str], voice_enabled: bool = False,
                  evidence: list[dict] | None = None) -> tuple[dict | None, list[str]]:
    errors = [f"schema {'/'.join(map(str, e.path)) or '(root)'}: {e.message}"
              for e in _validators[role].iter_errors(output)]
    if errors:
        return None, errors[:5]
    out = copy.deepcopy(output)
    if out["role"] != role:
        errors.append(f"role 불일치: {out['role']}")
    if out["context_version"] != context_version:
        errors.append("context_version 불일치")
    if out["intent"] not in (c.PHASE_INTENT[phase],) + c.FALLBACK_INTENTS:
        errors.append(f"intent {out['intent']}는 {phase} 단계에 맞지 않음")

    cited = set()
    for cl in out["claims"]:
        cited.update(cl["evidence_refs"])
    for q in out["questions_to_roles"]:
        cited.update(q["evidence_refs"])
    for u in out["ui_requests"]:
        cited.update(u["refs"])
    cited.update(out["structured_source_ids"])
    cited.update(out["rag_source_ids"])
    unknown = sorted(cited - allowed_ids)
    if unknown:
        errors.append(f"제공하지 않은 근거 ID 인용: {', '.join(unknown[:10])}")

    for field in ("display_text", "summary_text", "tts_text"):
        leak = _ID_LEAK.findall(out[field])
        if leak:
            errors.append(f"{field}에 내부 ID 노출: {', '.join(sorted(set(leak))[:5])}")
    if evidence is not None:
        for field in ("display_text", "summary_text"):
            bad = unsupported_numbers(out[field], evidence)
            if bad:
                errors.append(f"{field}의 숫자가 근거 값과 맞지 않음(근거에 있는 값만 반올림해서 쓸 것): "
                              + ", ".join(list(dict.fromkeys(bad))[:5]))
    if not voice_enabled and out["tts_text"]:
        errors.append("음성이 꺼져 있는데 tts_text가 비어 있지 않음")
    if errors:
        return None, errors

    used = set()
    for cl in out["claims"]:
        used.update(cl["evidence_refs"])
    for q in out["questions_to_roles"]:
        used.update(q["evidence_refs"])
    out["structured_source_ids"] = sorted((used | set(out["structured_source_ids"])) & {i for i in allowed_ids if i.startswith("D")}, key=_id_key)
    out["rag_source_ids"] = sorted((used | set(out["rag_source_ids"])) & {i for i in allowed_ids if i.startswith("S")}, key=_id_key)
    return out, []


def check_summary(output: dict, message_ids: set[str]) -> tuple[dict | None, list[str]]:
    errors = [f"schema {'/'.join(map(str, e.path)) or '(root)'}: {e.message}"
              for e in _summary_validator.iter_errors(output)]
    if errors:
        return None, errors[:5]
    refs = set()
    for a in output["agreements"]:
        refs.update(a["message_ids"])
    for d in output["disagreements"]:
        refs.update(p["message_id"] for p in d["positions"])
    unknown = sorted(refs - message_ids)
    if unknown:
        return None, [f"없는 발언 ID 인용: {', '.join(unknown[:5])}"]
    return output, []


def _id_key(i: str):
    return (i[0], int(i[1:]) if i[1:].isdigit() else 0)
