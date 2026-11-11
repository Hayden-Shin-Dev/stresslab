"""원본 B152, 잘못 이식한 PR12, 복원한 코드의 동일 날짜 비교."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
import pandas as pd
from .model import FACTORS, STATE, fit, predict
from .training import mature_training
from .universe import NAMES
from .run import save


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def compare(original, wrong, aligned, output):
    original, wrong, aligned, output = map(Path, [original, wrong, aligned, output])
    output.mkdir(parents=True, exist_ok=False)
    features = pd.read_parquet(aligned / "features.parquet")
    original_models = [m for m in json.loads((original/"models.json").read_text(encoding="utf-8")) if m["arm"] == "symmetric_huber"]
    old = pd.read_parquet(original/"forecasts.parquet", filters=[("arm", "==", "symmetric_huber")])
    for c in ["origin", "target_end"]:
        old[c] = pd.to_datetime(old[c]).astype("datetime64[ns]")
    groups = {key: g for key, g in features.groupby(["asset_id", "horizon"])}
    old_groups = {key: g for key, g in old.groupby("model_id")}
    audit, outputs = [], []
    for i, m in enumerate(original_models):
        group = groups[(m["asset_id"], m["horizon"])]
        train = mature_training(group, m["fit_origin"])
        digest = hashlib.sha256("|".join(train.origin.dt.strftime("%Y-%m-%d")).encode()).hexdigest()
        if len(train) != m["training_n"] or digest != m["training_origins_sha256"]:
            raise ValueError(f"원본 학습 표본 불일치: {m['model_id']}")
        fitted = fit(train)
        coef_error = float(np.max(abs(np.array(fitted["coef"])-np.array(m["coef"]))))
        np.testing.assert_allclose(fitted["coef"], m["coef"], rtol=0, atol=1e-9)
        expected = old_groups[m["model_id"]].sort_values("origin")
        actual = group.set_index("origin").loc[expected.origin].reset_index()
        for c in STATE+FACTORS+["scale"]:
            np.testing.assert_allclose(actual[c], expected[c], rtol=0, atol=1e-10)
        np.testing.assert_allclose(actual.target, expected.actual, rtol=0, atol=1e-10)
        calculated = predict(actual, fitted)
        error = float(np.max(abs(calculated["central_return"]-expected.central_return.to_numpy())))
        np.testing.assert_allclose(calculated["central_return"], expected.central_return, rtol=0, atol=1e-9)
        audit.append({"asset_id": m["asset_id"], "horizon": m["horizon"], "fit_origin": m["fit_origin"],
                      "training_n": len(train), "training_origins_sha256": digest, "coefficient_max_difference": coef_error,
                      "prediction_max_difference_pp": error})
        r = expected[["asset_id", "horizon", "origin", "target_end", "actual", "large", "scale", "central_return"]].copy()
        r = r.rename(columns={"central_return": "original_return"})
        r["refit_return"] = calculated["central_return"]
        outputs.append(r)
        if i % 200 == 0:
            print(f"원본 학습 표본/계수/출력 확인 {i+1}/{len(original_models)}", flush=True)
    pd.DataFrame(audit).to_csv(output/"model_reproduction.csv", index=False)
    reproduced = pd.concat(outputs, ignore_index=True)
    fixed = pd.read_parquet(aligned/"backtest.parquet")
    broken = pd.read_parquet(wrong/"backtest.parquet")
    keys = ["asset_id", "horizon", "origin"]
    verified = reproduced.merge(fixed[keys+["central_return"]], on=keys, validate="one_to_one", how="left")
    if verified.central_return.isna().any():
        raise ValueError("복원 파이프라인에서 원래 평가 날짜가 빠짐")
    np.testing.assert_allclose(verified.original_return, verified.central_return, rtol=0, atol=1e-9)
    common = verified.rename(columns={"central_return": "aligned_return"}).merge(
        broken[keys+["central_return"]].rename(columns={"central_return": "pr12_return"}), on=keys, validate="one_to_one")
    rows, intervals = [], []
    # 민철 2026-11-11 추가 (평가 날짜와 잔차 표본 차이로 비교가 달라지지 않도록 공통 날짜와 동일한 과거 보정 표본을 사용했음.)
    for (asset, horizon), g in common.groupby(["asset_id", "horizon"]):
        g = g.sort_values("origin").copy()
        g["quarter"] = g.origin.dt.to_period("Q")
        for arm in ["original", "pr12", "aligned"]:
            error = 100*np.log1p(g.actual/100)/g.scale - 100*np.log1p(g[arm+"_return"]/100)/g.scale
            g[arm+"_q05"] = np.nan
            g[arm+"_q95"] = np.nan
            for quarter, batch in g.groupby("quarter", sort=True):
                cutoff = quarter.start_time
                sample = error[g.target_end < cutoff].tail(756)
                if len(sample) < 100:
                    continue
                for q in [.05, .95]:
                    col = arm+f"_q{int(q*100):02}"
                    g.loc[batch.index, col] = 100*np.expm1(np.log1p(batch[arm+"_return"]/100)+np.quantile(sample,q)*batch.scale/100)
        intervals.append(g)
        for scope, mask in [("all_2017_onward", g.origin >= "2017-01-01"),
                            ("all_2025_onward", g.origin >= "2025-01-01"),
                            ("large_2017_onward", (g.origin >= "2017-01-01") & g.large),
                            ("large_2025_onward", (g.origin >= "2025-01-01") & g.large)]:
            part = g[mask].dropna(subset=[a+"_q05" for a in ["original", "pr12", "aligned"]])
            if part.empty:
                continue
            row = {"asset_id": asset, "name": NAMES[asset], "horizon": int(horizon), "scope": scope,
                   "n": len(part), "first": str(part.origin.min().date()), "last": str(part.origin.max().date()),
                   "zero_mae_pp": float(abs(part.actual).mean())}
            for arm in ["original", "pr12", "aligned"]:
                predicted = part[arm+"_return"]
                nonzero = part.actual.ne(0)
                row.update({arm+"_mae_pp": float(abs(predicted-part.actual).mean()),
                            arm+"_direction": float((np.sign(predicted[nonzero])==np.sign(part.actual[nonzero])).mean()),
                            arm+"_coverage90": float(part.actual.between(part[arm+"_q05"],part[arm+"_q95"]).mean()),
                            arm+"_width90_pp": float((part[arm+"_q95"]-part[arm+"_q05"]).mean())})
            rows.append(row)
    perf = pd.DataFrame(rows)
    perf.to_csv(output/"per_stock_comparison.csv", index=False)
    numeric = [c for c in perf if c.endswith(("_mae_pp", "_direction", "_coverage90", "_width90_pp"))]
    agg = perf.groupby(["scope", "horizon"])[numeric].mean().reset_index()
    agg.to_csv(output/"aggregate.csv", index=False)
    pd.concat(intervals, ignore_index=True).to_parquet(output/"paired_forecasts.parquet", index=False)
    summary = {"status": "passed", "original_models_refitted": len(audit),
               "training_sample_hashes_equal": True, "reference_forecasts_reproduced": len(reproduced),
               "max_coefficient_difference": max(r["coefficient_max_difference"] for r in audit),
               "max_prediction_difference_pp": max(r["prediction_max_difference_pp"] for r in audit),
               "pipeline_vs_original_max_difference_pp": float(abs(verified.original_return-verified.aligned_return).max()),
               "common_forecasts_all_arms": len(common), "assets": int(perf.asset_id.nunique()),
               "interval_rule": "same common historical dates; quarterly cutoff; matured past 756 errors, min100",
               "original_huber_had_interval_output": False,
               "interval_note": "original intervals newly calculated with the shared rule; not archived original service intervals",
               "comparison_note": "PR12 used publication-update shocks, so this is migration error correction, not a fixed-task algorithm improvement",
               "cloud_writes": False, "original_models_sha256": sha(original/"models.json")}
    save(output/"summary.json", summary)
    print(json.dumps(summary), flush=True)
    print(agg.to_json(orient="records"), flush=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    for key in ["original", "wrong", "aligned", "output"]:
        p.add_argument("--"+key, required=True)
    a = p.parse_args()
    compare(a.original, a.wrong, a.aligned, a.output)
