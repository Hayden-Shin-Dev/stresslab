"""Read a publicly available publisher article selected from the server's feed."""
import http.client
from functools import lru_cache
from ipaddress import ip_address
import json
import re
import socket
import ssl
from html.parser import HTMLParser
from time import monotonic
from urllib.parse import urljoin, urlsplit

_MAX_BODY = 2 * 1024 * 1024


@lru_cache(maxsize=1)
def _tls():
    return ssl.create_default_context()


class _PublicHTTPS(http.client.HTTPSConnection):
    def connect(self):
        addresses = socket.getaddrinfo(self.host, 443, type=socket.SOCK_STREAM)
        ips = [ip_address(item[4][0]) for item in addresses]
        ips = [getattr(ip, "ipv4_mapped", None) or ip for ip in ips]
        if not ips or any(not ip.is_global or ip.is_multicast or ip.is_reserved for ip in ips):
            raise ValueError("공개 기사 주소를 확인할 수 없습니다.")
        for family, kind, protocol, _, address in addresses:
            conn = socket.socket(family, kind, protocol)
            try:
                conn.settimeout(self.timeout)
                conn.connect(address)
                self.sock = _tls().wrap_socket(conn, server_hostname=self.host)
                return
            except OSError:
                conn.close()
                # A publisher may advertise IPv6 even when only IPv4 is reachable.
        raise OSError("publisher connection failed")


class _BodyParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.bodies = []
        self.visible = []
        self.canonical = ""
        self._stack = []
        self._scripts = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "link" and "canonical" in (attrs.get("rel") or "").lower().split():
            self.canonical = attrs.get("href") or ""
        if tag == "meta" and attrs.get("property") == "og:url" and not self.canonical:
            self.canonical = attrs.get("content") or ""
        if tag in {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
                   "param", "source", "track", "wbr"}:
            if tag in {"br", "hr"}:
                self.handle_data(" ")
            return
        body = tag == "article" or attrs.get("itemprop") == "articleBody" or attrs.get("id") in {
            "dic_area", "articleBodyContents", "article-body", "article-view-content-div", "harmonyContainer"
        }
        skip = tag in {"script", "style", "header", "footer", "aside", "nav", "noscript", "form"}
        self._stack.append((tag, body, skip))
        if tag == "script" and attrs.get("type") == "application/ld+json":
            self._scripts.append([])

    def handle_endtag(self, tag):
        while tag == "script" and self._scripts:
            raw = "".join(self._scripts.pop(0))
            try:
                self._collect(json.loads(raw))
            except (ValueError, RecursionError):
                pass
        for index in range(len(self._stack) - 1, -1, -1):
            if self._stack[index][0] == tag:
                del self._stack[index:]
                break

    def handle_data(self, data):
        if self._scripts and self._stack and self._stack[-1][0] == "script":
            self._scripts[-1].append(data)
        elif any(body for _, body, _ in self._stack) and not any(skip for _, _, skip in self._stack):
            self.visible.append(data.strip())

    def _collect(self, node):
        if isinstance(node, list):
            for item in node:
                self._collect(item)
        elif isinstance(node, dict):
            if isinstance(node.get("articleBody"), str):
                self.bodies.append(node["articleBody"])
            self._collect(node.get("@graph"))


def read_article(source_url: str) -> tuple[str, str]:
    """Return the final publisher URL and body, or fail without a headline substitute."""
    url = source_url
    deadline = monotonic() + 12
    for _ in range(5):
        parts = urlsplit(url)
        if (parts.scheme != "https" or not parts.hostname or parts.username is not None
                or parts.password is not None or parts.port not in (None, 443)):
            raise ValueError("공개 HTTPS 기사 원문만 읽을 수 있습니다.")
        timeout = deadline - monotonic()
        if timeout <= 0:
            break
        conn = _PublicHTTPS(parts.hostname, timeout=min(4, timeout), context=_tls())
        try:
            path = (parts.path or "/") + (("?" + parts.query) if parts.query else "")
            conn.request("GET", path,
                         headers={"Accept": "text/html", "User-Agent": "WHAT IF Article Reader",
                                  "Accept-Encoding": "identity"})
            response = conn.getresponse()
            location = response.getheader("Location")
            if response.status in (301, 302, 303, 307, 308) and location:
                url = urljoin(url, location)
                continue
            if response.status != 200 or "text/html" not in response.headers.get_content_type():
                break
            data = bytearray()
            for chunk in iter(lambda: response.read1(65536), b""):
                data.extend(chunk)
                if len(data) > _MAX_BODY or monotonic() >= deadline:
                    raise ValueError("기사 원문을 읽을 수 있는 범위를 초과했습니다.")
            encoding = response.headers.get_content_charset()
            if not encoding:
                match = re.search(br"charset=[^a-zA-Z0-9_-]*([a-zA-Z0-9_-]+)", data[:4096], re.I)
                encoding = match[1].decode() if match else "utf-8"
            parser = _BodyParser()
            parser.feed(data.decode(encoding, errors="replace"))
        finally:
            conn.close()
        if parts.hostname == "news.google.com" and parser.canonical:
            canonical = urljoin(url, parser.canonical)
            if urlsplit(canonical).hostname != parts.hostname:
                url = canonical
                continue
        if parts.hostname == "news.google.com":
            break
        body = re.sub(r"\s+", " ", max(parser.bodies, key=len, default="") or " ".join(parser.visible)).strip()
        if len(body) >= 100:
            return url, body
        break
    raise ValueError("기사 원문 본문을 읽지 못했습니다. 다른 기사를 선택해 주세요.")
