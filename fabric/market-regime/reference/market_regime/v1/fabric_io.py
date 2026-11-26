"""Fabric I/O helpers for the market regime notebooks (lh_whatif as default lakehouse).

Follows the team's Gold conventions:
  Files/gold_evidence/gold_stock_market_daily_v11/health.json   status must be "ready"
  Files/gold_evidence/gold_stock_market_daily_v11/latest.json   {"version", "path"}
  <path>/certificate.json  gold_sha256 / input_eligibility_sha256 checked before use
Regime outputs:
  Files/regime/runs/<run_id>/            context, model, bic, validation json
  Files/regime/snapshots/<version>/      regime_snapshot.json + certificate.json
  Files/regime/latest.json, Files/regime/health.json
"""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

FILES = Path(os.environ.get("REGIME_FILES_ROOT", "/lakehouse/default/Files"))
GOLD_EVIDENCE = FILES / "gold_evidence/gold_stock_market_daily_v11"
REGIME_ROOT = FILES / "regime"


def sha256_file(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json_atomic(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".pending-" + uuid.uuid4().hex)
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str, allow_nan=False), encoding="utf8")
    os.replace(tmp, path)


def read_json(path, default=None):
    path = Path(path)
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf8"))


def now_utc():
    return datetime.now(timezone.utc)


def new_run_id():
    return now_utc().strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6]


def run_dir(run_id) -> Path:
    return REGIME_ROOT / "runs" / run_id


def resolve_run_id(run_id: str | None):
    """Pipeline passes RUN_ID; a manual run reuses the id written by NB_R01."""
    if run_id:
        return run_id
    ptr = read_json(REGIME_ROOT / "runs/current_run.json")
    if not ptr:
        raise RuntimeError("RUN_ID_MISSING: NB_R01을 먼저 실행하세요")
    return ptr["run_id"]


# ------------------------------------------------------------------ Gold input
def load_gold(spark=None, use_certified=True, gold_table="gold_stress_daily", require_ready=True):
    health = read_json(GOLD_EVIDENCE / "health.json", {})
    if require_ready and health.get("status") != "ready":
        raise RuntimeError("GOLD_NOT_READY:" + str(health.get("status")) + ":" + str(health.get("reason", "")))
    if use_certified:
        latest = read_json(GOLD_EVIDENCE / "latest.json")
        if not latest:
            raise RuntimeError("GOLD_LATEST_POINTER_MISSING")
        run = FILES / latest["path"]
        cert = read_json(run / "certificate.json")
        if not cert:
            raise RuntimeError("GOLD_CERTIFICATE_MISSING")
        if sha256_file(run / "gold.parquet") != cert["gold_sha256"]:
            raise RuntimeError("GOLD_SNAPSHOT_HASH_MISMATCH")
        if sha256_file(run / "input_eligibility.parquet") != cert["input_eligibility_sha256"]:
            raise RuntimeError("GOLD_ELIGIBILITY_HASH_MISMATCH")
        gold = pd.read_parquet(run / "gold.parquet")
        elig = pd.read_parquet(run / "input_eligibility.parquet")
        version = {"source": "certified_snapshot", "gold_table": gold_table,
                   "gold_snapshot_version": latest["version"], "gold_sha256": cert["gold_sha256"],
                   "input_eligibility_sha256": cert["input_eligibility_sha256"],
                   "latest_gold_date": cert.get("latest_gold_date"),
                   "latest_eligible_date": cert.get("latest_eligible_date"),
                   "training_ready": cert.get("training_ready"),
                   "dataset_version": str(gold["dataset_version"].dropna().iloc[0]) if "dataset_version" in gold and gold["dataset_version"].notna().any() else None,
                   "gold_health_checked_at_utc": health.get("checked_at_utc")}
        if spark is not None:
            d = spark.table(gold_table).agg({"trading_date": "max"}).first()[0]
            version["delta_latest_date"] = str(d) if d is not None else None
            if version["latest_gold_date"] and version["delta_latest_date"] and version["latest_gold_date"] != version["delta_latest_date"]:
                raise RuntimeError("GOLD_SNAPSHOT_AND_DELTA_DATE_DIFFER")
        return gold, elig, version
    if spark is None:
        raise RuntimeError("SPARK_REQUIRED_FOR_DELTA_READ")
    gold = spark.table(gold_table).toPandas()
    version = {"source": "delta_table", "gold_table": gold_table, "gold_snapshot_version": None,
               "latest_gold_date": str(pd.to_datetime(gold["trading_date"]).max().date()),
               "dataset_version": str(gold["dataset_version"].dropna().iloc[0]) if gold["dataset_version"].notna().any() else None,
               "note": "인증 스냅샷 대신 Delta 테이블을 읽었습니다. quality_status='valid' 행만 사용합니다."}
    return gold, None, version


# ------------------------------------------------------------------ Delta tables
def _spark_ready(pdf: pd.DataFrame) -> pd.DataFrame:
    out = pdf.copy()
    if out.index.name is not None and out.index.name not in out.columns:
        out = out.reset_index()
    for c in out.columns:
        if pd.api.types.is_datetime64_any_dtype(out[c]):
            v = out[c].dropna()
            if len(v) == 0 or (v == v.dt.normalize()).all():
                out[c] = out[c].dt.date            # pure dates → DateType
            else:
                out[c] = out[c].dt.tz_localize(None) if getattr(out[c].dt, "tz", None) is not None else out[c]  # → TimestampType (UTC)
        elif out[c].dtype == object and out[c].isna().all():
            out[c] = out[c].astype("string").fillna("")
        elif pd.api.types.is_bool_dtype(out[c]):
            out[c] = out[c].astype(bool)
    return out


def save_table(spark, pdf: pd.DataFrame, name: str, mode="overwrite"):
    sdf = spark.createDataFrame(_spark_ready(pdf))
    (sdf.write.format("delta").mode(mode).option("overwriteSchema", "true").saveAsTable(name))
    return spark.table(name).count()


def load_table(spark, name: str, index_col=None) -> pd.DataFrame:
    pdf = spark.table(name).toPandas()
    for c in pdf.columns:
        if c in ("trading_date", "start", "end", "similar_date", "asof"):
            pdf[c] = pd.to_datetime(pdf[c])
    if index_col:
        pdf = pdf.set_index(index_col).sort_index()
        pdf.index.name = index_col
    return pdf
