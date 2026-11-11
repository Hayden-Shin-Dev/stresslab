"""로컬 실행 진입점. Fabric 노트북도 같은 함수에 Gold DataFrame을 전달할 수 있다."""
from __future__ import annotations
import argparse
import hashlib
import json
import platform
from pathlib import Path
import numpy as np
import pandas as pd
from .features import audit, build
from .training import train_and_backtest, metrics
from .result import scenario


def save(path, obj):
    Path(path).write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def run(snapshot, output):
    snapshot, output = Path(snapshot), Path(output)
    output.mkdir(parents=True, exist_ok=False)
    receipt = json.loads((snapshot / "receipt.json").read_text(encoding="utf-8"))
    for name, key in [("gold.parquet", "gold_sha256"), ("provenance.parquet", "provenance_sha256")]:
        if hashlib.sha256((snapshot/name).read_bytes()).hexdigest() != receipt[key]:
            raise ValueError("스냅샷 해시 불일치")
    gold = pd.read_parquet(snapshot / "gold.parquet")
    provenance = pd.read_parquet(snapshot / "provenance.parquet")
    checked, eligible, _, summary = audit(gold, provenance)
    published = pd.read_parquet(snapshot / "input_eligibility.parquet")
    published["trading_date"] = pd.to_datetime(published.trading_date).astype("datetime64[ns]")
    actual = checked[["trading_date", "asset_id"]].assign(input_eligible=eligible)
    matched = actual.merge(published, on=["trading_date", "asset_id"], suffixes=("_local", "_fabric"), validate="one_to_one", how="outer")
    if len(matched) != len(actual) or not matched.input_eligible_local.eq(matched.input_eligible_fabric).all():
        raise ValueError("Fabric와 로컬의 입력 가능 행 불일치")
    summary["fabric_eligibility_equal"] = True
    save(output / "input_audit.json", summary)
    save(output / "source_receipt.json", receipt)
    save(output / "protocol.json", {"model": "B152 symmetric_huber", "training_window": 2520,
         "minimum_training_rows": 252, "refit": "quarterly", "calibration": "past out-of-sample residuals, last 756, minimum 100",
         "evaluation_periods": ["2017-2024", "2025 onward"], "evaluation_kind": "re-evaluation, not an untouched final holdout",
         "shock_definition": "next Korean trading session change in Gold as-of macro state",
         "strict_historical_point_in_time_verified": False,
         "price_clock_basis": "end-of-session research assumption; exact release and vintage not certified",
         "python": platform.python_version(), "numpy": np.__version__, "pandas": pd.__version__})
    features, _ = build(gold, provenance)
    features.to_parquet(output / "features.parquet", index=False)
    forecasts, packages = train_and_backtest(features)
    forecasts.to_parquet(output / "backtest.parquet", index=False)
    save(output / "models.json", packages)
    scores = metrics(forecasts)
    save(output / "metrics.json", scores)
    pd.DataFrame(scores).to_csv(output / "metrics.csv", index=False)
    examples = []
    ids = sorted(gold.asset_id.unique().tolist())
    for horizon in [1, 5]:
        for name, shocks in [("zero", [0, 0, 0, 0]), ("fx_up2", [2, 0, 0, 0]),
                             ("rate_up25", [0, 25, 0, 0]), ("oil_up10", [0, 0, 10, 0]),
                             ("vix_up5", [0, 0, 0, 5]), ("combined", [2, 25, 10, 5])]:
            request = {"run_id": f"local-{receipt['delta_version']}-{name}-{horizon}", "horizon_trading_days": horizon,
                       "asset_ids": ids, "shocks": dict(zip(["shock_fx", "shock_rate", "shock_oil", "shock_vix"], shocks)),
                       "holdings_krw": {asset: 1000000 for asset in ids}}
            examples.append(scenario(features, packages, forecasts, gold, request))
    save(output / "scenario_examples.json", examples)
    save(output / "completion.json", {"models": len(packages), "backtest_rows": len(forecasts),
         "scenario_runs": len(examples), "scenario_asset_outputs": sum(len(r["assets"]) for r in examples),
         "cloud_modified": False, "production_approved": False})
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--output", required=True)
    a = parser.parse_args()
    print(run(a.snapshot, a.output))
