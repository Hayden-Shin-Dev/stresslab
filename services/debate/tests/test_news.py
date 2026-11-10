"""웹 뉴스 근거: Azure OpenAI Responses API 대신 가짜 클라이언트로 검증합니다.

실행: 저장소 최상위에서  python -m pytest services/debate/tests -q
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import evidence as ev  # noqa: E402
import news as nw  # noqa: E402
from test_debate import make, run, start_req  # noqa: E402

NOW = datetime(2026, 11, 4, 5, 0, tzinfo=timezone.utc)   # KST 2026-11-04 14:00


def response(text, cites=(), queries=("현대해상 뉴스",), num_requests=None):
    out = [{"type": "web_search_call", "status": "completed", "action": {"type": "search", "query": q}}
           for q in queries]
    out.append({"type": "reasoning", "summary": []})
    out.append({"type": "message", "content": [{
        "type": "output_text", "text": text,
        "annotations": [{"type": "url_citation", "url": u, "title": t, "start_index": 0, "end_index": 1}
                        for t, u in cites]}]})
    body = {"output": out}
    if num_requests is not None:
        body["tool_usage"] = {"web_search": {"num_requests": num_requests}}
    return body


class FakeResponses:
    def __init__(self, by_asset=None, default=None):
        self.calls, self.by_asset = [], by_asset or {}
        self.default = default or response(nw.NO_NEWS)

    async def create(self, **kw):
        self.calls.append(kw)
        for code, r in self.by_asset.items():
            if f"종목코드 {code}" in kw["input"]:
                if isinstance(r, Exception):
                    raise r
                return r
        return self.default


class FakeClient:
    def __init__(self, **kw):
        self.responses = FakeResponses(**kw)


GOOD = response("- 2026-11-03: 현대해상이 3분기 실적을 발표했다. ([한국경제](https://www.hankyung.com/a1))\n"
                "- 2026-11-02: 자동차보험 손해율이 올랐다. [매일경제](https://www.mk.co.kr/b2)",
                cites=[("현대해상 3분기 실적", "https://www.hankyung.com/a1"),
                       ("손해율 상승", "https://www.mk.co.kr/b2"),
                       ("중복", "https://www.hankyung.com/a1")],
                queries=["현대해상 뉴스 2026년 11월", "현대해상 실적"], num_requests=2)


def test_parse_keeps_citations_strips_inline_links_and_builds_query_urls():
    r = nw.parse_response(GOOD)
    assert r["summary"].startswith("- 2026-11-03: 현대해상이 3분기 실적을 발표했다.")
    assert "http" not in r["summary"]
    assert r["citations"] == [{"title": "현대해상 3분기 실적", "url": "https://www.hankyung.com/a1"},
                              {"title": "손해율 상승", "url": "https://www.mk.co.kr/b2"}]
    assert r["search_queries"] == ["현대해상 뉴스 2026년 11월", "현대해상 실적"]
    assert r["search_query_urls"][1] == "https://www.bing.com/search?q=%ED%98%84%EB%8C%80%ED%95%B4%EC%83%81+%EC%8B%A4%EC%A0%81"
    assert r["search_requests"] == 2


def test_summary_without_citations_or_no_news_is_dropped():
    assert nw.parse_response(response("- 2026-11-03: 근거 없는 요약"))["summary"] is None
    assert nw.parse_response(response(nw.NO_NEWS, cites=[("x", "https://x.com")]))["summary"] is None


def test_recent_calls_web_search_for_top_assets_with_kr_location_and_window():
    client = FakeClient(by_asset={"001450": GOOD})
    src = nw.WebNews(client, "gpt-5.4-mini", max_assets=2, lookback_days=3)
    res = run(src.recent([("001450", "현대해상"), ("003490", "대한항공"), ("005830", "DB손해보험")], NOW))
    assert len(client.responses.calls) == 2                               # 상위 2종목만
    kw = client.responses.calls[0]
    assert kw["model"] == "gpt-5.4-mini" and kw["tool_choice"] == "required"
    assert kw["max_tool_calls"] == 2 and kw["reasoning"] == {"effort": "low"}
    assert kw["tools"][0]["type"] == "web_search" and kw["tools"][0]["user_location"]["country"] == "KR"
    assert "2026-11-01부터 2026-11-04까지" in kw["input"] and "현대해상" in kw["input"]
    assert res["status"] == "ok" and res["window"]["to"] == "2026-11-04"
    assert [it["asset_id"] for it in res["items"]] == ["001450"]           # 대한항공은 '관련 뉴스 없음'
    assert res["search_requests"] == 2 + 1


def test_cache_reuses_same_asset_same_day():
    t = [0.0]
    client = FakeClient(by_asset={"001450": GOOD})
    src = nw.WebNews(client, "dep", cache_minutes=60, clock=lambda: t[0])  # 기본은 하루(1440분)
    run(src.recent([("001450", "현대해상")], NOW))
    second = run(src.recent([("001450", "현대해상")], NOW))
    assert len(client.responses.calls) == 1 and second["search_requests"] == 0
    t[0] += 61 * 60
    run(src.recent([("001450", "현대해상")], NOW))
    assert len(client.responses.calls) == 2


def test_one_asset_failure_is_partial():
    client = FakeClient(by_asset={"001450": GOOD, "003490": RuntimeError("429 Too Many Requests")})
    res = run(nw.WebNews(client, "dep").recent([("001450", "현대해상"), ("003490", "대한항공")], NOW))
    assert res["status"] == "partial" and len(res["items"]) == 1 and res["errors"][0].startswith("003490:")


def test_disabled_without_flag():
    assert isinstance(nw.from_env({}), nw.NoNews)


def test_debate_bundle_has_news_source_and_event_carries_display_links():
    orch, store, sender = make()
    orch.news = nw.WebNews(FakeClient(by_asset={"001450": GOOD}), "dep")
    run(orch.handle(start_req()))
    d = run(store.get_debate("dbt-1"))
    assert d["status"] == "completed"
    bundle = run(store.get_bundle(d["evidence_bundle_id"]))
    s = [x for x in bundle["S_sources"] if x.get("kind") == "web_news"]
    assert len(s) == 1 and s[0]["asset_id"] == "001450" and "AI 요약" in s[0]["title"]
    assert s[0]["source_uri"] == "https://www.hankyung.com/a1" and len(s[0]["citations"]) == 2
    assert bundle["news_status"]["status"] == "ok"
    for role in ("market", "risk", "portfolio"):
        assert s[0]["id"] in {x["id"] for x in ev.for_role(bundle, role)[1]}
    assert s[0]["id"] not in {x["id"] for x in ev.for_role(bundle, "macro")[1]}
    ready = [m for _, m in sender.sent if m["type"] == "debate.evidence_ready"][0]["payload"]
    assert ready["news_status"] == "ok"
    assert ready["web_news"][0]["search_query_urls"][0].startswith("https://www.bing.com/search?q=")
    assert ready["web_news"][0]["citations"][0]["url"] == "https://www.hankyung.com/a1"


def test_debate_continues_when_news_client_breaks():
    class Broken:
        async def recent(self, assets, now):
            raise RuntimeError("bug")
    orch, store, _ = make()
    orch.news = Broken()
    run(orch.handle(start_req()))
    d = run(store.get_debate("dbt-1"))
    assert d["status"] == "completed"
    assert run(store.get_bundle(d["evidence_bundle_id"]))["news_status"]["status"] == "failed"


def test_falls_back_to_auto_when_model_rejects_required_tool_choice():
    class Picky(FakeResponses):
        async def create(self, **kw):
            self.calls.append(kw)
            if kw.get("tool_choice") == "required":
                raise ValueError("Tool choices other than 'auto' are not supported with model")
            return GOOD
    client = FakeClient()
    client.responses = Picky()
    src = nw.WebNews(client, "dep")
    res = run(src.recent([("001450", "현대해상"), ("003490", "대한항공")], NOW))
    assert res["status"] == "ok" and len(res["items"]) == 2
    assert [c.get("tool_choice") for c in client.responses.calls].count("required") <= 2
    assert client.responses.calls[-1].get("tool_choice") is None



def dated(lines_with_urls):
    """[(줄, [(제목, url)])] → 인용 위치가 실제 줄을 가리키는 응답."""
    text, anns, pos = "", [], 0
    for i, (line, cs) in enumerate(lines_with_urls):
        if i:
            text += "\n"
            pos += 1
        for t, u in cs:
            anns.append((t, u, pos, pos + len(line)))
        text += line
        pos += len(line)
    out = [{"type": "web_search_call", "action": {"type": "search", "query": "S-Oil 뉴스"}},
           {"type": "message", "content": [{"type": "output_text", "text": text, "annotations": [
               {"type": "url_citation", "title": t, "url": u, "start_index": a, "end_index": b}
               for t, u, a, b in anns]}]}]
    return {"output": out, "tool_usage": {"web_search": {"num_requests": 1}}}


def test_lines_outside_window_or_undated_are_dropped_with_their_citations():
    from datetime import date
    resp = dated([("- 2026-11-02: 3분기 영업이익이 크게 늘었다.", [("실적", "https://yna/1102")]),
                  ("- 2026-11-08: 정제마진이 내렸다.", [("마진", "https://yna/1108")]),
                  ("- 날짜 없는 줄", [("x", "https://x")]),
                  ("- 2026-11-10: 정기보수 일정을 공시했다.", [("보수", "https://yna/1110")])])
    r = nw.parse_response(resp, date(2026, 11, 3), date(2026, 11, 10))
    assert r["summary"] == "- 2026-11-08: 정제마진이 내렸다.\n- 2026-11-10: 정기보수 일정을 공시했다."
    assert [c["url"] for c in r["citations"]] == ["https://yna/1108", "https://yna/1110"]
    assert r["dropped_lines"] == 2


def test_all_lines_outside_window_means_no_news():
    from datetime import date
    resp = dated([("- 2026-11-02: 오래된 기사", [("a", "https://yna/1102")])])
    r = nw.parse_response(resp, date(2026, 11, 3), date(2026, 11, 10))
    assert r["summary"] is None and r["citations"] == []


def test_rejected_optional_params_are_removed_one_by_one():
    class Strict(FakeResponses):
        async def create(self, **kw):
            self.calls.append(kw)
            if "reasoning" in kw:
                raise ValueError("Unsupported parameter: 'reasoning.effort' is not supported with this model.")
            if "max_tool_calls" in kw:
                raise ValueError("Unknown parameter: 'max_tool_calls'.")
            return GOOD
    client = FakeClient()
    client.responses = Strict()
    src = nw.WebNews(client, "dep")
    run(src.recent([("001450", "현대해상")], NOW))
    last = client.responses.calls[-1]
    assert "reasoning" not in last and "max_tool_calls" not in last and last["tool_choice"] == "required"
    run(src.recent([("003490", "대한항공")], NOW))           # 다음 호출부터는 바로 빼고 부름
    assert "reasoning" not in client.responses.calls[-1] and len(client.responses.calls) == 4


def test_daily_request_budget_skips_remaining_assets():
    client = FakeClient(default=GOOD)                         # 종목당 2건
    src = nw.WebNews(client, "dep", max_assets=5, concurrency=1, daily_request_limit=3)
    res = run(src.recent([("001450", "a"), ("003490", "b"), ("005830", "c")], NOW))
    assert len(client.responses.calls) == 2                   # 2 → 4건이 되면서 세 번째는 건너뜀
    assert res["status"] == "partial" and len(res["items"]) == 2 and "상한" in res["errors"][-1]
    res2 = run(src.recent([("000810", "d")], NOW))
    assert res2["status"] == "budget_exceeded" and len(client.responses.calls) == 2


def test_default_cache_keeps_same_day_across_slots():
    t = [0.0]
    client = FakeClient(by_asset={"001450": GOOD})
    src = nw.WebNews(client, "dep", clock=lambda: t[0])
    run(src.recent([("001450", "현대해상")], NOW))
    t[0] += 7 * 3600                                           # 08:30 → 15:40
    run(src.recent([("001450", "현대해상")], NOW))
    assert len(client.responses.calls) == 1



def test_per_asset_log_explains_why_news_was_dropped(caplog):
    from datetime import date  # noqa: F401
    old = response("- 2026-10-01: 오래된 기사", cites=[("a", "https://yna/1001")])
    client = FakeClient(by_asset={"001450": old})
    with caplog.at_level("INFO", logger="debate.news"):
        run(nw.WebNews(client, "dep").recent([("001450", "현대해상"), ("003490", "대한항공")], NOW))
    text = caplog.text
    assert "웹 뉴스 001450: 검색어 1, Bing 1, 답 1줄(기간 밖·날짜 없음 1), 인용 1, 없음이라고 답함 아니오, 결과 버림" in text
    assert "웹 뉴스 003490:" in text and "없음이라고 답함 예" in text
