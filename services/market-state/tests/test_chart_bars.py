from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from chart_bars import daily_bar, load_minutes


def test_minute_bars_preserve_daily_ohlc_and_unavailable_volume():
    minutes = [
        dict(at="2026-11-27T01:00:40+00:00", open=102, high=112, low=101, price=105, volume=12),
        dict(at="2026-11-27T01:01:20+00:00", open=105, high=109, low=90, price=103, volume=8),
    ]
    assert daily_bar(minutes) == dict(at=minutes[-1]["at"], open=102, high=112, low=90, price=103, volume=20)
    minutes[1]["volume"] = None
    assert daily_bar(minutes)["volume"] is None
    assert daily_bar([]) is None


def test_memory_fallback_keeps_minute_windows_aligned_and_nonoverlapping():
    start = datetime(2026, 11, 27, tzinfo=timezone.utc)
    end = start + timedelta(minutes=50, seconds=23)
    succeeded = []

    def fetch(left, right):
        if right - left > timedelta(minutes=15):
            raise RuntimeError("memory limit")
        succeeded.append((left, right))
        return {"005930": [{"at": left.isoformat()}]}

    series = load_minutes(fetch, start, end)
    assert succeeded[0][0] == start and succeeded[-1][1] == end
    assert all(left.second == left.microsecond == 0 for left, _ in succeeded)
    assert all(right == following[0] for (_, right), following in zip(succeeded, succeeded[1:]))
    assert [row["at"] for row in series["005930"]] == [left.isoformat() for left, _ in succeeded]
