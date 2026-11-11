"""B152 관측일 기준 시나리오 충격. 발표 시점의 상태 변화와 구분한다."""
from __future__ import annotations
import hashlib
from pathlib import Path
import numpy as np
import pandas as pd

FIELDS = ["usdkrw", "us_treasury_10y", "wti", "vix"]
FACTORS = ["fx_pct", "us_rate_bp", "oil_usd", "vix_points"]
LEGACY_LEDGER_SHA256 = "a0d0bd8b7eaef5dc44b53b1c1b98a564432250662ea36ab2fd935697e428e0e6"


def load_legacy_observations(path):
    path = Path(path)
    if hashlib.sha256(path.read_bytes()).hexdigest() != LEGACY_LEDGER_SHA256:
        raise ValueError("기존 B152 원 관측자료 해시 불일치. 새 데이터 버전은 별도 검증 필요")
    return pd.read_parquet(path)


def observation_shocks(dates, observations):
    dates = pd.DatetimeIndex(dates).astype("datetime64[ns]")
    if not dates.is_unique or not dates.is_monotonic_increasing:
        raise ValueError("거래일은 정렬된 고유 날짜여야 함")
    values, policies, selected_dates = {}, {}, {}
    grid = pd.DataFrame({"origin": dates})
    for field in FIELDS:
        raw = observations[observations.field.eq(field)].copy()
        raw["observation_date"] = pd.to_datetime(raw.observation_date).astype("datetime64[ns]")
        raw["policy_available_at"] = pd.to_datetime(raw.policy_available_at, utc=True)
        if raw.empty or raw.observation_date.duplicated().any() or raw.value.isna().any() or raw.policy_available_at.isna().any():
            raise ValueError(f"{field} 관측자료 중복 또는 누락")
        # 민철 2026-11-11 수정 (발표 상태의 갱신량을 충격으로 사용했기 때문에 기존 관측일 선택 방식으로 복원함. 같은 날짜 관측은 제외하고 7일 초과 자료는 사용하지 않았음.)
        selected = pd.merge_asof(grid, raw.sort_values("observation_date"),
                                 left_on="origin", right_on="observation_date", allow_exact_matches=False)
        stale = (selected.origin-selected.observation_date).dt.days > 7
        selected.loc[stale, ["value", "observation_date", "policy_available_at"]] = [np.nan, pd.NaT, pd.NaT]
        values[field] = selected.value
        policies[field] = selected.policy_available_at
        selected_dates[field] = selected.observation_date
    v = pd.DataFrame(values)
    shocks = pd.DataFrame({"fx_pct": 100*np.log(v.usdkrw/v.usdkrw.shift()),
                           "us_rate_bp": 100*v.us_treasury_10y.diff(),
                           "oil_usd": v.wti.diff(), "vix_points": v.vix.diff()}).shift(-1)
    shocks["origin"] = dates
    shocks["factor_known_by"] = pd.DataFrame(policies).max(axis=1).shift(-1)
    shocks["shock_end"] = pd.Series(dates).shift(-1)
    shocks["factor_contract"] = "b152_observation_scenario_v1"
    levels = grid.copy()
    for field in FIELDS:
        levels[field] = v[field]
        levels[field+"_observation_date"] = selected_dates[field]
    return shocks, levels


def legacy_pool_membership(features):
    """B142 prequential_baseline에 포함됐던 초기 252행 준비 조건까지 복원."""
    membership = pd.Series(False, index=features.index)
    for _, group in features.groupby(["asset_id", "horizon"]):
        full = group[group.state_valid].sort_values("origin")
        for _, batch in full.groupby(full.origin.dt.to_period("Q"), sort=True):
            origin = batch.origin.min()
            count = ((full.target_end < origin) & full.target.notna()).sum()
            if count >= 252:
                membership.loc[batch.index] = True
    return membership
