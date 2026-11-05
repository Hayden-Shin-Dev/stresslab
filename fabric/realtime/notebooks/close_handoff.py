"""장 마감 인계: realtime → batch.

장 마감 후 그날의 체결 원문·분봉·시장 상태 스냅샷을 검사해, batch가 이미 쓰는 Bronze 방식
(파일 + _runs/<배치명>/SUCCESS.json)으로 게시합니다. 이 파일은 계산과 쓰기·읽기만 담고,
Fabric 노트북(close_handoff_notebook.py)이 KQL 결과를 넣어 호출합니다.

게시 위치 (lh_whatif, Files/bronze 기준)
  realtime/close/<batch_id>/assets.json   종목별 마감 행
  realtime/close/<batch_id>/market.json   스냅샷 저장 현황과 전체 요약
  _runs/<batch_id>/SUCCESS.json            manifest (마지막에 씀. 이 파일이 있어야 완료)
  batch_id = realtime_close_<YYYYMMDD>_<HHMMSS KST 생성 시각>  다시 돌리면 새 batch_id. 최신 것을 사용.

원칙
  - 분봉의 마지막 가격은 종가 단일가 이전 가격이라 확정 종가가 아닙니다(is_official_close=false).
  - 체결이 없는 분과 수집 누락은 분봉만으로 구분할 수 없어 '분봉 없음'으로만 셉니다.
  - 값을 보간하거나 0으로 채우지 않습니다.
  - status는 batch가 쓰는 가격 자료(분봉) 기준입니다. 시장 상태 스냅샷 누락은 market.json에 따로 남깁니다.
  - 키움 실시간 체결은 시각만 오고 날짜는 수집기가 붙이므로 date_inferred가 대부분 true입니다(정상).
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

import pandas as pd

HANDOFF_VERSION = "realtime-close-v1"
KST = timezone(timedelta(hours=9))
CONTINUOUS_START = time(9, 0)
CONTINUOUS_MINUTES = 380            # 09:00~15:19 시작 분봉 (15:20부터 종가 단일가)
SNAPSHOT_FIRST, SNAPSHOT_LAST = time(9, 1), time(15, 20)   # 시장 상태 as_of 범위 (380개)
LATE_SECONDS = 60


# ---------------------------------------------------------------------------
# KQL (노트북이 trade_date를 넣어 실행). 시각은 모두 UTC로 저장되어 있습니다.
# KST 09:00 = UTC 00:00이라 KST 거래일 d의 정규장은 UTC d 00:00~06:30입니다.
# ---------------------------------------------------------------------------
def kql_queries(trade_date: date) -> dict[str, str]:
    d = trade_date.isoformat()
    return {
        "universe": "universe_assets | distinct asset_id",
        "events": f"""
let s = datetime({d}); let e = s + 6h + 30m;
quote_events
| extend et = todatetime(event_time), rt = todatetime(received_at)
| extend t = coalesce(et, rt)
| where t >= s and t < e and tobool(is_mock) == false
| summarize events = count(), unique_events = count_distinct(tostring(event_id)),
            non_regular = countif(tostring(session) != "regular"),
            date_inferred = countif(tobool(date_inferred) == true),
            no_event_time = countif(isnull(et)),
            late = countif(isnotnull(et) and rt - et > {LATE_SECONDS}s),
            first_event_time = min(et), last_event_time = max(et)
          by asset_id = tostring(asset_id)""",
        "bars": f"""
let s = datetime({d});
bars_1m
| where bar_at >= s and bar_at < s + {CONTINUOUS_MINUTES}m
| project asset_id = tostring(asset_id), bar_at, open, high, low, close, volume, ticks, last_cum, ingested_at""",
        "snapshots": f"""
let s = datetime({d});
market_state_history
| where as_of >= s + 1m and as_of <= s + 6h + 20m
| summarize arg_max(computed_at, snapshot) by as_of
| project as_of, quality_status = tostring(snapshot.quality_status), valid = toint(snapshot.valid_asset_count),
          expected = toint(snapshot.expected_asset_count)""",
    }


# ---------------------------------------------------------------------------
def _utc(d: date, t: time) -> pd.Timestamp:
    return pd.Timestamp(datetime.combine(d, t, KST)).tz_convert("UTC")


def _ranges(missing: list[pd.Timestamp]) -> list[str]:
    """누락 분을 'HH:MM~HH:MM' KST 구간으로 묶습니다."""
    out, start, prev = [], None, None
    for t in missing:
        if start is None:
            start = prev = t
        elif t - prev == pd.Timedelta(minutes=1):
            prev = t
        else:
            out.append((start, prev)); start = prev = t
    if start is not None:
        out.append((start, prev))
    fmt = lambda x: x.tz_convert(KST).strftime("%H:%M")
    return [fmt(a) if a == b else f"{fmt(a)}~{fmt(b)}" for a, b in out]


def _num(x):
    return None if x is None or pd.isna(x) else float(x)


def build_handoff(trade_date: date, universe: list[str], events: pd.DataFrame, bars: pd.DataFrame,
                  snapshots: pd.DataFrame, created_at: datetime) -> dict:
    universe = sorted({str(a) for a in universe})
    expected = pd.date_range(_utc(trade_date, CONTINUOUS_START), periods=CONTINUOUS_MINUTES, freq="1min")

    bars = bars.copy()
    if len(bars):
        bars["bar_at"] = pd.to_datetime(bars["bar_at"], utc=True)
        bars["ingested_at"] = pd.to_datetime(bars["ingested_at"], utc=True)
        revisions = bars.groupby(["asset_id", "bar_at"]).size().sub(1).groupby("asset_id").sum()
        latest = bars.sort_values("ingested_at").groupby(["asset_id", "bar_at"], as_index=False).last()
    else:
        revisions, latest = pd.Series(dtype=int), bars
    ev = events.set_index("asset_id") if len(events) else pd.DataFrame()

    rows = []
    for asset in universe:
        b = latest[latest["asset_id"] == asset].sort_values("bar_at") if len(latest) else latest
        have = set(b["bar_at"]) if len(b) else set()
        missing = [t for t in expected if t not in have]
        e = ev.loc[asset] if asset in ev.index else None
        n_events = int(e["events"]) if e is not None else 0
        dup = int(e["events"] - e["unique_events"]) if e is not None else 0
        first_bar = b.iloc[0] if len(b) else None
        last_bar = b.iloc[-1] if len(b) else None
        observed = len(have)
        if observed == 0:
            status = "missing"
        elif observed == CONTINUOUS_MINUTES:
            status = "complete"
        else:
            status = "partial"
        rows.append({
            "trade_date": trade_date.isoformat(),
            "asset_id": asset,
            "status": status,
            "bars_expected": CONTINUOUS_MINUTES,
            "bars_observed": observed,
            "bars_missing": len(missing),
            "missing_minutes_kst": _ranges(missing),
            "bars_revised": int(revisions.get(asset, 0)),
            "events": n_events,
            "duplicate_events": dup,
            "non_regular_events": int(e["non_regular"]) if e is not None else 0,
            "date_inferred_events": int(e["date_inferred"]) if e is not None else 0,
            "no_event_time_events": int(e["no_event_time"]) if e is not None else 0,
            "late_events": int(e["late"]) if e is not None else 0,
            "late_threshold_seconds": LATE_SECONDS,
            "first_event_time": None if e is None or pd.isna(e["first_event_time"]) else pd.Timestamp(e["first_event_time"]).isoformat(),
            "last_event_time": None if e is None or pd.isna(e["last_event_time"]) else pd.Timestamp(e["last_event_time"]).isoformat(),
            # 분봉 기반 장중 값 (09:00~15:19). 확정 종가·확정 거래량 아님
            "first_bar_at": None if first_bar is None else first_bar["bar_at"].isoformat(),
            "first_bar_open": None if first_bar is None else _num(first_bar["open"]),
            "high": _num(b["high"].max()) if len(b) else None,
            "low": _num(b["low"].min()) if len(b) else None,
            "last_bar_at": None if last_bar is None else last_bar["bar_at"].isoformat(),
            "last_bar_close": None if last_bar is None else _num(last_bar["close"]),
            "continuous_volume": _num(b["volume"].sum()) if len(b) else None,
            "last_cumulative_volume": _num(b["last_cum"].max()) if len(b) else None,
            "price_basis": "raw_unadjusted",
            "is_official_close": False,
        })

    snapshots = snapshots.copy()
    snap_expected = pd.date_range(_utc(trade_date, SNAPSHOT_FIRST), _utc(trade_date, SNAPSHOT_LAST), freq="1min")
    if len(snapshots):
        snapshots["as_of"] = pd.to_datetime(snapshots["as_of"], utc=True)
    saved = set(snapshots["as_of"]) if len(snapshots) else set()
    snap_missing = [t for t in snap_expected if t not in saved]
    quality_counts = snapshots["quality_status"].value_counts().to_dict() if len(snapshots) else {}

    complete_assets = [r["asset_id"] for r in rows if r["status"] == "complete"]
    partial_assets = [r["asset_id"] for r in rows if r["status"] == "partial"]
    missing_assets = [r["asset_id"] for r in rows if r["status"] == "missing"]
    if not len(events) and not len(latest):
        status = "no_market_observations"       # 휴장일이거나 수집이 전혀 없음
    elif len(complete_assets) == len(universe):
        status = "complete"              # 가격 자료 기준. 스냅샷 누락은 market.snapshots_status로 따로 표시
    else:
        status = "partial"
    market = {
        "trade_date": trade_date.isoformat(),
        "snapshots_expected": len(snap_expected),
        "snapshots_saved": len(saved & set(snap_expected)),
        "snapshots_missing_kst": _ranges(snap_missing),
        "snapshots_status": "complete" if not snap_missing else ("missing" if not saved else "partial"),
        "snapshot_quality_counts": {str(k): int(v) for k, v in quality_counts.items()},
        "assets_complete": len(complete_assets),
        "assets_partial": len(partial_assets),
        "assets_missing": len(missing_assets),
        "events_total": int(events["events"].sum()) if len(events) else 0,
        "duplicate_events_total": int((events["events"] - events["unique_events"]).sum()) if len(events) else 0,
        "bars_revised_total": int(sum(r["bars_revised"] for r in rows)),
    }
    batch_id = f"realtime_close_{trade_date:%Y%m%d}_{created_at.astimezone(KST):%H%M%S}"
    return {"batch_id": batch_id, "status": status, "rows": rows, "market": market,
            "requested_assets": universe, "partial_assets": partial_assets, "missing_assets": missing_assets,
            "created_at": created_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")}


# ---------------------------------------------------------------------------
def publish(bronze: str | Path, handoff: dict) -> Path:
    """파일을 먼저 쓰고 manifest를 마지막에 씁니다. 반환: manifest 경로."""
    root = Path(bronze)
    bid = handoff["batch_id"]
    common = {"is_mock": False, "source": "realtime_close", "handoff_version": HANDOFF_VERSION,
              "trade_date": handoff["market"]["trade_date"], "batch_id": bid}
    files = []
    for name, body in (("assets.json", {**common, "rows": handoff["rows"]}),
                       ("market.json", {**common, "market": handoff["market"]})):
        rel = f"realtime/close/{bid}/{name}"
        content = json.dumps(body, ensure_ascii=False, indent=1).encode("utf-8")
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes(content)
        files.append({"file": rel, "sha256": hashlib.sha256(content).hexdigest(),
                      "rows": len(body.get("rows", [])) or 1})
    manifest = {
        "status": handoff["status"],
        **common,
        "created_at": handoff["created_at"],
        "requested_assets": handoff["requested_assets"],
        "partial_assets": handoff["partial_assets"],
        "missing_assets": handoff["missing_assets"],
        "is_official_close": False,
        "price_basis": "raw_unadjusted",
        "files": files,
        "notes": "분봉 기반 장중 값. 확정 종가·거래량은 KRX 일별 원본을 기준으로 하고 이 자료는 대조용입니다.",
    }
    mpath = root / "_runs" / bid / "SUCCESS.json"
    mpath.parent.mkdir(parents=True, exist_ok=True)
    tmp = mpath.with_suffix(".tmp")
    tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(mpath)
    return mpath


# ---------------------------------------------------------------------------
# batch 담당용 읽기 (price_bridge_reference.read_stock_batch와 같은 방식)
# ---------------------------------------------------------------------------
def latest_batch_id(bronze: str | Path, trade_date: date) -> str | None:
    runs = Path(bronze) / "_runs"
    found = sorted(p.parent.name for p in runs.glob(f"realtime_close_{trade_date:%Y%m%d}_*/SUCCESS.json"))
    return found[-1] if found else None


def read_realtime_close(bronze: str | Path, batch_id: str) -> tuple[dict, pd.DataFrame, dict]:
    """manifest에 있고 체크섬이 맞는 파일만 읽습니다. 반환: (manifest, 종목별 DataFrame, market)."""
    root = Path(bronze).resolve()
    if Path(batch_id).name != batch_id or not batch_id.startswith("realtime_close_"):
        raise ValueError("invalid_batch_id")
    manifest = json.loads((root / "_runs" / batch_id / "SUCCESS.json").read_text(encoding="utf-8"))
    if manifest.get("source") != "realtime_close" or manifest.get("is_mock") is not False:
        raise ValueError("not_realtime_close")
    out = {}
    for item in manifest["files"]:
        path = (root / item["file"]).resolve()
        if not path.is_relative_to(root):
            raise ValueError("path_outside_bronze")
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != item["sha256"]:
            raise ValueError("checksum_mismatch")
        out[path.name] = json.loads(content)
    assets = pd.DataFrame(out["assets.json"]["rows"])
    if len(assets):
        assets["asset_id"] = assets["asset_id"].astype(str).str.zfill(6)
    return manifest, assets, out["market.json"]["market"]
