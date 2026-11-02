"""Adjusted-price connection reference: read Bronze, validate, return candidates only.

No network, credential access, table writes, or automatic adjustment factors.
Use in a Fabric notebook after mounting lh_whatif as the default Lakehouse.
"""
import hashlib
import json
import math
from pathlib import Path

import pandas as pd


def number(value):
    result = float(str(value).replace(",", ""))
    if not math.isfinite(result):
        raise ValueError("non_finite")
    return result


def read_history(bronze):
    """Read the current unpacked KRX history; keep the six-digit asset code."""
    records = []
    for path in sorted((Path(bronze) / "krx/history/stocks").glob("*.json")):
        for row in json.loads(path.read_text(encoding="utf-8")):
            records.append({"asset_id": path.stem,
                            "date": row["TRD_DD"].replace("/", "-"),
                            "close": number(row["TDD_CLSPRC"]),
                            "volume": number(row["ACC_TRDVOL"])})
    if not records:
        raise ValueError("history_missing")
    return pd.DataFrame(records).sort_values(["asset_id", "date"])


def read_stock_batch(bronze, batch_id):
    """Only read manifest-listed, checksum-verified KRX stock responses."""
    root = Path(bronze).resolve()
    if Path(batch_id).name != batch_id or batch_id in (".", ".."):
        raise ValueError("invalid_batch_id")
    manifest = json.loads((root / "_runs" / batch_id / "SUCCESS.json").read_text(encoding="utf-8"))
    if manifest["status"] not in ("complete", "no_market_observations"):
        raise ValueError("batch_not_complete")
    assets = set(manifest["requested_assets"])
    rows, market_days = [], set()
    for item in manifest["files"]:
        relative = item["file"].replace("\\", "/")
        path = (root / relative).resolve()
        if not path.is_relative_to(root):
            raise ValueError("path_outside_bronze")
        if not relative.startswith("krx/api/") or "/stocks/" not in relative:
            continue
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != item["sha256"]:
            raise ValueError("checksum_mismatch")
        envelope = json.loads(content)
        if envelope.get("is_mock") is not False:
            raise ValueError("mock_or_unknown_source")
        for row in envelope["rows"]:
            day = pd.Timestamp(row["BAS_DD"]).strftime("%Y-%m-%d")
            market_days.add(day)
            if row["ISU_CD"] in assets:
                rows.append(row)
    return manifest, rows, sorted(market_days)


def validate_connection(history, rows, assets, market_days, *, raw_comparable_from):
    """Return report and new rows. If blocked, return no publishable rows.

    raw_comparable_from is the verified date from which adjusted and raw prices
    share a basis. For the existing history it is 2026-10-16. Do not advance it
    to hide a newly detected corporate action; revalidate official history first.
    history must contain the latest accepted Silver prices on subsequent runs.
    """
    history = history.copy()
    history["date"] = pd.to_datetime(history["date"]).dt.strftime("%Y-%m-%d")
    if history.duplicated(["asset_id", "date"]).any():
        raise ValueError("duplicate_history")
    errors, additions = [], []
    for asset in sorted(assets):
        old = history[history.asset_id == asset].sort_values("date")
        current = sorted([r for r in rows if r["ISU_CD"] == asset], key=lambda r: r["BAS_DD"])
        if old.empty:
            errors.append({"asset_id": asset, "reason": "missing_history"})
            continue
        last = old.iloc[-1]["date"]
        previous = number(old.iloc[-1]["close"])
        observed = {pd.Timestamp(r["BAS_DD"]).strftime("%Y-%m-%d") for r in current}
        missing = sorted(set(market_days) - observed)
        if missing:
            errors.append({"asset_id": asset, "reason": "missing_market_dates", "dates": missing})
        if any(d > last for d in market_days) and last not in observed:
            errors.append({"asset_id": asset, "reason": "boundary_overlap_required"})
            continue
        seen = set()
        for row in current:
            day = pd.Timestamp(row["BAS_DD"]).strftime("%Y-%m-%d")
            issue = {"asset_id": asset, "date": day}
            if day in seen:
                errors.append({**issue, "reason": "duplicate"})
                continue
            seen.add(day)
            try:
                close = number(row["TDD_CLSPRC"])
                change = number(row["CMPPREVDD_PRC"])
                rate = number(row["FLUC_RT"])
                volume = number(row["ACC_TRDVOL"])
                if close <= 0 or volume < 0:
                    raise ValueError("invalid_price_or_volume")
            except (ValueError, KeyError, TypeError):
                errors.append({**issue, "reason": "invalid_numeric"})
                continue
            if day <= last:
                if day >= raw_comparable_from:
                    match = old[old.date == day]
                    if match.empty or number(match.iloc[0]["close"]) != close:
                        errors.append({**issue, "reason": "overlap_revision_or_action"})
                continue
            reference = close - change
            if abs(reference - previous) > 0.51:
                errors.append({**issue, "reason": "official_adjustment_required",
                               "previous_close": previous, "official_reference": reference})
                continue
            if abs((close / previous - 1) * 100 - rate) > 0.011:
                errors.append({**issue, "reason": "return_mismatch"})
                continue
            additions.append({**issue, "close": close, "volume": volume,
                              "reported_return_pct": rate, "source": "KRX_API"})
            previous = close
    report = {"status": "blocked" if errors else "passed", "errors": errors,
              "new_rows": 0 if errors else len(additions), "assets": len(assets)}
    return report, pd.DataFrame([] if errors else additions)
