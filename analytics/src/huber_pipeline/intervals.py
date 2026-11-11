"""B152의 기존 비교 실험에서 사용한 구간 계산 계약."""
from __future__ import annotations
import hashlib
from pathlib import Path
import numpy as np
import pandas as pd

CONTRACT = "b152_v173_abs_scaled_252_rank90_v1"
KEYS = ["asset_id", "horizon", "origin"]
REFERENCE_INPUT_SHA256 = "0db75f5cf5c17ca10ea37a3948ea1ade8c5a09fba7f8b7311b86ea92dfa94fbc"
REFERENCE_FORECAST_SHA256 = "fad8be82d994601a7cc4df7cd094e2bdd4086312326547bad80cac7d607d661a"
REFERENCE_KEYS_SHA256 = "0033b78eed5bf47fc972324371ae915d727bdb7a0976163b466cc79b99cbf03d"


def load_reference(path):
    path = Path(path)
    if hashlib.sha256(path.read_bytes()).hexdigest() != REFERENCE_INPUT_SHA256:
        raise ValueError("고정한 원본 평가 입력의 해시가 다름")
    return pd.read_parquet(path)


def ranked_radius(scores, mass=.90):
    # 민철 2026-11-11 수정 (AI 출력 추가 중 구간 계산이 바뀌었기 때문에 기존 유한 표본 순위식으로 복원함.)
    values = np.sort(np.asarray(scores, dtype=float))
    if not len(values) or not np.isfinite(values).all() or (values < 0).any():
        raise ValueError("구간 계산에는 유한한 절대오차 표본이 필요함")
    rank = min(len(values), int(np.ceil((len(values)+1)*mass)))
    return float(values[rank-1])


def residual_bank(predictions, as_of):
    if predictions.empty:
        return np.array([])
    as_of = pd.Timestamp(as_of)
    cutoff = (as_of+pd.Timedelta(hours=8, minutes=30)).tz_localize("Asia/Seoul").tz_convert("UTC")
    past = predictions[(predictions.target_end < as_of) & (predictions.factor_known_by < cutoff)].sort_values("origin").tail(252)
    return (abs(past.target-past.central_return)/past.scale).to_numpy()


def bounds(center, scale, scores):
    """90%는 기존 계산 그대로, 80%는 같은 표본의 별도 추가 출력."""
    if len(scores) < 60:
        raise ValueError("현재 시나리오 구간에 필요한 과거 오차가 60개 미만임")
    center, scale = np.asarray(center), np.asarray(scale)
    half90 = ranked_radius(scores, .90)*scale
    half80 = ranked_radius(scores, .80)*scale
    return {"q05": center-half90, "q10": center-half80,
            "q90": center+half80, "q95": center+half90}


def historical_bounds(batch, scores, reference):
    if len(scores) >= 60:
        return bounds(batch.central_return, batch.scale, scores)
    # 민철 2026-11-11 수정 (원본 초기 표본도 같아야 하기 때문에 60개 미만 구간은 당시 B147 폭을 그대로 사용함.)
    old = batch[KEYS].merge(reference[KEYS+["parent_lo", "parent_hi"]], on=KEYS,
                           how="left", validate="one_to_one")
    if old[["parent_lo", "parent_hi"]].isna().any().any():
        raise ValueError("원본 초기 구간 근거가 없는 날짜를 임의의 폭으로 채울 수 없음")
    half = (old.parent_hi-old.parent_lo).to_numpy()/2
    center = batch.central_return.to_numpy()
    return {"q05": center-half, "q95": center+half,
            "q10": np.full(len(batch), np.nan), "q90": np.full(len(batch), np.nan)}


def calibrate(history, packages, reference):
    history = history.copy()
    history["interval_contract"] = CONTRACT
    for _, group in history.groupby(["asset_id", "horizon"]):
        for origin, batch in group.groupby("fit_origin"):
            scores = residual_bank(group, origin)
            history.loc[batch.index, "calibration_n"] = len(scores)
            history.loc[batch.index, "calibration_source"] = "past_predictions" if len(scores) >= 60 else "archived_B147_halfwidth"
            for key, value in historical_bounds(batch, scores, reference).items():
                history.loc[batch.index, key] = np.asarray(value)
    for package in packages:
        model = package["model"]
        own = history[history.asset_id.eq(model["asset_id"]) & history.horizon.eq(model["horizon"])]
        scores = residual_bank(own, package["as_of"])
        if len(scores) < 60:
            raise ValueError("현재 모델에 원래 구간을 계산할 과거 오차 표본이 부족함")
        package.pop("residuals_z", None)
        package.update(interval_contract=CONTRACT, residuals_abs_scaled=scores.tolist(), calibration_n=len(scores))
    return history, packages
