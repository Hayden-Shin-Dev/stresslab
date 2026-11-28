from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import os
import sys

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "services/market-state/src"))
os.environ.setdefault("KUSTO_QUERY_URI", "https://chart-test.kusto.windows.net")
os.environ.setdefault("KUSTO_DATABASE", "test")
os.environ.setdefault("SCHEMA_PATH", str(ROOT / "contracts/realtime/schema.json"))
import app as market

FIRST = date(2026, 11, 2)
SEALED = date(2026, 11, 27)
SYMBOL = "005930"


class FixedDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        stamp = cls(2026, 12, 10, 1, tzinfo=timezone.utc)
        return stamp.astimezone(tz) if tz else stamp.replace(tzinfo=None)


@pytest.fixture
def endpoint(monkeypatch):
    queries = []
    blob_requests = []

    def execute(_, query, props):
        queries.append(query)
        return SimpleNamespace(primary_results=[[dict(
            asset_id=SYMBOL, at=datetime(2026, 11, 26, 10, 59, 59, tzinfo=timezone.utc),
            price=171500, open=170700, high=176700, low=170700, volume=13630204,
        )]])

    def history(codes, period, first, last):
        blob_requests.append((codes, period, first, last))
        return {code: [{"at": first.isoformat(), "price": 171800}] for code in codes}, True

    monkeypatch.setattr(market, "datetime", FixedDateTime)
    monkeypatch.setattr(market, "monotonic", lambda: 1200)
    monkeypatch.setattr(market, "chart_bars", SimpleNamespace(history=history))
    monkeypatch.setattr(market, "_kusto", SimpleNamespace(execute=execute))
    monkeypatch.setattr(market, "_archive_through", SEALED)
    market.read_saved_bars.cache_clear()
    yield TestClient(market.app), queries, blob_requests
    market.read_saved_bars.cache_clear()


@pytest.mark.parametrize(("period", "view"), [
    ("day", "stock_price_bars_1d_latest"),
    ("minute", "stock_price_bars_1m_latest"),
])
def test_reads_saved_bars_with_kst_bounds_and_no_raw_tick_query(endpoint, period, view):
    client, queries, blob_requests = endpoint
    result = client.get("/market-state/stock-prices", params={
        "period": period, "assets": SYMBOL, "from_date": "2026-11-26", "to_date": "2026-11-27",
    })
    assert result.status_code == 200
    data = result.json()
    assert data["history_source"] == "eventhouse_bars"
    assert data["available_from"] == str(FIRST)
    assert data["tick_available_from"] == "2026-11-10"
    assert data["series"][SYMBOL][0]["volume"] == 13630204
    assert len(queries) == 1 and view in queries[0]
    assert "2026-11-25T15:00:00+00:00" in queries[0]
    assert "2026-11-27T15:00:00+00:00" in queries[0]
    assert "quote_events" not in queries[0]
    assert not blob_requests


def test_merges_unsealed_dates_and_reuses_the_sealed_query(endpoint):
    client, queries, blob_requests = endpoint
    params = {"assets": SYMBOL, "from_date": "2026-11-26", "to_date": "2026-11-29"}
    for _ in range(2):
        data = client.get("/market-state/stock-prices", params=params).json()
        assert data["history_source"] == "eventhouse_bars+blob_snapshots"
        assert [row["at"] for row in data["series"][SYMBOL]] == [
            "2026-11-26T10:59:59+00:00", "2026-11-28",
        ]
    assert len(queries) == 1
    assert blob_requests == [([SYMBOL], "day", date(2026, 11, 28), date(2026, 11, 29))] * 2


def test_archive_failure_falls_back_without_raw_query(endpoint, monkeypatch):
    client, _, blob_requests = endpoint

    def fail(*_):
        raise RuntimeError("KQL backend unavailable")

    monkeypatch.setattr(market, "_kusto", SimpleNamespace(execute=fail))
    data = client.get("/market-state/stock-prices", params={"assets": SYMBOL, "trade_date": str(SEALED)}).json()
    assert data["history_source"] == "blob_snapshots"
    assert data["history_complete"]
    assert blob_requests == [([SYMBOL], "day", SEALED, SEALED)]


@pytest.mark.parametrize("params", [
    {"from_date": "2026-11-28", "to_date": "2026-11-27"},
    {"period": "tick", "to_date": "2026-11-28"},
    {"trade_date": "2026-11-27", "to_date": "2026-11-28"},
    {"to_date": "2026-12-11"},
])
def test_invalid_date_windows_are_rejected_before_fetching(endpoint, params):
    client, queries, blob_requests = endpoint
    response = client.get("/market-state/stock-prices", params={"assets": SYMBOL, **params})
    assert response.status_code == 422
    assert not queries and not blob_requests
