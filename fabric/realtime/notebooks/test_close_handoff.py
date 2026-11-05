"""마감 인계 계산·게시·읽기 검증 (합성 자료, Fabric 불필요).

실행: python -m pytest fabric/realtime/notebooks -q
"""
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent))
import close_handoff as ch  # noqa: E402

DAY = date(2026, 11, 4)
START = pd.Timestamp("2026-11-04T00:00:00Z")   # KST 09:00


def make_inputs():
    rows = []
    minutes = pd.date_range(START, periods=380, freq="1min")
    for i, t in enumerate(minutes):   # 005930: 전부 있음, 10:00 분봉 한 번 정정
        rows.append(dict(asset_id="005930", bar_at=t, open=100 + i, high=101 + i, low=99 + i, close=100.5 + i,
                         volume=10, ticks=3, last_cum=10 * (i + 1), ingested_at=t + pd.Timedelta(seconds=70)))
    rows.append(dict(rows[60], close=999.0, ingested_at=rows[60]["ingested_at"] + pd.Timedelta(minutes=2)))
    gaps = set(pd.date_range("2026-11-04T01:00:00Z", periods=5, freq="1min")) | {pd.Timestamp("2026-11-04T04:30:00Z")}
    for t in minutes:                  # 000660: 10:00~10:04, 13:30 없음
        if t not in gaps:
            rows.append(dict(asset_id="000660", bar_at=t, open=5, high=6, low=4, close=5, volume=1, ticks=1,
                             last_cum=1, ingested_at=t + pd.Timedelta(seconds=70)))
    bars = pd.DataFrame(rows)
    events = pd.DataFrame([
        dict(asset_id="005930", events=1200, unique_events=1195, non_regular=3, date_inferred=0, no_event_time=0,
             late=2, first_event_time=pd.Timestamp("2026-11-04T00:00:01Z"), last_event_time=pd.Timestamp("2026-11-04T06:19:59Z")),
        dict(asset_id="000660", events=900, unique_events=900, non_regular=0, date_inferred=1, no_event_time=4,
             late=0, first_event_time=pd.Timestamp("2026-11-04T00:00:03Z"), last_event_time=pd.Timestamp("2026-11-04T06:19:58Z")),
    ])
    as_of = [t for t in pd.date_range("2026-11-04T00:01:00Z", "2026-11-04T06:20:00Z", freq="1min")
             if t != pd.Timestamp("2026-11-04T01:17:00Z")]           # 10:17 누락
    snaps = pd.DataFrame({"as_of": as_of, "quality_status": "valid", "valid": 2, "expected": 3})
    return ["005930", "000660", "035420"], events, bars, snaps


def test_build_handoff_counts_and_status():
    universe, events, bars, snaps = make_inputs()
    h = ch.build_handoff(DAY, universe, events, bars, snaps, datetime(2026, 11, 4, 7, 10, tzinfo=timezone.utc))
    r = {x["asset_id"]: x for x in h["rows"]}
    assert h["batch_id"] == "realtime_close_20261104_161000"
    assert h["status"] == "partial"
    assert r["005930"]["status"] == "complete" and r["005930"]["bars_revised"] == 1
    assert r["005930"]["duplicate_events"] == 5 and r["005930"]["late_events"] == 2
    assert r["005930"]["last_bar_close"] == 100.5 + 379 and r["005930"]["first_bar_open"] == 100
    assert r["005930"]["is_official_close"] is False
    assert r["000660"]["status"] == "partial" and r["000660"]["bars_missing"] == 6
    assert r["000660"]["missing_minutes_kst"] == ["10:00~10:04", "13:30"]
    assert r["035420"]["status"] == "missing" and r["035420"]["events"] == 0 and r["035420"]["last_bar_close"] is None
    m = h["market"]
    assert m["snapshots_expected"] == 380 and m["snapshots_saved"] == 379 and m["snapshots_missing_kst"] == ["10:17"]
    assert m["snapshots_status"] == "partial"
    assert h["missing_assets"] == ["035420"] and h["partial_assets"] == ["000660"]


def test_revision_uses_latest_value():
    universe, events, bars, snaps = make_inputs()
    h = ch.build_handoff(DAY, universe, events, bars, snaps, datetime(2026, 11, 4, 7, 10, tzinfo=timezone.utc))
    r = {x["asset_id"]: x for x in h["rows"]}["005930"]
    assert r["high"] == 101 + 379    # 정정 행(close=999)은 고가에 영향 없음, 중복 집계 없음
    assert r["bars_observed"] == 380


def test_complete_day_and_holiday():
    universe, events, bars, snaps = make_inputs()
    only = bars[bars.asset_id == "005930"]
    full_snaps = pd.DataFrame({"as_of": pd.date_range("2026-11-04T00:01:00Z", "2026-11-04T06:20:00Z", freq="1min"),
                               "quality_status": "valid", "valid": 1, "expected": 1})
    h = ch.build_handoff(DAY, ["005930"], events[events.asset_id == "005930"], only, full_snaps,
                         datetime(2026, 11, 4, 7, 10, tzinfo=timezone.utc))
    assert h["status"] == "complete" and h["market"]["snapshots_status"] == "complete"
    gappy = ch.build_handoff(DAY, ["005930"], events[events.asset_id == "005930"], only, full_snaps.iloc[10:],
                             datetime(2026, 11, 4, 7, 10, tzinfo=timezone.utc))
    assert gappy["status"] == "complete" and gappy["market"]["snapshots_missing_kst"] == ["09:01~09:10"]
    empty = ch.build_handoff(DAY, universe, events.iloc[0:0], bars.iloc[0:0], snaps.iloc[0:0],
                             datetime(2026, 11, 4, 7, 10, tzinfo=timezone.utc))
    assert empty["status"] == "no_market_observations"


def test_publish_and_read_roundtrip(tmp_path):
    universe, events, bars, snaps = make_inputs()
    h = ch.build_handoff(DAY, universe, events, bars, snaps, datetime(2026, 11, 4, 7, 10, tzinfo=timezone.utc))
    ch.publish(tmp_path, h)
    later = ch.build_handoff(DAY, universe, events, bars, snaps, datetime(2026, 11, 4, 9, 0, tzinfo=timezone.utc))
    ch.publish(tmp_path, later)                       # 재실행 → 새 batch_id
    assert ch.latest_batch_id(tmp_path, DAY) == "realtime_close_20261104_180000"
    manifest, assets, market = ch.read_realtime_close(tmp_path, h["batch_id"])
    assert manifest["status"] == "partial" and manifest["is_official_close"] is False
    assert sorted(assets["asset_id"]) == sorted(universe) and market["snapshots_saved"] == 379
    assert not list(tmp_path.rglob("*.tmp"))


def test_read_rejects_tampered_file(tmp_path):
    universe, events, bars, snaps = make_inputs()
    h = ch.build_handoff(DAY, universe, events, bars, snaps, datetime(2026, 11, 4, 7, 10, tzinfo=timezone.utc))
    ch.publish(tmp_path, h)
    f = tmp_path / "realtime" / "close" / h["batch_id"] / "assets.json"
    f.write_text(f.read_text(encoding="utf-8").replace("partial", "complete"), encoding="utf-8")
    with pytest.raises(ValueError, match="checksum_mismatch"):
        ch.read_realtime_close(tmp_path, h["batch_id"])
    with pytest.raises(ValueError, match="invalid_batch_id"):
        ch.read_realtime_close(tmp_path, "../krx")


def test_kql_has_trade_date_window():
    q = ch.kql_queries(DAY)
    assert "datetime(2026-11-04)" in q["bars"] and "380m" in q["bars"]
    assert "6h + 20m" in q["snapshots"] and "count_distinct" in q["events"]
