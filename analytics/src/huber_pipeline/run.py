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
from .shocks import load_legacy_observations
from .intervals import CONTRACT, load_reference


def save(path, obj):
    Path(path).write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def run(snapshot, output, observations, reference_inputs):
    snapshot, output = Path(snapshot), Path(output)
    output.mkdir(parents=True, exist_ok=False)
    receipt = json.loads((snapshot / "receipt.json").read_text(encoding="utf-8"))
    for name, key in [("gold.parquet", "gold_sha256"), ("provenance.parquet", "provenance_sha256")]:
        if hashlib.sha256((snapshot/name).read_bytes()).hexdigest() != receipt[key]:
            raise ValueError("스냅샷 해시 불일치")
    certificate = json.loads((snapshot / "certificate.json").read_text(encoding="utf-8"))
    if hashlib.sha256((snapshot / "input_eligibility.parquet").read_bytes()).hexdigest() != certificate["input_eligibility_sha256"]:
        raise ValueError("입력 적합성 표 해시 불일치")
    gold = pd.read_parquet(snapshot / "gold.parquet")
    provenance = pd.read_parquet(snapshot / "provenance.parquet")
    observation_data = load_legacy_observations(observations)
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
         "minimum_training_rows": 252, "refit": "quarterly", "calibration": "absolute arithmetic error / scale, last252, min60, finite-sample rank90", "interval_contract": CONTRACT,
         "evaluation_periods": ["development <2017", "evaluation >=2017", "recent >=2022"],
         "primary_evaluation_keys": "original 132394 frozen keys; verify_interval_contract required",
         "reference_inputs_sha256": hashlib.sha256(Path(reference_inputs).read_bytes()).hexdigest(), "evaluation_kind": "re-evaluation, not an untouched final holdout",
         "shock_definition": "B152 next-session change in observation-date-aligned original series; hypothetical/ex-post scenario",
         "factor_observations_sha256": hashlib.sha256(Path(observations).read_bytes()).hexdigest(),
         "training_cutoff": "08:30 Asia/Seoul, strict less-than; legacy research proxy",
         "strict_historical_point_in_time_verified": False,
         "price_clock_basis": "end-of-session research assumption; exact release and vintage not certified",
         "python": platform.python_version(), "numpy": np.__version__, "pandas": pd.__version__})
    features, _ = build(gold, provenance, observation_data)
    features.to_parquet(output / "features.parquet", index=False)
    forecasts, packages = train_and_backtest(features, load_reference(reference_inputs))
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
    parser.add_argument("--observations", required=True)
    parser.add_argument("--reference-inputs", required=True)
    a = parser.parse_args()
    print(run(a.snapshot, a.output, a.observations, a.reference_inputs))
