"""저장 모델로 예시를 재생성하고 실제 AI 근거 조립 코드에 전달한다."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import numpy as np
import pandas as pd
from .result import scenario
from .run import save


def verify(output, snapshot, evidence_file):
    output, snapshot, evidence_file = Path(output), Path(snapshot), Path(evidence_file)
    spec = importlib.util.spec_from_file_location("checked_debate_evidence", evidence_file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    features = pd.read_parquet(output / "features.parquet")
    history = pd.read_parquet(output / "backtest.parquet")
    packages = json.loads((output / "models.json").read_text(encoding="utf-8"))
    gold = pd.read_parquet(snapshot / "gold.parquet")
    previous = json.loads((output / "scenario_examples.json").read_text(encoding="utf-8"))
    examples, evidence_counts = [], []
    max_change = 0.
    for old in previous:
        request = {"run_id": old["run_id"], "horizon_trading_days": old["horizon_trading_days"],
                   "asset_ids": [a["asset"] for a in old["assets"]], "shocks": old["shocks"],
                   "holdings_krw": {a["asset"]: a["holding_value_krw"] for a in old["assets"]}}
        result = scenario(features, packages, history, gold, request)
        for a, before in zip(result["assets"], old["assets"]):
            center = a["conditional_center_return_pct"]
            max_change = max(max_change, abs(center-before["conditional_center_return_pct"]))
            assert np.isclose(a["zero_shock_center_pct"]+a["scenario_difference_pp"], center, atol=1e-10)
            assert np.isclose(sum(a["model_contributions_pp"].values()), a["scenario_difference_pp"], atol=1e-10)
            assert a["model_q05_pct"] <= a["model_q10_pct"] <= a["model_q90_pct"] <= a["model_q95_pct"]
            assert np.isclose(a["center_pnl_krw"], a["holding_value_krw"]*center/100)
            for h in a["historical_examples"]:
                assert h["end"] < result["state_date"]
        assert np.isclose(result["portfolio"]["center_pnl_krw"], sum(a["center_pnl_krw"] for a in result["assets"]))
        bundle = module.build_bundle("local-format-check", result, None)
        centers = [d for d in bundle["D_sources"] if d["metric_id"] == "conditional_center_return"]
        assert len(centers) == 20
        mapped = {d["asset_id"]: d["value"] for d in centers}
        assert all(mapped[a["asset"]] == a["conditional_center_return_pct"] for a in result["assets"])
        oil = next(d for d in bundle["D_sources"] if d["metric_id"] == "scenario_shock_wti")
        assert oil["unit"] == "%" and oil["value"] == result["shocks"]["shock_oil"]
        evidence_counts.append(len(bundle["D_sources"]))
        examples.append(result)
    assert max_change == 0
    save(output / "scenario_examples.json", examples)
    result = {"status": "passed", "runs": len(examples), "asset_outputs": 240,
              "unchanged_center_max_difference_pp": max_change,
              "debate_reader_sha256": hashlib.sha256(evidence_file.read_bytes()).hexdigest(),
              "evidence_items_per_run": evidence_counts, "llm_called": False,
              "cloud_deployed": False, "portfolio_model_trained": False}
    save(output / "output_verification.json", result)
    print(json.dumps(result))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    for key in ["output", "snapshot", "evidence-file"]:
        p.add_argument("--"+key, required=True)
    a = p.parse_args()
    verify(a.output, a.snapshot, a.evidence_file)
