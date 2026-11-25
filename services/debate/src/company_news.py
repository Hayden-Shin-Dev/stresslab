"""Company-specific Google News RSS headlines from the last three calendar months."""

from __future__ import annotations

import asyncio
import calendar
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse
import xml.etree.ElementTree as ET

import httpx

FEED_URL = "https://news.google.com/rss/search"
_cache: dict[str, tuple[datetime, dict]] = {}
_lock = asyncio.Lock()
_ttl = timedelta(minutes=5)


def three_months_before(now: datetime) -> datetime:
    month = now.month - 3
    year = now.year
    if month <= 0:
        month += 12
        year -= 1
    day = min(now.day, calendar.monthrange(year, month)[1])
    return now.replace(year=year, month=month, day=day)


def _fetch(company: str, start: datetime, end: datetime) -> list[dict]:
    query = f'"{company}" after:{start:%Y-%m-%d} before:{end + timedelta(days=1):%Y-%m-%d}'
    response = httpx.get(FEED_URL, params={"q": query, "hl": "ko", "gl": "KR", "ceid": "KR:ko"}, timeout=20)
    response.raise_for_status()
    root = ET.fromstring(response.content)
    articles = []
    seen = set()
    for item in root.findall("./channel/item"):
        title = (item.findtext("title") or "").strip()[:400]
        url = (item.findtext("link") or "").strip()
        parsed = urlparse(url)
        if not title or parsed.scheme not in {"http", "https"} or not parsed.netloc or url in seen:
            continue
        try:
            published = parsedate_to_datetime(item.findtext("pubDate") or "").astimezone(timezone.utc)
        except (TypeError, ValueError, IndexError):
            continue
        if not start <= published <= end:
            continue
        source = item.find("source")
        articles.append({"title": title, "url": url,
                         "publisher": ((source.text or "") if source is not None else "").strip()[:120],
                         "publishedAt": published.isoformat().replace("+00:00", "Z"),
                         "category": "company"})
        seen.add(url)
        if len(articles) >= 50:
            break
    return articles


async def latest(company: str) -> dict:
    company = " ".join(company.split())
    if not 2 <= len(company) <= 40 or any(char in company for char in '"<>'):
        raise ValueError("Invalid company name")
    now = datetime.now(timezone.utc)
    cached = _cache.get(company)
    if cached and now - cached[0] < _ttl:
        return cached[1]
    async with _lock:
        now = datetime.now(timezone.utc)
        cached = _cache.get(company)
        if cached and now - cached[0] < _ttl:
            return cached[1]
        start = three_months_before(now)
        try:
            articles = await asyncio.wait_for(asyncio.to_thread(_fetch, company, start, now), timeout=25)
        except Exception as exc:
            raise RuntimeError("기업 뉴스 제공처에서 자료를 받지 못했습니다.") from exc
        payload = {"source": "Google News RSS", "company": company,
                   "from": start.date().isoformat(), "to": now.date().isoformat(),
                   "fetchedAt": now.isoformat().replace("+00:00", "Z"), "articles": articles}
        if len(_cache) >= 100:
            _cache.clear()
        _cache[company] = (now, payload)
        return payload
