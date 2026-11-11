"""종목/기간별 분기 재학습과 과거 예측오차만 사용하는 구간 계산."""
from __future__ import annotations
import hashlib
import numpy as np
import pandas as pd
from .model import STATE, FACTORS, fit, predict
from .intervals import CONTRACT, residual_bank, calibrate, load_reference

QUANTILES = [.05, .10, .90, .95]


def mature_training(frame, as_of):
    as_of = pd.Timestamp(as_of)
    if "factor_contract" not in frame or not frame.factor_contract.eq("b152_observation_scenario_v1").all():
        raise ValueError("B152 원 관측 충격 계약이 없는 학습 입력")
    # 민철 2026-11-11 수정 (원본과 학습 가능 시간이 달랐기 때문에 오후 3시 30분에서 오전 8시 30분 미만 조건으로 복원함.)
    cutoff = as_of.tz_localize("Asia/Seoul").tz_convert("UTC") + pd.Timedelta(hours=8, minutes=30)
    return frame[frame.training_eligible & frame.state_valid & (frame.target_end < as_of)
                 & (frame.shock_end < as_of) & (frame.factor_known_by < cutoff)
                 & np.isfinite(frame[FACTORS + ["target"]]).all(axis=1)].sort_values("origin").tail(2520)


def attach_metadata(model, train, asset, horizon, as_of):
    model.update(asset_id=asset, horizon=int(horizon), fit_origin=str(pd.Timestamp(as_of).date()),
                 factor_contract="b152_observation_scenario_v1",
                 training_n=len(train), training_max_target_end=str(train.target_end.max().date()),
                 training_max_factor_known_by=str(train.factor_known_by.max()),
                 training_origins_sha256=hashlib.sha256("|".join(train.origin.dt.strftime("%Y-%m-%d")).encode()).hexdigest())
    return model


def train_and_backtest(features, reference):
    # 민철 2026-11-11 추가 (미래 정답이나 검증 오차가 학습에 들어가지 않도록 분기 시작 이전에 확정된 행만 사용했음.)
    all_predictions, packages = [], []
    for (asset, horizon), group in features.groupby(["asset_id", "horizon"], sort=True):
        group = group.sort_values("origin").copy()
        group["quarter"] = group.origin.dt.to_period("Q")
        candidate = group[group.state_valid & group.training_eligible
                          & np.isfinite(group[FACTORS]).all(axis=1)]
        observed = candidate[candidate.target.notna()]
        predictions = []
        for quarter, batch in observed.groupby("quarter", sort=True):
            if str(quarter) < "2011Q1":
                continue
            origin = candidate[candidate.quarter.eq(quarter)].origin.min()
            train = mature_training(group, origin)
            if len(train) < 252:
                continue
            model = fit(train)
            out = predict(batch, model)
            r = batch.copy()
            for key, value in out.items():
                r[key] = value
            r["fit_origin"] = origin
            predictions.append(r)
        history = pd.concat(predictions, ignore_index=True) if predictions else pd.DataFrame()
        if not history.empty:
            all_predictions.append(history)
        latest = group[group.state_valid].origin.max()
        if pd.isna(latest):
            continue
        train = mature_training(group, latest)
        if len(train) < 252:
            continue
        model = attach_metadata(fit(train), train, asset, horizon, latest)
        packages.append({"model": model, "as_of": str(latest.date())})
        print(f"{asset} D+{horizon}: train={len(train)} backtest={len(history)}", flush=True)
    return calibrate(pd.concat(all_predictions, ignore_index=True), packages, reference)


def metrics(predictions):
    rows = []
    for (asset, horizon), g in predictions.groupby(["asset_id", "horizon"]):
        for label, mask in [("2017_2024", g.origin.between("2017-01-01", "2024-12-31")),
                            ("2025_onward", g.origin >= "2025-01-01")]:
            x = g[mask]
            if x.empty:
                continue
            calibrated = x.dropna(subset=["q05", "q95"])
            rows.append({"asset_id": asset, "horizon": int(horizon), "period": label, "n": len(x),
                         "mae_pp": float(abs(x.central_return-x.target).mean()),
                         "zero_mae_pp": float(abs(x.target).mean()),
                         "no_shock_mae_pp": float(abs(x.baseline_return-x.target).mean()),
                         "direction_accuracy": float((np.sign(x.central_return)==np.sign(x.target)).mean()),
                         "interval_n": len(calibrated),
                         "coverage90": float(calibrated.target.between(calibrated.q05, calibrated.q95).mean()) if len(calibrated) else None,
                         "width90_pp": float((calibrated.q95-calibrated.q05).mean()) if len(calibrated) else None})
    return rows


if __name__ == "__main__":
    import argparse
    import json
    import shutil
    from pathlib import Path
    parser = argparse.ArgumentParser()
    parser.add_argument("--recalibrate-from", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--reference-inputs", required=True)
    args = parser.parse_args()
    source, output = Path(args.recalibrate_from), Path(args.output)
    shutil.copytree(source, output)
    before = pd.read_parquet(source/"backtest.parquet")
    models = json.loads((source/"models.json").read_text(encoding="utf-8"))
    history, models = calibrate(before, models, load_reference(args.reference_inputs))
    np.testing.assert_array_equal(before.central_return, history.central_return)
    history.to_parquet(output/"backtest.parquet", index=False)
    (output/"models.json").write_bytes(json.dumps(models, ensure_ascii=False, indent=2, allow_nan=False).encode())
    scores = metrics(history)
    (output/"metrics.json").write_bytes(json.dumps(scores, indent=2, allow_nan=False).encode())
    pd.DataFrame(scores).to_csv(output/"metrics.csv", index=False)
    receipt = {"source_models_sha256": hashlib.sha256((source/"models.json").read_bytes()).hexdigest(),
               "models_sha256": hashlib.sha256((output/"models.json").read_bytes()).hexdigest(),
               "central_return_change": 0., "refitted": False, "purpose": "restore archived B152 interval rule", "interval_contract": CONTRACT}
    (output/"calibration_replay.json").write_bytes(json.dumps(receipt, indent=2).encode())
    protocol = json.loads((output/"protocol.json").read_text(encoding="utf-8"))
    protocol.update(interval_contract=CONTRACT, calibration="absolute arithmetic error / scale, last252, min60, finite-sample rank90",
                    primary_evaluation="frozen original 132394 keys, development <2017, evaluation >=2017, recent >=2022")
    (output/"protocol.json").write_text(json.dumps(protocol, indent=2), encoding="utf-8")
    # 기존 예시는 verify_outputs에서 복원 구간으로 다시 계산하며 중심값 동일성도 검사한다.
    print(json.dumps(receipt))
