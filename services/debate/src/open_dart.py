"""Authenticated server-side client for the OpenDART API."""
from __future__ import annotations

import io
import logging
import re
import zipfile
from datetime import datetime, timedelta
from typing import Any
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

import httpx


BASE_URL = "https://opendart.fss.or.kr/api"
REPORT_CODES = {"11011", "11012", "11013", "11014"}
PUBLICATION_TYPES = {"A", "B", "C", "D", "E"}


class _RedactKey(logging.Filter):
    """OpenDART puts its authentication key in the URL query string."""
    _pattern = re.compile(r"(crtfc_key=)[^&\s\"']+")

    def filter(self, record):
        message = record.getMessage()
        if "crtfc_key=" in message:
            record.msg = self._pattern.sub(r"\1***", message)
            record.args = None
        return True


for _name in ("httpx", "httpcore"):
    if not any(isinstance(item, _RedactKey) for item in logging.getLogger(_name).filters):
        logging.getLogger(_name).addFilter(_RedactKey())


class OpenDartError(Exception):
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message
        super().__init__(message)


class OpenDartClient:
    def __init__(self, api_key: str, *, timeout: float = 30.0,
                 transport: httpx.AsyncBaseTransport | None = None):
        self._api_key = api_key
        self._http = httpx.AsyncClient(base_url=BASE_URL, timeout=timeout, transport=transport)
        self._companies: list[dict[str, str]] | None = None

    async def close(self) -> None:
        await self._http.aclose()

    async def _get(self, path: str, **params: str | int) -> httpx.Response:
        try:
            response = await self._http.get(path, params={"crtfc_key": self._api_key, **params})
        except httpx.TimeoutException as exc:
            raise OpenDartError(504, "DART 응답 시간이 초과되었습니다. 잠시 후 다시 시도해 주세요.") from exc
        except httpx.RequestError as exc:
            raise OpenDartError(502, "DART 서버에 연결하지 못했습니다.") from exc
        if response.status_code >= 400:
            raise OpenDartError(502, f"DART 서버가 HTTP {response.status_code}를 반환했습니다.")
        return response

    @staticmethod
    def _json(response: httpx.Response) -> dict[str, Any]:
        try:
            body = response.json()
        except ValueError as exc:
            raise OpenDartError(502, "DART에서 예상하지 못한 응답 형식을 반환했습니다.") from exc
        status = str(body.get("status", ""))
        if status == "013":
            return {**body, "list": []}
        if status == "020":
            raise OpenDartError(429, "DART API 일일 요청 한도에 도달했습니다.")
        if status in {"010", "011"}:
            raise OpenDartError(503, "DART API 인증 설정을 확인해야 합니다.")
        if status and status != "000":
            raise OpenDartError(502, f"DART 응답 오류({status}): {body.get('message', '요청 실패')}")
        return body

    async def _company_codes(self) -> list[dict[str, str]]:
        if self._companies is not None:
            return self._companies
        response = await self._get("/corpCode.xml")
        if not zipfile.is_zipfile(io.BytesIO(response.content)):
            raise OpenDartError(502, "DART 회사 코드 파일을 읽을 수 없습니다.")
        try:
            with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
                names = archive.namelist()
                if not names:
                    raise OpenDartError(502, "DART 회사 코드 파일이 비어 있습니다.")
                xml = archive.read(names[0])
            records = []
            for element in ElementTree.fromstring(xml).iter("list"):
                corp_code = (element.findtext("corp_code") or "").strip()
                corp_name = (element.findtext("corp_name") or "").strip()
                stock_code = (element.findtext("stock_code") or "").strip()
                if corp_code and corp_name:
                    records.append({"corp_code": corp_code, "corp_name": corp_name, "stock_code": stock_code})
        except (KeyError, ValueError, zipfile.BadZipFile, ElementTree.ParseError) as exc:
            raise OpenDartError(502, "DART 회사 코드 파일을 해석할 수 없습니다.") from exc
        self._companies = records
        return records

    async def search_companies(self, query: str) -> list[dict[str, str]]:
        term = re.sub(r"\s+", "", query).casefold()
        if len(term) < 2:
            return []
        records = await self._company_codes()
        matches = [row for row in records if term in re.sub(r"\s+", "", row["corp_name"]).casefold()
                   or (row["stock_code"] and term in row["stock_code"])]
        matches.sort(key=lambda row: (
            0 if re.sub(r"\s+", "", row["corp_name"]).casefold() == term else
            1 if re.sub(r"\s+", "", row["corp_name"]).casefold().startswith(term) else
            2 if row["stock_code"].startswith(term) else 3,
            row["corp_name"],
        ))
        return matches[:30]

    async def disclosures(self, *, corp_code: str, begin: str, end: str,
                          publication_type: str = "", page: int = 1) -> dict[str, Any]:
        params: dict[str, str | int] = {
            "corp_code": corp_code, "bgn_de": begin, "end_de": end,
            "sort": "date", "sort_mth": "desc", "page_no": page, "page_count": 100,
        }
        if publication_type:
            params["pblntf_ty"] = publication_type
        return self._json(await self._get("/list.json", **params))

    async def financials(self, *, corp_code: str, year: str, report_code: str,
                         statement_type: str = "CFS") -> dict[str, Any]:
        return self._json(await self._get("/fnlttSinglAcntAll.json", corp_code=corp_code,
                                          bsns_year=year, reprt_code=report_code, fs_div=statement_type))

    async def major_detail(self, *, corp_code: str, begin: str, end: str,
                           receipt_no: str, report_name: str) -> dict[str, Any]:
        from disclosures import detail_endpoint, label_fields, parse_detail

        match = detail_endpoint(report_name)
        if not match:
            return {"status": "unavailable", "detail_type": None, "fields": {}}
        endpoint, detail_type = match
        body = self._json(await self._get(f"/{endpoint}.json", corp_code=corp_code,
                                         bgn_de=begin, end_de=end))
        row = next((item for item in body.get("list") or [] if item.get("rcept_no") == receipt_no), None)
        if row is None:
            return {"status": "empty", "detail_type": detail_type, "fields": {}}
        return {"status": "ok", "detail_type": detail_type,
                "fields": label_fields(endpoint, parse_detail(row))}

    async def _zip(self, endpoint: str, **params: str) -> bytes:
        response = await self._get(endpoint, **params)
        content = response.content
        if zipfile.is_zipfile(io.BytesIO(content)):
            return content
        try:
            body = response.json()
        except ValueError as exc:
            raise OpenDartError(502, "DART 원문 파일 응답을 해석할 수 없습니다.") from exc
        status = str(body.get("status", ""))
        if status == "020":
            raise OpenDartError(429, "DART API 일일 요청 한도에 도달했습니다.")
        if status in {"010", "011"}:
            raise OpenDartError(503, "DART API 인증 설정을 확인해야 합니다.")
        raise OpenDartError(404 if status == "013" else 502,
                            "DART 원문 파일을 찾을 수 없습니다." if status == "013" else
                            f"DART 원문 응답 오류({status or 'unknown'}).")

    async def original(self, receipt_no: str) -> bytes:
        return await self._zip("/document.xml", rcept_no=receipt_no)

    async def xbrl(self, receipt_no: str, report_code: str) -> bytes:
        return await self._zip("/fnlttXbrl.xml", rcept_no=receipt_no, reprt_code=report_code)


def default_window() -> tuple[str, str]:
    end = datetime.now(ZoneInfo("Asia/Seoul")).date()
    begin = end - timedelta(days=90)
    return begin.strftime("%Y%m%d"), end.strftime("%Y%m%d")
