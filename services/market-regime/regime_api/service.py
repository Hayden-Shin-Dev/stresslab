"""Pure functions: snapshot dict → API response bodies (no web framework, easy to test)."""
from __future__ import annotations

from datetime import date, timedelta

CODES = ("bull", "sideways", "bear")


class BadRequest(ValueError):
    pass


def meta(snap, sha=None):
    return {"schema": snap["schema"], "schema_version": snap["schema_version"],
            "snapshot_version": snap["snapshot_version"], "as_of": snap["as_of"],
            "generated_at": snap["generated_at"], "data_mode": snap["data_mode"],
            "model_version": snap.get("model", {}).get("model_version"),
            "payload_sha256": sha, "notice": snap["notice"]}


def envelope(snap, data, sha=None):
    return {"meta": meta(snap, sha), "data": data}


def _date(s, name):
    if s is None:
        return None
    try:
        return date.fromisoformat(s)
    except (TypeError, ValueError):
        raise BadRequest(f"{name} must be YYYY-MM-DD")


def current(snap):
    return {**snap["current"], "regimes": snap["regimes"]}


def history(snap, start=None, end=None, years=None):
    rows = snap["history"]
    s, e = _date(start, "start"), _date(end, "end")
    if years is not None:
        if not (0 < float(years) <= 30):
            raise BadRequest("years must be in (0, 30]")
        s = date.fromisoformat(snap["as_of"]) - timedelta(days=int(float(years) * 365.25))
    if s and e and s > e:
        raise BadRequest("start must be <= end")
    out = [r for r in rows if (not s or r["date"] >= s.isoformat()) and (not e or r["date"] <= e.isoformat())]
    return {"count": len(out), "fields": ["date", "kospi", "regime", "p_bull", "p_sideways", "p_bear", "raw", "basis"],
            "basis_legend": {"wf": "walk_forward (그날까지의 자료만 사용)", "is": "initial_in_sample (첫 학습 구간)"},
            "rows": out}


def runs(snap, regime=None, limit=None):
    out = snap["runs"]
    if regime:
        if regime not in CODES:
            raise BadRequest("regime must be one of bull, sideways, bear")
        out = [r for r in out if r["regime_code"] == regime]
    if limit is not None:
        if int(limit) < 1:
            raise BadRequest("limit must be >= 1")
        out = out[-int(limit):]
    return {"count": len(out), "rows": out}


def summary(snap):
    return {"rows": snap["summary"]}


def transitions(snap):
    return snap["transitions"]


def similar(snap):
    return snap["similar"]


def model(snap):
    return {"model": snap["model"], "validation": snap["validation"], "quality": snap["quality"],
            "data_version": snap["data_version"], "core_version": snap.get("core_version")}
