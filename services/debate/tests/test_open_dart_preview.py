"""DART original preview must return readable text without trusting archive contents."""
import asyncio
import io
import stat
import sys
import zipfile
from pathlib import Path

import pytest
import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import open_dart  # noqa: E402


def archive(files: dict[str, bytes]) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zipped:
        for name, content in files.items():
            zipped.writestr(name, content)
    return out.getvalue()


def test_original_preview_extracts_text_and_drops_executable_markup():
    source = ("<?xml version='1.0' encoding='UTF-8'?>"
              "<DOCUMENT><TITLE>사업보고서</TITLE><BODY><P>매출 &amp; 영업이익</P>"
              "<SCRIPT>alert('unsafe')</SCRIPT><STYLE>body{display:none}</STYLE>"
              "<TABLE><TR><TD>2026년</TD><TD>100억원</TD></TR></TABLE>"
              "<P>&lt;img src=x onerror=alert(1)&gt;</P></BODY></DOCUMENT>").encode()
    text, truncated = open_dart.original_preview_text(archive({"report.xml": source}))

    assert not truncated
    assert "사업보고서" in text and "매출 & 영업이익" in text
    assert "2026년" in text and "100억원" in text
    assert "alert('unsafe')" not in text and "display:none" not in text
    assert "<img src=x onerror=alert(1)>" in text  # remains text; frontend must escape it


def test_original_preview_preserves_tables_without_executable_markup():
    source = ("<DOCUMENT><BODY><P>리스부채 (단위: 천원)</P>"
              "<TABLE onclick='steal()'><TR><TH>구분</TH><TH>당기말</TH><TH>전기말</TH></TR>"
              "<TR><TD rowspan='2'>유동</TD><TD>53,840,044</TD><TD>48,651,247</TD></TR>"
              "<TR><TD colspan='2' style='color:red'>합계 &amp; 주석</TD></TR></TABLE>"
              "<IMG src='bad' onerror='steal()'><SCRIPT>steal()</SCRIPT>"
              "<P>&lt;script&gt;unsafe&lt;/script&gt;</P></BODY></DOCUMENT>").encode()
    text, markup, truncated = open_dart.original_preview_data(archive({"report.xml": source}))

    assert not truncated and "53,840,044" in text
    assert "<table>" in markup and "<tr>" in markup
    assert '<td rowspan="2">유동</td>' in markup
    assert '<td colspan="2">합계 &amp; 주석</td>' in markup
    assert "onclick" not in markup and "style=" not in markup and "<img" not in markup
    assert "steal()" not in markup and "&lt;script&gt;unsafe&lt;/script&gt;" in markup


@pytest.mark.parametrize("name", ["../secret.xml", "/absolute.xml", "C:\\secret.xml"])
def test_original_preview_rejects_unsafe_archive_names(name):
    with pytest.raises(open_dart.OpenDartError) as raised:
        open_dart.original_preview_text(archive({name: b"<DOCUMENT>secret</DOCUMENT>"}))
    assert raised.value.status_code == 502


def test_original_preview_rejects_zip_bomb_before_decompression(monkeypatch):
    monkeypatch.setattr(open_dart, "PREVIEW_MAX_FILE_BYTES", 256)
    content = archive({"report.xml": b"<P>" + b"X" * 5000 + b"</P>"})
    assert len(content) < 256
    with pytest.raises(open_dart.OpenDartError) as raised:
        open_dart.original_preview_text(content)
    assert raised.value.status_code == 502


def test_original_preview_limits_archive_count_and_text_length(monkeypatch):
    monkeypatch.setattr(open_dart, "PREVIEW_MAX_FILES", 1)
    with pytest.raises(open_dart.OpenDartError):
        open_dart.original_preview_text(archive({"one.xml": b"<P>one</P>", "two.xml": b"<P>two</P>"}))

    monkeypatch.setattr(open_dart, "PREVIEW_MAX_TEXT_CHARS", 20)
    text, truncated = open_dart.original_preview_text(archive({"report.xml": b"<P>" + b"A" * 100 + b"</P>"}))
    assert truncated and len(text) <= 20


def test_original_preview_rejects_missing_xml():
    with pytest.raises(open_dart.OpenDartError) as raised:
        open_dart.original_preview_text(archive({"readme.txt": b"not a disclosure"}))
    assert raised.value.status_code == 502


def test_original_preview_never_expands_external_xml_entities():
    malicious = (b'<!DOCTYPE DOCUMENT [<!ENTITY secret SYSTEM "file:///etc/passwd">]>'
                 b'<DOCUMENT><P>&secret;</P></DOCUMENT>')
    text, truncated = open_dart.original_preview_text(archive({"report.xml": malicious}))
    assert not truncated
    assert "&secret;" in text and "root:" not in text


def test_original_preview_rejects_symlink_and_corrupt_zip():
    output = io.BytesIO()
    link = zipfile.ZipInfo("report.xml")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(output, "w") as zipped:
        zipped.writestr(link, b"target.xml")
    for content in (output.getvalue(), b"not a ZIP"):
        with pytest.raises(open_dart.OpenDartError) as raised:
            open_dart.original_preview_text(content)
        assert raised.value.status_code == 502


def test_original_preview_bounds_upstream_response_while_streaming(monkeypatch):
    monkeypatch.setattr(open_dart, "PREVIEW_MAX_ARCHIVE_BYTES", 128)
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=b"X" * 129))
    client = open_dart.OpenDartClient("test-key", transport=transport)

    async def run():
        try:
            with pytest.raises(open_dart.OpenDartError) as raised:
                await client.original_preview("20261121000001")
            assert raised.value.status_code == 502
        finally:
            await client.close()

    asyncio.run(run())


@pytest.mark.parametrize("dart_status,http_status", [("013", 404), ("010", 503)])
@pytest.mark.parametrize("preview", [False, True])
def test_original_zip_and_preview_preserve_dart_error_codes(dart_status, http_status, preview):
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"status": dart_status, "message": "DART error"}))
    client = open_dart.OpenDartClient("test-key", transport=transport)

    async def run():
        try:
            with pytest.raises(open_dart.OpenDartError) as raised:
                if preview:
                    await client.original_preview("20261121000001")
                else:
                    await client.original("20261121000001")
            assert raised.value.status_code == http_status
        finally:
            await client.close()

    asyncio.run(run())
