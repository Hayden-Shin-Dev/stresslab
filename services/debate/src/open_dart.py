"""Authenticated server-side client for the OpenDART API."""
from __future__ import annotations

import io
from html import escape as escape_html
import json
import logging
import re
import stat
import zipfile
from datetime import datetime, timedelta
from html.parser import HTMLParser
from typing import Any
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

import httpx


BASE_URL = "https://opendart.fss.or.kr/api"
REPORT_CODES = {"11011", "11012", "11013", "11014"}
PUBLICATION_TYPES = {"A", "B", "C", "D", "E"}
PREVIEW_MAX_ARCHIVE_BYTES = 16 * 1024 * 1024
PREVIEW_MAX_FILES = 32
PREVIEW_MAX_FILE_BYTES = 24 * 1024 * 1024
PREVIEW_MAX_TOTAL_BYTES = 48 * 1024 * 1024
PREVIEW_MAX_TEXT_CHARS = 300_000
PREVIEW_MAX_MARKUP_TAGS = 20_000


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


class _DocumentText(HTMLParser):
    """Read untrusted DART XML/HTML as plain text, never as browser markup."""

    _breaks = {"br", "p", "div", "tr", "table", "section", "title", "h1", "h2", "h3", "h4", "h5", "h6"}
    _skip = {"script", "style", "noscript", "svg"}

    def __init__(self, limit: int):
        super().__init__(convert_charrefs=True)
        self.limit = limit
        self.parts: list[str] = []
        self.length = 0
        self.truncated = False
        self.skip_depth = 0

    def _append(self, value: str) -> None:
        remaining = self.limit - self.length
        if remaining <= 0:
            self.truncated = True
            return
        if len(value) > remaining:
            value = value[:remaining]
            self.truncated = True
        self.parts.append(value)
        self.length += len(value)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.skip_depth:
            self.skip_depth += 1
        elif tag in self._skip:
            self.skip_depth = 1
        elif tag in self._breaks:
            self._append("\n")

    def handle_endtag(self, tag: str) -> None:
        if self.skip_depth:
            self.skip_depth -= 1
        elif tag in self._breaks:
            self._append("\n")
        elif tag in {"td", "th"}:
            self._append("  ")

    def handle_data(self, data: str) -> None:
        if not self.skip_depth:
            self._append(re.sub(r"\s+", " ", data))

    def result(self) -> str:
        return "\n".join(line.strip() for line in "".join(self.parts).splitlines() if line.strip())


class _DocumentMarkup(HTMLParser):
    """Keep disclosure tables while allowing only inert, escaped document markup."""

    _allowed = {"p", "div", "br", "table", "thead", "tbody", "tfoot", "tr", "td", "th",
                "ul", "ol", "li", "b", "strong", "i", "em", "u", "h1", "h2", "h3", "h4", "h5", "h6"}
    _void = {"br"}
    _skip = {"script", "style", "noscript", "svg"}

    def __init__(self, limit: int):
        super().__init__(convert_charrefs=True)
        self.limit = limit
        self.parts: list[str] = []
        self.stack: list[str] = []
        self.length = 0
        self.tag_count = 0
        self.truncated = False
        self.skip_tag: str | None = None
        self.skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.skip_tag:
            if tag == self.skip_tag:
                self.skip_depth += 1
            return
        if tag in self._skip:
            self.skip_tag = tag
            self.skip_depth = 1
            return
        if tag not in self._allowed or self.truncated:
            return
        if self.tag_count >= PREVIEW_MAX_MARKUP_TAGS:
            self.truncated = True
            return
        self.tag_count += 1
        safe_attrs = ""
        if tag in {"td", "th"}:
            for key, value in attrs:
                if key in {"colspan", "rowspan"} and value and len(value) <= 2 and value.isascii() and value.isdigit():
                    span = int(value)
                    safe_attrs += f' {key}="{span}"' if 1 <= span <= 30 else ""
        self.parts.append(f"<{tag}{safe_attrs}>")
        if tag not in self._void:
            self.stack.append(tag)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in self._void:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if self.skip_tag:
            if tag == self.skip_tag:
                self.skip_depth -= 1
                if not self.skip_depth:
                    self.skip_tag = None
            return
        if tag not in self.stack:
            return
        while self.stack:
            current = self.stack.pop()
            self.parts.append(f"</{current}>")
            if current == tag:
                break

    def handle_data(self, data: str) -> None:
        if self.skip_tag or self.truncated:
            return
        remaining = self.limit - self.length
        if len(data) > remaining:
            data = data[:remaining]
            self.truncated = True
        if data:
            self.parts.append(escape_html(data))
            self.length += len(data)

    def result(self) -> str:
        return "".join(self.parts + [f"</{tag}>" for tag in reversed(self.stack)])


def _decode_document(content: bytes) -> str:
    declaration = re.match(br"\s*<\?xml[^>]*encoding\s*=\s*['\"]([^'\"]+)", content[:200], re.I)
    encoding = declaration.group(1).decode("ascii", "ignore").lower() if declaration else "utf-8"
    if encoding not in {"utf-8", "euc-kr", "cp949", "ks_c_5601-1987"}:
        encoding = "utf-8"
    return content.decode(encoding, "replace")


def original_preview_data(archive_bytes: bytes) -> tuple[str, str, bool]:
    """Extract bounded text and sanitized table markup from a DART original ZIP."""
    if len(archive_bytes) > PREVIEW_MAX_ARCHIVE_BYTES:
        raise OpenDartError(502, "DART 원문 ZIP이 미리보기 크기 제한을 초과했습니다.")
    try:
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
            infos = archive.infolist()
            if not infos or len(infos) > PREVIEW_MAX_FILES:
                raise OpenDartError(502, "DART 원문 ZIP의 파일 구성을 확인할 수 없습니다.")
            if sum(info.file_size for info in infos) > PREVIEW_MAX_TOTAL_BYTES:
                raise OpenDartError(502, "DART 원문 ZIP의 압축 해제 크기가 너무 큽니다.")
            documents = []
            seen_names = set()
            for info in infos:
                name = info.filename.replace("\\", "/")
                parts = name.split("/")
                if (name.startswith("/") or ":" in parts[0] or ".." in parts or
                        info.filename in seen_names or stat.S_IFMT(info.external_attr >> 16) == stat.S_IFLNK):
                    raise OpenDartError(502, "DART 원문 ZIP에 안전하지 않은 파일명이 있습니다.")
                seen_names.add(info.filename)
                if info.file_size > PREVIEW_MAX_FILE_BYTES:
                    raise OpenDartError(502, "DART 원문 파일이 미리보기 크기 제한을 초과했습니다.")
                if not info.is_dir() and name.lower().endswith(".xml"):
                    documents.append(info)
            if not documents:
                raise OpenDartError(502, "DART 원문 ZIP에서 XML 문서를 찾지 못했습니다.")
            parser = _DocumentText(PREVIEW_MAX_TEXT_CHARS)
            markup = _DocumentMarkup(PREVIEW_MAX_TEXT_CHARS)
            for info in documents:
                with archive.open(info) as source:
                    content = source.read(PREVIEW_MAX_FILE_BYTES + 1)
                if len(content) > PREVIEW_MAX_FILE_BYTES:
                    raise OpenDartError(502, "DART 원문 파일이 미리보기 크기 제한을 초과했습니다.")
                decoded = _decode_document(content)
                parser.feed(decoded)
                markup.feed(decoded)
                parser.feed("<br>")
                markup.feed("<br>")
            parser.close()
            markup.close()
            text = parser.result()
            if not text:
                raise OpenDartError(502, "DART 원문에서 표시할 본문을 찾지 못했습니다.")
            return text, markup.result(), parser.truncated or markup.truncated
    except (OSError, RuntimeError, ValueError, zipfile.BadZipFile, NotImplementedError) as exc:
        raise OpenDartError(502, "DART 원문 ZIP을 안전하게 읽을 수 없습니다.") from exc


def original_preview_text(archive_bytes: bytes) -> tuple[str, bool]:
    """Retain the plain-text interface for existing callers."""
    text, _markup, truncated = original_preview_data(archive_bytes)
    return text, truncated


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

    async def _get_limited(self, path: str, max_bytes: int, **params: str | int) -> bytes:
        """Bound the response before buffering an untrusted original archive."""
        try:
            async with self._http.stream("GET", path, params={"crtfc_key": self._api_key, **params}) as response:
                if response.status_code >= 400:
                    raise OpenDartError(502, f"DART 서버가 HTTP {response.status_code}를 반환했습니다.")
                chunks = []
                length = 0
                async for chunk in response.aiter_bytes():
                    length += len(chunk)
                    if length > max_bytes:
                        raise OpenDartError(502, "DART 원문 ZIP이 미리보기 크기 제한을 초과했습니다.")
                    chunks.append(chunk)
                return b"".join(chunks)
        except httpx.TimeoutException as exc:
            raise OpenDartError(504, "DART 응답 시간이 초과되었습니다. 잠시 후 다시 시도해 주세요.") from exc
        except httpx.RequestError as exc:
            raise OpenDartError(502, "DART 서버에 연결하지 못했습니다.") from exc

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
        row = next((item for item in body.get("list") or []
                    if str(item.get("rcept_no") or "") == receipt_no), None)
        if row is None:
            return {"status": "empty", "detail_type": detail_type, "fields": {}}
        return {"status": "ok", "detail_type": detail_type,
                "fields": label_fields(endpoint, parse_detail(row))}

    async def _zip(self, endpoint: str, *, max_bytes: int | None = None, **params: str) -> bytes:
        content = (await self._get_limited(endpoint, max_bytes, **params) if max_bytes is not None
                   else (await self._get(endpoint, **params)).content)
        if zipfile.is_zipfile(io.BytesIO(content)):
            return content
        try:
            body = json.loads(content)
        except ValueError as exc:
            raise OpenDartError(502, "DART 원문 파일 응답을 해석할 수 없습니다.") from exc
        if not isinstance(body, dict):
            raise OpenDartError(502, "DART 원문 파일 응답을 해석할 수 없습니다.")
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

    async def original_preview(self, receipt_no: str) -> tuple[str, str, bool]:
        content = await self._zip("/document.xml", max_bytes=PREVIEW_MAX_ARCHIVE_BYTES, rcept_no=receipt_no)
        return original_preview_data(content)

    async def xbrl(self, receipt_no: str, report_code: str) -> bytes:
        return await self._zip("/fnlttXbrl.xml", rcept_no=receipt_no, reprt_code=report_code)


def default_window() -> tuple[str, str]:
    end = datetime.now(ZoneInfo("Asia/Seoul")).date()
    begin = end - timedelta(days=90)
    return begin.strftime("%Y%m%d"), end.strftime("%Y%m%d")
