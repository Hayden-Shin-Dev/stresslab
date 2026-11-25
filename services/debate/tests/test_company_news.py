"""Company news date window and RSS filtering tests."""

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import company_news


class CompanyNewsTests(unittest.TestCase):
    def test_three_calendar_months_preserves_valid_day(self):
        self.assertEqual(company_news.three_months_before(datetime(2026, 5, 31, tzinfo=timezone.utc)),
                         datetime(2026, 2, 28, tzinfo=timezone.utc))

    def test_feed_keeps_only_window_and_unique_articles(self):
        xml = b"""<rss><channel>
        <item><title>Recent</title><link>https://example.com/a</link><pubDate>Mon, 23 Nov 2026 01:00:00 GMT</pubDate><source>Press</source></item>
        <item><title>Duplicate</title><link>https://example.com/a</link><pubDate>Mon, 23 Nov 2026 01:00:00 GMT</pubDate></item>
        <item><title>Old</title><link>https://example.com/b</link><pubDate>Mon, 20 Jul 2026 01:00:00 GMT</pubDate></item>
        </channel></rss>"""
        class Response:
            content = xml
            def raise_for_status(self):
                pass
        with patch.object(company_news.httpx, "get", return_value=Response()) as get:
            rows = company_news._fetch("삼성전자", datetime(2026, 8, 23, tzinfo=timezone.utc),
                                       datetime(2026, 11, 23, 2, tzinfo=timezone.utc))
        self.assertEqual([row["title"] for row in rows], ["Recent"])
        self.assertIn('"삼성전자"', get.call_args.kwargs["params"]["q"])
        self.assertEqual(rows[0]["publisher"], "Press")


if __name__ == "__main__":
    unittest.main()
