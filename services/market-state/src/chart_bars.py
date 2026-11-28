"""Persistent KST trading-day snapshots for chart history."""
import asyncio
import gzip
import json
import logging
from datetime import datetime, time, timedelta, timezone
from threading import Lock
from time import monotonic

from azure.core import MatchConditions
from azure.core.exceptions import ResourceNotFoundError
from azure.storage.blob import ContainerClient

log = logging.getLogger(__name__)
KST = timezone(timedelta(hours=9))
MINUTE = timedelta(minutes=1)
SETTLE = timedelta(minutes=15)


def dates_between(first, last):
    return [first + timedelta(days=index) for index in range((last - first).days + 1)]


def daily_bar(minutes):
    if not minutes:
        return None
    return {
        "at": minutes[-1]["at"], "open": minutes[0]["open"],
        "high": max(point["high"] for point in minutes),
        "low": min(point["low"] for point in minutes),
        "price": minutes[-1]["price"],
        "volume": (sum(point["volume"] for point in minutes)
                   if all(point["volume"] is not None for point in minutes) else None),
    }


def load_minutes(fetch, start, end):
    """Reduce memory if a trading day's deduplication exceeds Eventhouse capacity."""
    try:
        return fetch(start, end)
    except Exception:
        if end - start <= timedelta(minutes=10):
            raise
        minute_count = (end - start) // MINUTE
        middle = start + (minute_count // 2) * MINUTE
        left = load_minutes(fetch, start, middle)
        right = load_minutes(fetch, middle, end)
        for code, rows in right.items():
            left.setdefault(code, []).extend(rows)
        return left


class ChartBars:
    def __init__(self, url, credential, fetch_minutes):
        self.container = ContainerClient.from_container_url(
            url, credential=credential, retry_total=1, connection_timeout=3, read_timeout=8,
        )
        self.fetch_minutes = fetch_minutes
        self.cache = {}
        self.locks = tuple(Lock() for _ in range(32))
        self.cache_lock = Lock()

    def _blob(self, day):
        return self.container.get_blob_client(f"{day.isoformat()}.json.gz")

    def _remember(self, day, snapshot, etag):
        with self.cache_lock:
            self.cache.pop(day, None)
            self.cache[day] = (monotonic(), snapshot, etag)
            if len(self.cache) > 34:
                self.cache.pop(next(iter(self.cache)))

    def _load(self, day, force=False):
        with self.cache_lock:
            cached = self.cache.get(day)
        # Live snapshots can be produced by another replica.
        ttl = 300 if cached and cached[1] and cached[1]["final"] else 20
        if not force and cached and monotonic() - cached[0] < ttl:
            return cached[1], cached[2]
        try:
            data = self._blob(day).download_blob()
            snapshot = json.loads(gzip.decompress(data.readall()))
            etag = data.properties.etag
        except ResourceNotFoundError:
            snapshot, etag = None, None
        self._remember(day, snapshot, etag)
        return snapshot, etag

    def history(self, codes, period, first, last):
        points = {code: [] for code in codes}
        complete = True
        for day in dates_between(first, last):
            # Share downloads across overlapping selections and API requests.
            with self.locks[day.toordinal() % len(self.locks)]:
                snapshot, _ = self._load(day)
            if snapshot is None:
                complete = False
                continue
            if period == "day":
                for code in codes:
                    if code in snapshot["day"]:
                        points[code].append(snapshot["day"][code])
            else:
                for code in codes:
                    points[code].extend(snapshot["minute"].get(code, []))
        return points, complete

    def refresh(self, day, now):
        """Re-read the recent overlap to incorporate delayed and amended events."""
        # Keep the network aggregate outside the day lock so concurrent reads can
        # continue to use the last successfully published snapshot.
        lock = self.locks[day.toordinal() % len(self.locks)]
        with lock:
            previous, etag = self._load(day)
        if previous and previous["final"]:
            return
        start_of_day = datetime.combine(day, time.min, KST).astimezone(timezone.utc)
        end_of_day = start_of_day + timedelta(days=1)
        end = min(end_of_day, now)
        start = start_of_day
        if previous:
            covered = datetime.fromisoformat(previous["through"])
            start = max(start, (covered - SETTLE).replace(second=0, microsecond=0))
        if end <= start:
            return
        tail = load_minutes(self.fetch_minutes, start, end)
        current = {}
        for code in set(tail) | set(previous["minute"] if previous else {}):
            old = previous["minute"].get(code, []) if previous else []
            points = [point for point in old if datetime.fromisoformat(point["at"]) < start]
            points.extend(tail.get(code, []))
            if points:
                current[code] = points
        snapshot = {
            "through": end.isoformat(), "final": now >= end_of_day + SETTLE,
            "minute": current, "day": {code: daily_bar(points) for code, points in current.items()},
        }
        payload = gzip.compress(json.dumps(snapshot, separators=(",", ":")).encode())
        with lock:
            kwargs = {"overwrite": True, "etag": etag, "match_condition": MatchConditions.IfNotModified} if etag else {}
            stored = self._blob(day).upload_blob(payload, **kwargs)
            self._remember(day, snapshot, stored["etag"])

    async def run(self, first_date):
        # Prioritize the current day. Backfill once per date and retry a failed
        # date on the next pass, without fanning out queries against Eventhouse.
        while True:
            started = monotonic()
            now = datetime.now(timezone.utc)
            today = now.astimezone(KST).date()
            first = first_date(now)
            last_live = started
            for day in reversed(dates_between(first, today)):
                try:
                    if day != today and monotonic() - last_live >= 60:
                        newest = datetime.now(timezone.utc)
                        await asyncio.to_thread(self.refresh, newest.astimezone(KST).date(), newest)
                        last_live = monotonic()
                    await asyncio.to_thread(self.refresh, day, datetime.now(timezone.utc))
                except Exception:
                    log.exception("Could not refresh chart bars for %s", day)
                await asyncio.sleep(0.15)
            await asyncio.sleep(max(10, 60 - (monotonic() - started)))
