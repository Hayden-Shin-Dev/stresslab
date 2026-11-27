"""Scope notices stay neutral without changing valid financial answers."""
import json

import pytest

import contracts as c
import validate
from test_debate import FakeLLM, run


def answer(role):
    payload = dict(role=role, phase="USER_ANSWER", context_version="scope-test", D_sources=[])
    return run(FakeLLM().complete("", json.dumps(payload), c.persona_output_schema(role), "persona_" + role))


@pytest.mark.parametrize("role", c.ROLES)
def test_empty_scope_refusal_uses_neutral_notice(role):
    output = answer(role)
    output.update(intent="unsupported", response_status="unsupported", view_status="deferred",
                  claims=[], structured_source_ids=[], rag_source_ids=[],
                  summary_text="요청하신 내부 정보는 제공할 수 없습니다.",
                  display_text="요청하신 내부 정보는 제공할 수 없습니다.")
    checked, errors = validate.check_persona(output, role=role, phase="USER_ANSWER",
                                            context_version="scope-test", allowed_ids=set(), evidence=[])
    assert not errors
    assert checked["display_text"] == validate.SCOPE_NOTICE
    assert checked["summary_text"] == validate.SCOPE_NOTICE
    assert checked["tts_text"] == ""
    assert checked["intent"] == "unsupported" and checked["claims"] == []
    assert output["display_text"] != checked["display_text"]  # Never mutate the original output.


def test_valid_source_analysis_keeps_its_text_and_evidence():
    output = answer("macro")
    checked, errors = validate.check_persona(output, role="macro", phase="USER_ANSWER",
                                            context_version="scope-test", allowed_ids=set(), evidence=[])
    assert not errors
    assert checked["display_text"] == output["display_text"]
    assert checked["claims"] == output["claims"]
    assert checked["response_status"] == "ok"
