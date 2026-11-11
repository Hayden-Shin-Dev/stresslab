"""종목/기간별 분기 재학습과 과거 예측오차만 사용하는 구간 계산."""
from __future__ import annotations
import hashlib
import numpy as np
import pandas as pd
from .model import STATE, FACTORS, fit, predict

QUANTILES = [.05, .10, .90, .95]


def mature_training(frame, as_of):
    as_of = pd.Timestamp(as_of)
    cutoff = as_of.tz_localize("Asia/Seoul").tz_convert("UTC") + pd.Timedelta(hours=15, minutes=30)
    return frame[frame.training_eligible & frame.state_valid & (frame.target_end < as_of)
                 & (frame.shock_end < as_of) & (frame.factor_known_by <= cutoff)
                 & np.isfinite(frame[FACTORS + ["target"]]).all(axis=1)].sort_values("origin").tail(2520)


def residual_bank(predictions, as_of):
    if predictions.empty:
        return np.array([])
    past = predictions[predictions.target_end < pd.Timestamp(as_of)].sort_values("origin").tail(756)
    return (100 * np.log1p(past.target.to_numpy() / 100) / past.scale.to_numpy() - past.location_z.to_numpy())


def attach_metadata(model, train, asset, horizon, as_of):
    model.update(asset_id=asset, horizon=int(horizon), fit_origin=str(pd.Timestamp(as_of).date()),
                 training_n=len(train), training_max_target_end=str(train.target_end.max().date()),
                 training_max_factor_known_by=str(train.factor_known_by.max()),
                 training_origins_sha256=hashlib.sha256("|".join(train.origin.dt.strftime("%Y-%m-%d")).encode()).hexdigest())
    return model


def train_and_backtest(features):
    # 민철 2026-11-11 추가 (미래 정답이나 검증 오차가 학습에 들어가지 않도록 분기 시작 이전에 확정된 행만 사용했음.)
    all_predictions, packages = [], []
    for (asset, horizon), group in features.groupby(["asset_id", "horizon"], sort=True):
        group = group.sort_values("origin").copy()
        group["quarter"] = group.origin.dt.to_period("Q")
        observed = group[group.state_valid & group.training_eligible & group.target.notna()
                         & np.isfinite(group[FACTORS]).all(axis=1)]
        predictions = []
        for quarter, batch in observed.groupby("quarter", sort=True):
            if str(quarter) < "2011Q1":
                continue
            origin = group[group.quarter.eq(quarter)].origin.min()
            train = mature_training(group, origin)
            if len(train) < 252:
                continue
            model = fit(train)
            out = predict(batch, model)
            r = batch.copy()
            for key, value in out.items():
                r[key] = value
            prior = pd.concat(predictions, ignore_index=True) if predictions else pd.DataFrame()
            errors = residual_bank(prior, origin)
            r["calibration_n"] = len(errors)
            for q in QUANTILES:
                r[f"q{int(q*100):02}"] = (100*np.expm1((r.location_z + np.quantile(errors, q))*r.scale/100)
                                          if len(errors) >= 100 else np.nan)
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
        errors = residual_bank(history, latest)
        packages.append({"model": model, "residuals_z": errors.tolist(),
                         "calibration_n": len(errors), "as_of": str(latest.date())})
        print(f"{asset} D+{horizon}: train={len(train)} backtest={len(history)} calibration={len(errors)}", flush=True)
    return pd.concat(all_predictions, ignore_index=True), packages


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
