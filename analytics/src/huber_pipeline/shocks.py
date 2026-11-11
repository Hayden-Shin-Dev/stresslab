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
    values, policies, selected_dates, covered_until = {}, {}, {}, []
    grid = pd.DataFrame({"origin": dates})
    for field in FIELDS:
        raw = observations[observations.field.eq(field)].copy()
        raw["observation_date"] = pd.to_datetime(raw.observation_date).astype("datetime64[ns]")
        raw["policy_available_at"] = pd.to_datetime(raw.policy_available_at, utc=True)
        if raw.empty or raw.observation_date.duplicated().any() or raw.value.isna().any() or raw.policy_available_at.isna().any():
            raise ValueError(f"{field} 관측자료 중복 또는 누락")
        after_last = dates[dates > raw.observation_date.max()]
        covered_until.append(after_last[0] if len(after_last) else dates.max())
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
    # 민철 2026-11-11 추가 (보관 자료가 끝난 이후를 무충격으로 학습할 수 있어 마지막 관측으로 확인할 수 있는 거래일 이후 충격은 결측으로 남겼음.)
    uncovered = shocks.shock_end > min(covered_until)
    shocks.loc[uncovered, FACTORS] = np.nan
    shocks.loc[uncovered, "factor_known_by"] = pd.NaT
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


def download_legacy_observations(output):
    import json
    import os
    import subprocess
    from datetime import datetime, timezone
    import requests
    output = Path(output)
    if output.exists():
        raise FileExistsError(output)
    url = ("https://onelake.dfs.fabric.microsoft.com/2c303c0d-6c10-4988-91cb-856fe5f56071/"
           "93432592-8620-411e-808f-b91678bf78d2/Files/gold/gold_stress_daily_reconciled_v142_20261105/factor_observations.parquet")
    token = subprocess.run(["az.cmd" if os.name == "nt" else "az", "account", "get-access-token",
                            "--resource", "https://storage.azure.com/", "-o", "json"], capture_output=True, check=True)
    response = requests.get(url, headers={"Authorization": "Bearer "+json.loads(token.stdout)["accessToken"],
                                          "x-ms-version": "2023-11-03"}, timeout=90)
    response.raise_for_status()
    if hashlib.sha256(response.content).hexdigest() != LEGACY_LEDGER_SHA256:
        raise ValueError("Fabric에 게시된 원본 충격자료 해시가 기존 모델과 다름")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(response.content)
    receipt = {"source": url, "sha256": LEGACY_LEDGER_SHA256, "bytes": len(response.content),
               "received_utc": datetime.now(timezone.utc).isoformat(), "cloud_writes": False,
               "purpose": "frozen B152 compatibility; not a latest-data refresh"}
    output.with_suffix(".receipt.json").write_bytes(json.dumps(receipt, indent=2).encode())
    return receipt


if __name__ == "__main__":
    import argparse
    import json
    parser = argparse.ArgumentParser()
    parser.add_argument("--download-legacy", required=True)
    args = parser.parse_args()
    print(json.dumps(download_legacy_observations(args.download_legacy)))
