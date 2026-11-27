"""Google News RSS headlines for the scenario news panel.

Article text is intentionally not scraped. The published timestamp belongs
to the publisher, while fetched_at is ours.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse
import xml.etree.ElementTree as ET

import httpx

log = logging.getLogger("debate.news_feed")
TOPIC_QUERY = {"politics": "정치", "economy": "경제", "society": "사회"}
FEED_URL = "https://news.google.com/rss/search"
_cache: dict[str, tuple[datetime, dict]] = {}
_locks = {topic: asyncio.Lock() for topic in TOPIC_QUERY}
_ttl = timedelta(minutes=5)


def _article(raw: dict, topic: str) -> dict | None:
    title = str(raw.get("title") or "").strip()[:400]
    url = str(raw.get("url") or "").strip()
    parsed = urlparse(url)
    if not title or parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None
    source = raw.get("publisher") or {}
    publisher = str(source.get("title") if isinstance(source, dict) else source).strip()[:120]
    published = str(raw.get("published date") or "").strip()
    try:
        date = parsedate_to_datetime(published)
        published_at = date.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    except (TypeError, ValueError, IndexError):
        published_at = None
    return {"title": title, "url": url, "publisher": publisher,
            "publishedAt": published_at, "category": topic}


def _fetch(topic: str) -> list[dict]:
    response = httpx.get(FEED_URL, params={
        "q": "(경제 OR 환율 OR 미국 국채 OR WTI OR VIX) when:1d" if topic == "economy" else f"{TOPIC_QUERY[topic]} when:7d",
        "hl": "ko",
        "gl": "KR",
        "ceid": "KR:ko",
    }, timeout=20)
    response.raise_for_status()
    root = ET.fromstring(response.content)
    items = []
    for item in root.findall("./channel/item")[:24]:
        source = item.find("source")
        items.append({
            "title": item.findtext("title", ""),
            "url": item.findtext("link", ""),
            "published date": item.findtext("pubDate", ""),
            "publisher": {"title": source.text or ""} if source is not None else {},
        })
    return items


async def latest(topic: str) -> dict:
    if topic not in TOPIC_QUERY:
        raise ValueError("Unsupported news topic")
    now = datetime.now(timezone.utc)
    cached = _cache.get(topic)
    if cached and now - cached[0] < _ttl:
        return cached[1]
    async with _locks[topic]:
        now = datetime.now(timezone.utc)
        cached = _cache.get(topic)
        if cached and now - cached[0] < _ttl:
            return cached[1]
        try:
            raw_items = await asyncio.wait_for(asyncio.to_thread(_fetch, topic), timeout=25)
        except (Exception, asyncio.TimeoutError) as exc:
            log.warning("Google News feed unavailable for %s: %s", topic, type(exc).__name__)
            raise RuntimeError("뉴스 제공처에서 자료를 받지 못했습니다.") from exc
        articles = []
        seen = set()
        for raw in raw_items:
            article = _article(raw, topic)
            if article and article["url"] not in seen:
                articles.append(article)
                seen.add(article["url"])
        if not articles:
            raise RuntimeError("뉴스 제공처에서 표시할 기사를 받지 못했습니다.")
        payload = {"source": "Google News RSS via GNews", "topic": topic,
                   "fetchedAt": now.isoformat().replace("+00:00", "Z"),
                   "articles": articles}
        _cache[topic] = (now, payload)
        return payload
