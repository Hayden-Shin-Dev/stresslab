"""DART 공시 근거: 실제 DART 대신 가짜 응답(httpx.MockTransport)으로 검증합니다.

실행: 저장소 최상위에서  python -m pytest services/debate/tests -q
"""
import asyncio
import io
import json
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import disclosures as dz  # noqa: E402
import evidence as ev  # noqa: E402
from test_debate import FakeLLM, make, run, start_req  # noqa: E402

NOW = datetime(2026, 11, 4, 5, 0, tzinfo=timezone.utc)   # KST 2026-11-04 14:00

CORPS = [("00164742", "현대해상", "001450"), ("00113526", "대한항공", "003490"),
         ("00159102", "DB손해보험", "005830"), ("99999999", "비상장회사", " ")]


def corp_zip(rows=CORPS) -> bytes:
    xml = "<result>" + "".join(
        f"<list><corp_code>{c}</corp_code><corp_name>{n}</corp_name><stock_code>{s}</stock_code>"
        f"<modify_date>20260101</modify_date></list>" for c, n, s in rows) + "</result>"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("CORPCODE.xml", xml)
    return buf.getvalue()


def filings(corp, n, report="임원ㆍ주요주주특정증권등소유상황보고서"):
    return [{"corp_code": corp, "corp_name": "현대해상", "stock_code": "001450", "corp_cls": "Y",
             "report_nm": f"  {report}  {i}", "rcept_no": f"2026110300{i:04d}",
             "flr_nm": "현대해상", "rcept_dt": "20261103", "rm": "유"} for i in range(n)]


def filing(corp, rcept_no, report):
    return {"corp_code": corp, "corp_name": "현대해상", "stock_code": "001450", "corp_cls": "Y",
            "report_nm": report, "rcept_no": rcept_no, "flr_nm": "현대해상", "rcept_dt": "20261103", "rm": "유"}


class FakeDart:
    """corpCode.xml / list.json 가짜. 호출 기록을 남깁니다."""

    def __init__(self, lists=None, corp_status=200, corp_body=None, details=None):
        self.calls = []
        self.lists = lists or {}          # corp_code -> dict 응답 또는 HTTP 상태코드(int)
        self.details = details or {}      # (상세 API, corp_code) -> dict 응답 또는 HTTP 상태코드(int)
        self.corp_status, self.corp_body = corp_status, corp_body

    def handler(self, request: httpx.Request):
        self.calls.append((request.url.path, dict(request.url.params)))
        assert request.url.params["crtfc_key"] == "test-key"
        if request.url.path.endswith("/corpCode.xml"):
            return httpx.Response(self.corp_status, content=self.corp_body or corp_zip())
        corp = request.url.params["corp_code"]
        none = {"status": "013", "message": "조회된 데이타가 없습니다."}
        if request.url.path.endswith("/list.json"):
            r = self.lists.get(corp, none)
        else:
            r = self.details.get((request.url.path.rsplit("/", 1)[-1][:-5], corp), none)
        if isinstance(r, int):
            return httpx.Response(r)
        return httpx.Response(200, json=r)

    def source(self, **kw):
        return dz.DartDisclosures("test-key", transport=httpx.MockTransport(self.handler), **kw)

    def list_calls(self):
        return [p for p, _ in self.calls if p.endswith("/list.json")]

    def detail_calls(self):
        return [p.rsplit("/", 1)[-1] for p, _ in self.calls
                if not p.endswith("/list.json") and not p.endswith("/corpCode.xml")]


def ok(items):
    return {"status": "000", "message": "정상", "list": items}


# ---------------------------------------------------------------------------
def test_recent_maps_stock_code_and_limits_window_and_count():
    fake = FakeDart({"00164742": ok(filings("00164742", 8))})
    res = run(fake.source(max_per_asset=5).recent(["001450", "003490", "069500"], NOW))
    assert res["status"] == "ok" and res["errors"] == []
    assert res["window"] == {"from": "2026-10-28", "to": "2026-11-04", "timezone": "Asia/Seoul"}
    assert len(res["items"]) == 5                                  # 종목당 상한
    it = res["items"][0]
    assert it["asset_id"] == "001450" and it["received_date"] == "2026-11-03"
    assert it["report_name"] == "임원ㆍ주요주주특정증권등소유상황보고서 0"   # 공백 정리
    assert "detail" not in it and fake.detail_calls() == []        # 주요사항보고서 아니면 상세 안 부름
    assert it["url"] == "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20261103000000"
    params = [q for p, q in fake.calls if p.endswith("/list.json")][0]
    assert params["bgn_de"] == "20261028" and params["end_de"] == "20261104" and params["corp_code"] == "00164742"
    # 069500(표에 없음)은 DART를 부르지 않음, 003490은 013(없음)
    assert len(fake.list_calls()) == 2


def test_cache_reuses_same_asset_across_debates_and_corp_table_loaded_once():
    t = [0.0]
    fake = FakeDart({"00164742": ok(filings("00164742", 2))})
    src = fake.source(cache_minutes=30, clock=lambda: t[0])
    run(src.recent(["001450"], NOW))
    run(src.recent(["001450"], NOW))               # 다른 사용자의 같은 종목
    assert len(fake.list_calls()) == 1
    t[0] += 31 * 60                                  # 30분 지나면 다시 조회
    run(src.recent(["001450"], NOW))
    assert len(fake.list_calls()) == 2
    assert sum(p.endswith("/corpCode.xml") for p, _ in fake.calls) == 1


def test_errors_do_not_raise_and_limit_stops_remaining_assets():
    fake = FakeDart({"00164742": 500, "00113526": {"status": "020", "message": "요청 제한을 초과하였습니다."},
                     "00159102": ok(filings("00159102", 1))})
    res = run(fake.source().recent(["001450", "003490", "005830"], NOW))
    assert res["status"] == "failed" and res["items"] == []
    assert len(res["errors"]) == 2 and "요청 제한" in res["errors"][1]
    assert len(fake.list_calls()) == 2              # 제한 초과 뒤 005830은 부르지 않음
    assert res["errors"][0] == "001450: HTTP 500"


def test_key_never_appears_in_errors_or_logs(caplog):
    fake = FakeDart({"00164742": 500})
    with caplog.at_level("DEBUG"):
        res = run(fake.source().recent(["001450"], NOW))
    assert "test-key" not in json.dumps(res, ensure_ascii=False)
    assert "test-key" not in caplog.text


def test_bad_key_corp_table_is_reported_as_failed():
    fake = FakeDart(corp_body=json.dumps({"status": "010", "message": "등록되지 않은 키입니다."}).encode())
    res = run(fake.source().recent(["001450"], NOW))
    assert res["status"] == "failed" and "ZIP" in res["errors"][0] and fake.list_calls() == []


def test_parse_corp_codes_keeps_listed_only():
    table = dz.parse_corp_codes(corp_zip())
    assert table["001450"] == ("00164742", "현대해상") and len(table) == 3


def test_from_env_without_key_disables():
    assert isinstance(dz.from_env({}), dz.NoDisclosures)


# ---------------------------------------------------------------------------
def test_debate_bundle_includes_disclosures_for_scoped_roles_and_fixes_them():
    fake = FakeDart({"00164742": ok(filings("00164742", 2))})
    orch, store, sender = make()
    orch.disclosures = fake.source()
    run(orch.handle(start_req()))
    d = run(store.get_debate("dbt-1"))
    assert d["status"] == "completed"
    bundle = run(store.get_bundle(d["evidence_bundle_id"]))
    disc = [s for s in bundle["S_sources"] if s.get("kind") == "dart_disclosure"]
    assert len(disc) == 2 and bundle["disclosure_status"]["status"] == "ok"
    assert disc[0]["asset_name"] == "현대해상" and disc[0]["source_uri"].startswith("https://dart.fss.or.kr/")
    for role in ("market", "risk", "portfolio"):
        _, s = ev.for_role(bundle, role)
        assert {x["id"] for x in disc} <= {x["id"] for x in s}
    _, s_macro = ev.for_role(bundle, "macro")
    assert not any(x.get("kind") == "dart_disclosure" for x in s_macro)
    ready = [m for _, m in sender.sent if m["type"] == "debate.evidence_ready"][0]["payload"]
    assert ready["disclosure_count"] == 2 and ready["disclosure_status"] == "ok"

    # 사용자 질문은 같은 묶음을 씀 → DART 다시 부르지 않음
    calls = len(fake.list_calls())
    import contracts as c
    q = c.DebateRequest(type="user_question", request_id="q-1", debate_id="dbt-1", user_id="u1", run_id="stress_run",
                        created_at="2026-11-04T05:10:00Z",
                        question=c.UserQuestion(question_id="Q1", text="공시 영향은?", target_roles=["risk"]))
    run(orch.handle(q))
    assert len(fake.list_calls()) == calls


def test_debate_continues_when_dart_is_down():
    fake = FakeDart(corp_status=503)
    orch, store, _ = make(FakeLLM())
    orch.disclosures = fake.source()
    run(orch.handle(start_req()))
    d = run(store.get_debate("dbt-1"))
    assert d["status"] == "completed"
    assert run(store.get_bundle(d["evidence_bundle_id"]))["disclosure_status"]["status"] == "failed"


def test_debate_continues_when_source_raises():
    class Broken:
        async def recent(self, asset_ids, now):
            raise RuntimeError("bug")
    orch, store, _ = make()
    orch.disclosures = Broken()
    run(orch.handle(start_req()))
    assert run(store.get_debate("dbt-1"))["status"] == "completed"


def test_bundle_assets_matches_bundle_order():
    import json as _j
    r = _j.loads((Path(__file__).parent / "fixtures" / "stress_run.json").read_text(encoding="utf-8"))
    assert ev.bundle_assets(r) == [a["asset"] for a in sorted(r["assets"], key=ev._holding, reverse=True)][:ev.MAX_ASSETS]


# ---------------------------------------------------------------------------- 주요사항보고서 상세
def test_detail_endpoint_matching_prefers_longer_names():
    assert dz.detail_endpoint("주요사항보고서(유무상증자결정)") == ("pifricDecsn", "유무상증자 결정")
    assert dz.detail_endpoint("[기재정정]주요사항보고서 (유상증자결정)") == ("piicDecsn", "유상증자 결정")
    assert dz.detail_endpoint("주요사항보고서(회사분할합병결정)")[0] == "cmpDvmgDecsn"
    assert dz.detail_endpoint("주요사항보고서(전환사채권발행결정)")[0] == "cvbdIsDecsn"
    assert dz.detail_endpoint("유상증자결정") is None                    # 주요사항보고서가 아님(거래소 공시 등)
    assert dz.detail_endpoint("주요사항보고서(영업양수결정)") is None      # 목록에 없는 종류


def test_parse_detail_numbers_and_drops_empty():
    row = {"rcept_no": "1", "corp_code": "c", "corp_name": "n", "corp_cls": "Y",
           "nstk_ostk_cnt": "1,000,000", "fdpp_op": "50,000,000,000", "dc_rt": "10.5", "ic_mthn": "주주배정후 실권주 일반공모",
           "fdpp_etc": "-", "x": "", "neg": "-3"}
    assert dz.parse_detail(row) == {"nstk_ostk_cnt": 1000000, "fdpp_op": 50000000000, "dc_rt": 10.5,
                                    "ic_mthn": "주주배정후 실권주 일반공모", "neg": -3}


def test_major_report_gets_detail_once_per_type_and_matched_by_rcept_no():
    lst = ok([filing("00164742", "A1", "주요사항보고서(유상증자결정)"),
              filing("00164742", "A2", "[기재정정]주요사항보고서(유상증자결정)"),
              filing("00164742", "A3", "주요사항보고서(전환사채권발행결정)"),
              filing("00164742", "A4", "기업설명회(IR)개최")])
    fake = FakeDart({"00164742": lst}, details={
        ("piicDecsn", "00164742"): ok([{"rcept_no": "A1", "fdpp_op": "50,000,000,000"},
                                       {"rcept_no": "A2", "fdpp_op": "60,000,000,000"}]),
        ("cvbdIsDecsn", "00164742"): 500})
    res = run(fake.source().recent(["001450"], NOW))
    by = {it["rcept_no"]: it for it in res["items"]}
    assert sorted(fake.detail_calls()) == ["cvbdIsDecsn.json", "piicDecsn.json"]
    assert by["A1"]["detail"] == {"endpoint": "piicDecsn", "fields": {"fdpp_op": 50000000000}}
    assert by["A2"]["detail"]["fields"]["fdpp_op"] == 60000000000
    assert by["A3"]["detail_type"] == "전환사채 발행 결정" and by["A3"]["detail_error"] == "HTTP 500"
    assert "detail_type" not in by["A4"]
    assert res["status"] == "ok"                        # 상세 실패는 전체 상태를 바꾸지 않음


def test_detail_becomes_D_evidence_linked_to_S_and_numbers_are_citable():
    import validate as v
    lst = ok([filing("00164742", "A1", "주요사항보고서(유상증자결정)")])
    fake = FakeDart({"00164742": lst}, details={
        ("piicDecsn", "00164742"): ok([{"rcept_no": "A1", "fdpp_op": "50,000,000,000", "nstk_ostk_cnt": "1,000,000"}])})
    orch, store, _ = make()
    orch.disclosures = fake.source()
    run(orch.handle(start_req()))
    bundle = run(store.get_bundle(run(store.get_debate("dbt-1"))["evidence_bundle_id"]))
    s = [x for x in bundle["S_sources"] if x.get("kind") == "dart_disclosure"][0]
    d = [x for x in bundle["D_sources"] if x["metric_id"] == "dart_detail"][0]
    assert d["source_ref"] == s["id"] and d["unit"] == "mixed" and d["asset_id"] == "001450"
    assert d["report_type"] == "유상증자 결정" and d["quality"] == "official_disclosure"
    assert s["detail_type"] == "유상증자 결정"
    assert set(d["role_scope"]) == {"market", "risk", "portfolio"}
    # 공시 금액은 원 단위로, 주식 수도 숫자로 인용 가능
    assert v.unsupported_numbers("운영자금 500억원, 신주 100만주", [d]) == []
    assert v.unsupported_numbers("운영자금 700억원", [d]) == ["700억원"]
