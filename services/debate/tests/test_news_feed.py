"""Google News RSS adapter tests."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import news_feed  # noqa: E402


def test_fetch_parses_korean_google_news_rss(monkeypatch):
    xml = """<?xml version="1.0"?>
    <rss><channel>
      <item>
        <title>기사 제목</title>
        <link>https://news.example/article</link>
        <pubDate>Mon, 23 Nov 2026 10:00:00 GMT</pubDate>
        <source>언론사</source>
      </item>
    </channel></rss>""".encode("utf-8")
    requested = {}

    class Response:
        content = xml

        def raise_for_status(self):
            pass

    def get(url, *, params, timeout):
        requested.update(url=url, params=params, timeout=timeout)
        return Response()

    monkeypatch.setattr(news_feed.httpx, "get", get)

    articles = news_feed._fetch("politics")

    assert requested["url"] == news_feed.FEED_URL
    assert requested["params"] == {"q": "정치 when:7d", "hl": "ko", "gl": "KR", "ceid": "KR:ko"}
    assert requested["timeout"] == 20
    assert articles == [{
        "title": "기사 제목",
        "url": "https://news.example/article",
        "published date": "Mon, 23 Nov 2026 10:00:00 GMT",
        "publisher": {"title": "언론사"},
    }]
