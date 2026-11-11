"""원본 평가 날짜, 충격 분류, 중심값, 구간과 집계 수치를 고정하여 검증한다."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
import pandas as pd
from .intervals import (CONTRACT, KEYS, REFERENCE_FORECAST_SHA256,
                        REFERENCE_KEYS_SHA256, load_reference)
from .universe import NAMES


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify(output, reference_inputs, reference_forecasts, report):
    output, reference_forecasts, report = map(Path, [output, reference_forecasts, report])
    report.mkdir(parents=True, exist_ok=False)
    inputs = load_reference(reference_inputs)
    if digest(reference_forecasts) != REFERENCE_FORECAST_SHA256:
        raise ValueError("고정한 원본 비교 예측 파일의 해시가 다름")
    old = pd.read_parquet(reference_forecasts, filters=[("arm", "==", "B152")])
    keys = old.sort_values(KEYS)
    serial = "\n".join(f"{r.asset_id}|{r.horizon}|{r.origin:%Y-%m-%d}" for r in keys.itertuples())
    if hashlib.sha256(serial.encode()).hexdigest() != REFERENCE_KEYS_SHA256:
        raise ValueError("원본 평가 날짜가 달라짐")
    new = pd.read_parquet(output/"backtest.parquet")
    if not new.interval_contract.eq(CONTRACT).all():
        raise ValueError("원본 구간 계약으로 계산되지 않음")
    # 민철 2026-11-11 수정 (기간과 표본이 달라져 폭 비교가 달라졌기 때문에 원본 평가 키 전체를 기준으로 고정함.)
    paired = old.merge(new, on=KEYS, how="left", suffixes=("_old", "_new"), validate="one_to_one", indicator=True)
    if len(paired) != 132394 or not paired._merge.eq("both").all():
        raise ValueError("원본 평가 날짜가 누락됨")
    checks = {}
    for label, left, right in [("center", "point", "central_return"), ("lower90", "lo", "q05"),
                                ("upper90", "hi", "q95"), ("target", "actual", "target"),
                                ("scale", "scale_old", "scale_new")]:
        np.testing.assert_allclose(paired[left], paired[right], rtol=0, atol=1e-10)
        checks[label+"_max_difference_pp"] = float(abs(paired[left]-paired[right]).max())
    for left, right in [("target_end_old", "target_end_new"), ("fit_origin_old", "fit_origin_new"),
                        ("calibration_n_old", "calibration_n_new"), ("factor_policy_available_at", "factor_known_by")]:
        np.testing.assert_array_equal(paired[left], paired[right])
    factors = ["fx_pct", "us_rate_bp", "oil_usd", "vix_points"]
    for factor in factors:
        np.testing.assert_allclose(paired[factor+"_old"], paired[factor+"_new"], rtol=0, atol=1e-10)
    large = np.logical_or.reduce([abs(paired[f+"_new"]) >= threshold for f, threshold in
                                 zip(factors, [100*np.log1p(.01), 25, 5, 5])])
    np.testing.assert_array_equal(large, paired.large)
    data = paired.merge(inputs[KEYS], on=KEYS, validate="one_to_one")
    rows = []
    for (asset, horizon), g in data.groupby(["asset_id", "horizon"]):
        for period, period_mask in [("development", g.origin < "2017-01-01"),
                                    ("evaluation", g.origin >= "2017-01-01"),
                                    ("recent", g.origin >= "2022-01-01")]:
            for event, event_mask in [("all", np.ones(len(g), bool)), ("large", g.large)]:
                z = g[period_mask & event_mask]
                if z.empty:
                    continue
                row = dict(asset_id=asset, name=NAMES[asset], horizon=int(horizon), period=period, event=event,
                           n=len(z), first=str(z.origin.min().date()), last=str(z.origin.max().date()))
                for name, center, lower, upper in [("original", "point", "lo", "hi"),
                                                   ("restored", "central_return", "q05", "q95")]:
                    nonzero = z.actual.ne(0)
                    row.update({name+"_mae_pp": float(abs(z[center]-z.actual).mean()),
                                name+"_width90_pp": float((z[upper]-z[lower]).mean()),
                                name+"_coverage90": float(z.actual.between(z[lower], z[upper]).mean()),
                                name+"_direction": float((np.sign(z[center][nonzero])==np.sign(z.actual[nonzero])).mean())})
                rows.append(row)
    scores = pd.DataFrame(rows)
    fields = [c for c in scores if c.startswith(("original_", "restored_"))]
    aggregate = scores.groupby(["horizon", "period", "event"])[fields].mean().reset_index()
    for metric in ["mae_pp", "width90_pp", "coverage90", "direction"]:
        np.testing.assert_allclose(scores["original_"+metric], scores["restored_"+metric], rtol=0, atol=1e-10)
    scores.to_csv(report/"per_stock_comparison.csv", index=False)
    aggregate.to_csv(report/"aggregate.csv", index=False)
    evidence = dict(status="passed", interval_contract=CONTRACT, original_rows=132394, stocks=20,
                    reference_keys_sha256=REFERENCE_KEYS_SHA256,
                    reference_inputs_sha256=digest(reference_inputs), reference_forecasts_sha256=digest(reference_forecasts),
                    restored_forecasts_sha256=digest(output/"backtest.parquet"),
                    identical_calibration_sample_counts=True, identical_fit_dates=True, identical_large_shock_labels=True,
                    additional_live_rows_excluded_from_frozen_benchmark=len(new)-len(paired),
                    archived_cold_start_rows=int((paired.calibration_n_old<60).sum()),
                    all_per_stock_metrics_equal=True, cloud_modified=False, **checks)
    (report/"verification.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(evidence))
    print(aggregate[aggregate.period.eq("evaluation")].to_json(orient="records"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for flag in ["output", "reference-inputs", "reference-forecasts", "report"]:
        parser.add_argument("--"+flag, required=True)
    args = parser.parse_args()
    verify(args.output, args.reference_inputs, args.reference_forecasts, args.report)
