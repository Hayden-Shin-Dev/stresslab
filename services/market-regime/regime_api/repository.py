"""Where the API reads the published regime snapshot from.

REGIME_SOURCE=postgres  → latest row of regime.snapshot (Fabric pipeline Copy target)   [운영 권장]
REGIME_SOURCE=file      → a snapshot JSON file, or a directory holding latest.json (e.g. a copy
                          of Fabric Files/regime, or a mounted OneLake/Blob path)          [개발·대체]
Every read verifies sha256 and refuses synthetic data unless REGIME_ALLOW_SYNTHETIC=true.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from pathlib import Path


class SnapshotUnavailable(RuntimeError):
    pass


def _parse(payload_text: str, expected_sha: str | None, allow_synthetic: bool):
    raw = payload_text.encode("utf-8")
    sha = hashlib.sha256(raw).hexdigest()
    if expected_sha and sha != expected_sha.strip():
        raise SnapshotUnavailable("SNAPSHOT_SHA256_MISMATCH")
    snap = json.loads(payload_text)
    if snap.get("schema") != "market_regime_snapshot" or snap.get("schema_version") != 1:
        raise SnapshotUnavailable("SNAPSHOT_SCHEMA_UNSUPPORTED")
    if snap.get("data_mode") != "fabric_gold" and not allow_synthetic:
        raise SnapshotUnavailable("SYNTHETIC_SNAPSHOT_REFUSED")
    return snap, sha


class FileSnapshotRepository:
    def __init__(self, path: str, allow_synthetic: bool = False):
        self.path = Path(path)
        self.allow_synthetic = allow_synthetic
        self._cache = None  # (key, snap, sha)
        self._lock = threading.Lock()

    def _resolve(self):
        p = self.path
        if p.is_dir():
            ptr = json.loads((p / "latest.json").read_text(encoding="utf8"))
            rel = ptr["path"]
            # latest.json paths are relative to Files/ (…/regime/snapshots/<v>/regime_snapshot.json)
            cand = p.parent / rel if (p.parent / rel).exists() else p / rel.split("regime/", 1)[-1]
            return cand, ptr.get("sha256")
        sha_file = p.with_suffix(".sha256")
        return p, sha_file.read_text().strip() if sha_file.exists() else None

    def latest(self):
        try:
            f, sha = self._resolve()
            key = (str(f), f.stat().st_mtime_ns)
        except (OSError, KeyError, ValueError) as e:
            raise SnapshotUnavailable("SNAPSHOT_FILE_UNAVAILABLE") from e
        with self._lock:
            if self._cache and self._cache[0] == key:
                return self._cache[1], self._cache[2]
            snap, real = _parse(f.read_text(encoding="utf8"), sha, self.allow_synthetic)
            self._cache = (key, snap, real)
            return snap, real


class PostgresSnapshotRepository:
    SQL = ("select snapshot_version, payload_text, payload_sha256 from regime.snapshot "
           "where data_mode = any(%s) order by as_of desc, created_at desc limit 1")

    def __init__(self, dsn: str, allow_synthetic: bool = False, ttl_seconds: int = 300):
        self.dsn = dsn
        self.allow_synthetic = allow_synthetic
        self.ttl = ttl_seconds
        self._cache = None  # (fetched_at, snap, sha)
        self._lock = threading.Lock()

    def latest(self):
        with self._lock:
            if self._cache and time.time() - self._cache[0] < self.ttl:
                return self._cache[1], self._cache[2]
            try:
                import psycopg  # psycopg 3
                modes = ["fabric_gold", "synthetic_fixture"] if self.allow_synthetic else ["fabric_gold"]
                with psycopg.connect(self.dsn, connect_timeout=5) as conn, conn.cursor() as cur:
                    cur.execute(self.SQL, (modes,))
                    row = cur.fetchone()
            except Exception as e:  # network / auth / missing table
                if self._cache:      # serve the last good snapshot rather than failing the page
                    return self._cache[1], self._cache[2]
                raise SnapshotUnavailable("POSTGRES_UNAVAILABLE:" + type(e).__name__) from e
            if not row:
                raise SnapshotUnavailable("NO_SNAPSHOT_ROWS")
            snap, sha = _parse(row[1], row[2], self.allow_synthetic)
            self._cache = (time.time(), snap, sha)
            return snap, sha


def from_env():
    allow = os.environ.get("REGIME_ALLOW_SYNTHETIC", "false").lower() == "true"
    source = os.environ.get("REGIME_SOURCE", "postgres").lower()
    if source == "postgres":
        dsn = os.environ.get("REGIME_PG_DSN")
        if not dsn:
            raise RuntimeError("REGIME_PG_DSN is required when REGIME_SOURCE=postgres")
        return PostgresSnapshotRepository(dsn, allow, int(os.environ.get("REGIME_CACHE_SECONDS", "300")))
    if source == "file":
        return FileSnapshotRepository(os.environ["REGIME_SNAPSHOT_PATH"], allow)
    raise RuntimeError("REGIME_SOURCE must be postgres or file")
