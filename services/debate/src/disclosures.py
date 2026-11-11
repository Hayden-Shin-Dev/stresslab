"""DART 공시 근거 (금감원 OpenDART).

토론 근거 묶음을 처음 만들 때 한 번 조회합니다. 묶음은 한 번 만들면 바뀌지 않으므로, 재배달이나 사용자
질문에서는 다시 부르지 않고 같은 공시를 봅니다(근거 고정).

- 대상: 근거 묶음에 들어가는 종목(보유 금액 큰 순 최대 20개)
- 기간: 토론 시각(KST) 기준 최근 DART_LOOKBACK_DAYS일(기본 7), 종목당 최신 DART_MAX_PER_ASSET건(기본 5)
- 내용: 공시 제목·제출인·접수일·원문 링크. 본문은 가져오지 않습니다.
- 주요사항보고서(유상증자·전환사채·자기주식·합병 등)는 같은 키로 종류별 상세 API를 한 번 더 불러 금액·주식 수
  같은 항목을 붙입니다(DETAIL_ENDPOINTS). 목록에 그 종류가 있을 때만 부르므로 평소에는 추가 호출이 없습니다.
  상세 조회가 실패해도 제목 근거는 그대로 들어갑니다.
- 중복 호출 방지: 같은 종목·같은 기간은 DART_CACHE_MINUTES분(기본 30) 동안 프로세스 안에서 재사용합니다.
  정시 회의에서 여러 사용자가 같은 종목을 갖고 있어도 DART는 종목당 한 번만 부릅니다.
- 실패해도 토론은 진행합니다. 공시 없이 진행하고 묶음의 disclosure_status에 이유를 남깁니다.

DART 호출
  GET https://opendart.fss.or.kr/api/corpCode.xml   종목코드(6자리) → 고유번호(8자리) 표. 프로세스마다 한 번
  GET https://opendart.fss.or.kr/api/list.json      종목별 공시 목록
  GET https://opendart.fss.or.kr/api/<상세>.json     주요사항보고서 종류별 상세 (corp_code, bgn_de, end_de)

환경변수: DART_API_KEY(없으면 공시 조회를 끔), DART_LOOKBACK_DAYS, DART_MAX_PER_ASSET, DART_CACHE_MINUTES
키는 팀이 같은 키를 공유하므로 하루 호출 한도(약 20,000건)도 함께 씁니다.
"""
from __future__ import annotations

import asyncio
import io
import logging
import re
import time
import zipfile
from datetime import date, datetime, timedelta
from typing import Optional, Protocol
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

import httpx

log = logging.getLogger("debate.disclosures")
KST = ZoneInfo("Asia/Seoul")
BASE = "https://opendart.fss.or.kr/api"
VIEWER = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo={}"


class _RedactKey(logging.Filter):
    """httpx는 요청 URL을 INFO로 기록합니다. DART 인증키가 쿼리에 있어 로그에서 가립니다."""
    _pat = re.compile(r"(crtfc_key=)[^&\s\"']+")

    def filter(self, record):
        msg = record.getMessage()
        if "crtfc_key=" in msg:
            record.msg, record.args = self._pat.sub(r"\1***", msg), None
        return True


for _name in ("httpx", "httpcore"):
    if not any(isinstance(f, _RedactKey) for f in logging.getLogger(_name).filters):
        logging.getLogger(_name).addFilter(_RedactKey())


# 공시 제목(공백 제거)에 들어 있는 문구 → (상세 API, 표시 이름). 긴 문구를 먼저 검사합니다(유무상 > 유상).
# 확인: piicDecsn·fricDecsn·pifricDecsn·cvbdIsDecsn·exbdIsDecsn·lwstLg (공개 사용 예 기준)
#       tsstkAqDecsn·tsstkDpDecsn (2026-11-10 실제 응답: SK하이닉스 자기주식취득, 현대모비스 자기주식처분)
# 미확인: 나머지는 OpenDART 명명 규칙으로 넣었습니다. 이름이 틀리면 해당 공시만 detail_error로 남습니다.
DETAIL_ENDPOINTS = [
    ("유무상증자결정", "pifricDecsn", "유무상증자 결정"),
    ("유상증자결정", "piicDecsn", "유상증자 결정"),
    ("무상증자결정", "fricDecsn", "무상증자 결정"),
    ("감자결정", "crDecsn", "감자 결정"),
    ("신주인수권부사채권발행결정", "bdwtIsDecsn", "신주인수권부사채 발행 결정"),
    ("전환사채권발행결정", "cvbdIsDecsn", "전환사채 발행 결정"),
    ("교환사채권발행결정", "exbdIsDecsn", "교환사채 발행 결정"),
    ("자기주식취득결정", "tsstkAqDecsn", "자기주식 취득 결정"),
    ("자기주식처분결정", "tsstkDpDecsn", "자기주식 처분 결정"),
    ("회사분할합병결정", "cmpDvmgDecsn", "회사분할합병 결정"),
    ("회사합병결정", "cmpMgDecsn", "회사합병 결정"),
    ("회사분할결정", "cmpDvDecsn", "회사분할 결정"),
    ("소송등의제기", "lwstLg", "소송 등의 제기"),
]
_DETAIL_META = {"rcept_no", "corp_cls", "corp_code", "corp_name"}

# 상세 항목 한국어 이름 (단위 포함). 실제 응답을 확인한 종류만 넣습니다. 없는 항목은 원본 이름 그대로 둡니다.
_COMMON_LABELS = {
    "od_a_at_t": "사외이사 참석(명)",
    "od_a_at_b": "사외이사 불참(명)",
    "adt_a_atn": "감사(위원) 참석 여부",
    "cs_iv_bk": "위탁 투자중개업자",
}
DETAIL_LABELS = {
    "tsstkAqDecsn": {   # 자기주식 취득 결정
        **_COMMON_LABELS,
        "aqpln_stk_ostk": "취득예정 주식 수(보통주, 주)",
        "aqpln_stk_estk": "취득예정 주식 수(기타주, 주)",
        "aqpln_prc_ostk": "취득예정 금액(보통주, 원)",
        "aqpln_prc_estk": "취득예정 금액(기타주, 원)",
        "aqexpd_bgd": "취득예상기간 시작일",
        "aqexpd_edd": "취득예상기간 종료일",
        "hdexpd_bgd": "보유예상기간 시작일",
        "hdexpd_edd": "보유예상기간 종료일",
        "aq_pp": "취득 목적",
        "aq_mth": "취득 방법",
        "aq_wtn_div_ostk": "취득 전 자기주식(배당가능이익 범위 내 취득, 보통주, 주)",
        "aq_wtn_div_ostk_rt": "취득 전 자기주식 비율(배당가능이익 범위 내 취득, 보통주, %)",
        "aq_wtn_div_estk": "취득 전 자기주식(배당가능이익 범위 내 취득, 기타주, 주)",
        "aq_wtn_div_estk_rt": "취득 전 자기주식 비율(배당가능이익 범위 내 취득, 기타주, %)",
        "eaq_ostk": "취득 전 자기주식(기타 취득, 보통주, 주)",
        "eaq_ostk_rt": "취득 전 자기주식 비율(기타 취득, 보통주, %)",
        "eaq_estk": "취득 전 자기주식(기타 취득, 기타주, 주)",
        "eaq_estk_rt": "취득 전 자기주식 비율(기타 취득, 기타주, %)",
        "aq_dd": "취득 결정일",
        "d1_prodlm_ostk": "1일 매수 주문 한도(보통주, 주)",
        "d1_prodlm_estk": "1일 매수 주문 한도(기타주, 주)",
    },
    "tsstkDpDecsn": {   # 자기주식 처분 결정
        **_COMMON_LABELS,
        "dppln_stk_ostk": "처분예정 주식 수(보통주, 주)",
        "dppln_stk_estk": "처분예정 주식 수(기타주, 주)",
        "dpstk_prc_ostk": "처분 대상 주식 가격(보통주, 원)",
        "dpstk_prc_estk": "처분 대상 주식 가격(기타주, 원)",
        "dppln_prc_ostk": "처분예정 금액(보통주, 원)",
        "dppln_prc_estk": "처분예정 금액(기타주, 원)",
        "dpprpd_bgd": "처분예정기간 시작일",
        "dpprpd_edd": "처분예정기간 종료일",
        "dp_pp": "처분 목적",
        "dp_m_mkt": "처분 방법: 시장 매도(주)",
        "dp_m_ovtm": "처분 방법: 시간외대량매매(주)",
        "dp_m_otc": "처분 방법: 장외처분(주)",
        "dp_m_etc": "처분 방법: 기타(주)",
        "aq_wtn_div_ostk": "처분 전 자기주식(배당가능이익 범위 내 취득, 보통주, 주)",
        "aq_wtn_div_ostk_rt": "처분 전 자기주식 비율(배당가능이익 범위 내 취득, 보통주, %)",
        "aq_wtn_div_estk": "처분 전 자기주식(배당가능이익 범위 내 취득, 기타주, 주)",
        "aq_wtn_div_estk_rt": "처분 전 자기주식 비율(배당가능이익 범위 내 취득, 기타주, %)",
        "eaq_ostk": "처분 전 자기주식(기타 취득, 보통주, 주)",
        "eaq_ostk_rt": "처분 전 자기주식 비율(기타 취득, 보통주, %)",
        "eaq_estk": "처분 전 자기주식(기타 취득, 기타주, 주)",
        "eaq_estk_rt": "처분 전 자기주식 비율(기타 취득, 기타주, %)",
        "dp_dd": "처분 결정일",
    },
}


def label_fields(endpoint: str, fields: dict) -> dict:
    """원본 항목명 → 한국어 이름. 모르는 항목은 원본 이름 그대로."""
    labels = DETAIL_LABELS.get(endpoint, {})
    return {labels.get(k, k): v for k, v in fields.items()}


def detail_endpoint(report_name: str) -> Optional[tuple[str, str]]:
    """주요사항보고서 제목이면 (상세 API, 표시 이름). 아니면 None."""
    name = "".join(report_name.split())
    if "주요사항보고서" not in name:
        return None
    for key, endpoint, label in DETAIL_ENDPOINTS:
        if key in name:
            return endpoint, label
    return None


def parse_detail(row: dict) -> dict:
    """상세 응답 한 건 → {원본 항목명: 숫자 또는 문자열}. 빈 값과 '-'는 뺍니다."""
    out = {}
    for k, v in row.items():
        if k in _DETAIL_META or v is None:
            continue
        text = " ".join(str(v).split())             # 여러 줄 값(증권사 이름 등)을 한 줄로
        if text in ("", "-"):
            continue
        num = text.replace(",", "")
        try:
            out[k] = int(num) if re.fullmatch(r"-?\d+", num) else float(num) if re.fullmatch(r"-?\d+\.\d+", num) else text
        except ValueError:
            out[k] = text
    return out


class DisclosureSource(Protocol):
    async def recent(self, asset_ids: list[str], now: datetime) -> dict:
        """{"status": "ok"|"disabled"|"partial"|"failed", "window": {...}, "items": [...], "errors": [...]}"""
        ...


class NoDisclosures:
    """DART_API_KEY가 없을 때(로컬 개발 등)."""

    async def recent(self, asset_ids, now):
        return {"status": "disabled", "window": None, "items": [], "errors": []}


class DartError(Exception):
    pass


class DartLimit(DartError):
    """020: 요청 제한 초과. 남은 종목은 부르지 않습니다."""


class DartDisclosures:
    def __init__(self, api_key: str, *, lookback_days: int = 7, max_per_asset: int = 5, cache_minutes: float = 30,
                 timeout: float = 15.0, transport: Optional[httpx.AsyncBaseTransport] = None,
                 clock=time.monotonic):
        self._key = api_key
        self.lookback_days, self.max_per_asset = lookback_days, max_per_asset
        self._ttl = cache_minutes * 60
        self._http = httpx.AsyncClient(base_url=BASE, timeout=timeout, transport=transport)
        self._clock = clock
        self._corp: Optional[dict[str, tuple[str, str]]] = None   # 종목코드 → (고유번호, 회사명)
        self._corp_lock = asyncio.Lock()
        self._cache: dict[tuple[str, str, str], tuple[float, list[dict]]] = {}

    async def close(self):
        await self._http.aclose()

    def _safe(self, e: Exception) -> str:
        """로그·묶음에 남길 오류 문구. 인증키는 쿼리 문자열에 들어가므로 지웁니다."""
        return _short(e).replace(self._key, "***")

    # ------------------------------------------------------------------ 고유번호 표
    async def _corp_codes(self) -> dict[str, tuple[str, str]]:
        async with self._corp_lock:
            if self._corp is None:
                r = await self._http.get("/corpCode.xml", params={"crtfc_key": self._key})
                r.raise_for_status()
                self._corp = parse_corp_codes(r.content)
                log.info("DART 고유번호 표 %d개 상장사", len(self._corp))
            return self._corp

    # ------------------------------------------------------------------ 공시 목록
    async def _list(self, corp_code: str, bgn: str, end: str) -> list[dict]:
        r = await self._http.get("/list.json", params={
            "crtfc_key": self._key, "corp_code": corp_code, "bgn_de": bgn, "end_de": end,
            "sort": "date", "sort_mth": "desc", "page_no": 1, "page_count": 100})
        r.raise_for_status()
        body = r.json()
        status = body.get("status")
        if status == "013":                       # 조회된 데이터 없음
            return []
        if status == "020":
            raise DartLimit(body.get("message", "요청 제한 초과"))
        if status != "000":
            raise DartError(f"{status} {body.get('message', '')}".strip())
        return body.get("list") or []

    async def _detail_rows(self, endpoint: str, corp_code: str, bgn: str, end: str) -> list[dict]:
        r = await self._http.get(f"/{endpoint}.json", params={
            "crtfc_key": self._key, "corp_code": corp_code, "bgn_de": bgn, "end_de": end})
        r.raise_for_status()
        body = r.json()
        if body.get("status") == "013":
            return []
        if body.get("status") != "000":
            raise DartError(f"{body.get('status')} {body.get('message', '')}".strip())
        return body.get("list") or []

    async def _attach_details(self, corp_code: str, items: list[dict], bgn: str, end: str):
        """주요사항보고서만 상세를 붙입니다. 같은 종류는 한 번만 부르고 접수번호로 맞춥니다."""
        wanted: dict[str, list[dict]] = {}
        for it in items:
            hit = detail_endpoint(it["report_name"])
            if hit:
                it["detail_type"] = hit[1]
                wanted.setdefault(hit[0], []).append(it)
        for endpoint, its in wanted.items():
            try:
                rows = {r.get("rcept_no"): r for r in await self._detail_rows(endpoint, corp_code, bgn, end)}
            except Exception as e:
                for it in its:
                    it["detail_error"] = self._safe(e)
                log.warning("DART 상세(%s) 실패: %s", endpoint, self._safe(e))
                continue
            for it in its:
                row = rows.get(it["rcept_no"])
                if row is None:
                    it["detail_error"] = "상세 응답에 같은 접수번호 없음"
                else:
                    it["detail"] = {"endpoint": endpoint, "fields": label_fields(endpoint, parse_detail(row))}

    async def _for_asset(self, asset_id: str, bgn: str, end: str) -> list[dict]:
        key = (asset_id, bgn, end)
        hit = self._cache.get(key)
        if hit and self._clock() - hit[0] < self._ttl:
            return hit[1]
        corp = (await self._corp_codes()).get(asset_id)
        if corp is None:                          # 상장사 표에 없음(ETF 등) → 공시 없음으로 처리
            items = []
        else:
            items = [_item(asset_id, corp[1], row) for row in await self._list(corp[0], bgn, end)]
            items = items[: self.max_per_asset]
            await self._attach_details(corp[0], items, bgn, end)
        self._cache[key] = (self._clock(), items)
        return items

    async def recent(self, asset_ids, now):
        end_d = now.astimezone(KST).date()
        bgn, end = _ymd(end_d - timedelta(days=self.lookback_days)), _ymd(end_d)
        window = {"from": _iso(bgn), "to": _iso(end), "timezone": "Asia/Seoul"}
        items, errors = [], []
        try:
            await self._corp_codes()
        except Exception as e:
            log.warning("DART 고유번호 표 실패: %s", self._safe(e))
            return {"status": "failed", "window": window, "items": [], "errors": [f"corp_code: {self._safe(e)}"]}
        for aid in asset_ids:
            try:
                items.extend(await self._for_asset(aid, bgn, end))
            except DartLimit as e:
                errors.append(f"{aid}: 요청 제한 초과({self._safe(e)})")
                log.warning("DART 요청 제한 초과, 남은 %d종목 건너뜀", len(asset_ids) - asset_ids.index(aid))
                break
            except Exception as e:
                errors.append(f"{aid}: {self._safe(e)}")
                log.warning("DART 공시 조회 실패 %s: %s", aid, self._safe(e))
        status = "ok" if not errors else ("partial" if items else "failed")
        return {"status": status, "window": window, "items": items, "errors": errors}


# ---------------------------------------------------------------------------
def parse_corp_codes(content: bytes) -> dict[str, tuple[str, str]]:
    """corpCode.xml 응답(ZIP 안의 CORPCODE.xml)에서 상장사만 뽑습니다. 키가 틀리면 ZIP이 아닌 오류 응답이 옵니다."""
    if not zipfile.is_zipfile(io.BytesIO(content)):
        raise DartError("고유번호 응답이 ZIP이 아닙니다: " + content[:200].decode("utf-8", "replace"))
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        xml = z.read(z.namelist()[0])
    out = {}
    for el in ElementTree.fromstring(xml).iter("list"):
        stock = (el.findtext("stock_code") or "").strip()
        if stock:
            out[stock] = ((el.findtext("corp_code") or "").strip(), (el.findtext("corp_name") or "").strip())
    return out


def _item(asset_id: str, corp_name: str, row: dict) -> dict:
    rcept_no = row.get("rcept_no", "")
    return {
        "rcept_no": rcept_no,
        "asset_id": asset_id,
        "corp_name": row.get("corp_name") or corp_name,
        "report_name": " ".join((row.get("report_nm") or "").split()),
        "filer": row.get("flr_nm"),
        "received_date": _iso(row.get("rcept_dt", "")),
        "remark": (row.get("rm") or "").strip() or None,   # 유(유가증권 공시)·코(코스닥)·정(정정) 등 DART 비고
        "url": VIEWER.format(rcept_no),
    }


def _ymd(d: date) -> str:
    return d.strftime("%Y%m%d")


def _iso(ymd: str) -> str:
    return f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:8]}" if len(ymd) == 8 else ymd


def _short(e: Exception) -> str:
    if isinstance(e, httpx.HTTPStatusError):        # 메시지에 URL(=인증키)이 들어 있어 상태코드만 남김
        return f"HTTP {e.response.status_code}"
    if isinstance(e, httpx.RequestError):
        return type(e).__name__
    return f"{type(e).__name__}: {e}"[:200]


def from_env(env) -> DisclosureSource:
    key = env.get("DART_API_KEY")
    if not key:
        log.info("DART_API_KEY 없음: 공시 근거 없이 진행")
        return NoDisclosures()
    return DartDisclosures(key, lookback_days=int(env.get("DART_LOOKBACK_DAYS", "7")),
                           max_per_asset=int(env.get("DART_MAX_PER_ASSET", "5")),
                           cache_minutes=float(env.get("DART_CACHE_MINUTES", "30")))
