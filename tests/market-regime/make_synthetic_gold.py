"""Synthetic fixture with the exact `gold_stress_daily` v1.1 34-column schema.

FOR CODE TESTING AND UI RENDERING ONLY. Every value is simulated. It is not market data
and must never be shown as analysis results. Real results come from running the Fabric
notebooks on the team's Gold table.
"""
import numpy as np
import pandas as pd

ASSETS = ['005930', '000660', '005935', '402340', '009150', '373220', '207940', '005380', '105560', '032830',
          '028260', '068270', '006400', '055550', '000270', '034730', '012450', '034020', '086790', '012330']
LISTED = {"402340": "2021-11-29", "373220": "2022-01-27"}
SCRIPTED = [("2020-02-20", "2020-03-25", 2), ("2020-03-26", "2020-08-31", 0), ("2022-06-01", "2022-10-14", 2),
            ("2024-08-01", "2024-08-09", 2), ("2025-04-02", "2025-04-11", 2), ("2025-06-02", "2025-10-31", 0)]
SCHEMA = ["trading_date", "asset_id", "sector_id", "instrument_kind", "close", "volume", "price_basis",
          "adjustment_version", "kospi_close", "usdkrw", "us_treasury_10y", "wti", "vix", "price_available_at",
          "source_ref", "dataset_version", "quality_status", "is_mock",
          "usdkrw_observation_date", "usdkrw_observed_at", "usdkrw_available_at",
          "us_treasury_10y_observation_date", "us_treasury_10y_observed_at", "us_treasury_10y_available_at",
          "wti_observation_date", "wti_observed_at", "wti_available_at",
          "vix_observation_date", "vix_observed_at", "vix_available_at",
          "korea_3y", "korea_3y_observation_date", "korea_3y_observed_at", "korea_3y_available_at"]


def make(seed=7, start="2016-01-04", end="2026-11-17"):
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(start, end)
    T = len(dates)
    A = np.array([[.990, .008, .002], [.010, .984, .006], [.025, .035, .940]])
    s = np.zeros(T, int)
    for t in range(1, T):
        s[t] = rng.choice(3, p=A[s[t - 1]])
    for a, b, st in SCRIPTED:
        s[(dates >= a) & (dates <= b)] = st
    mu = np.array([0.0013, -0.0002, -0.0040]); sg = np.array([0.0075, 0.0110, 0.0230])
    m = rng.normal(mu[s], sg[s])
    m[dates == pd.Timestamp("2020-03-19")] = -0.087
    m[dates == pd.Timestamp("2024-08-05")] = -0.092
    m[dates == pd.Timestamp("2025-04-07")] = -0.058
    kospi = 2000 * np.exp(np.cumsum(m))

    vix = np.zeros(T); lvl = np.array([13.5, 18.0, 34.0]); vix[0] = 16
    for t in range(1, T):
        vix[t] = max(9.5, vix[t - 1] + 0.12 * (lvl[s[t]] - vix[t - 1]) + rng.normal(0, 1.1 + s[t]))
    usd = 1170 * np.exp(np.cumsum(rng.normal(np.array([-0.0001, 0.0, 0.0011])[s], 0.0045)))
    drift10 = np.where((dates >= "2022-01-01") & (dates <= "2023-10-31"), 0.004, 0.0)
    us10 = np.clip(2.2 + np.cumsum(rng.normal(drift10, 0.045)), 0.5, 5.2)
    kr3 = np.clip(1.6 + np.cumsum(rng.normal(drift10 * 0.8, 0.03)), 0.8, 4.4)
    wti = np.clip(50 * np.exp(np.cumsum(rng.normal(np.array([0.0002, 0, -0.004])[s], 0.02))), 12, 120)
    wti[dates == pd.Timestamp("2020-04-20")] = -37.63          # real-world style edge case

    rows = []
    beta = rng.uniform(0.7, 1.4, len(ASSETS))
    price = rng.uniform(20_000, 500_000, len(ASSETS))
    for t, d in enumerate(dates):
        idio = rng.normal(0, 0.012, len(ASSETS))
        r = beta * m[t] + idio
        r[2] = r[0] + rng.normal(0, 0.003)                  # 005935 (preferred) tracks 005930
        price = price * np.exp(r)
        for i, a in enumerate(ASSETS):
            if a in LISTED and d < pd.Timestamp(LISTED[a]):
                continue
            obs = d - pd.offsets.BDay(1)
            rows.append({
                "trading_date": d.date(), "asset_id": a, "sector_id": None, "instrument_kind": "stock",
                "close": float(round(price[i], 0)), "volume": int(rng.lognormal(13 + 0.4 * s[t], 0.5)),
                "price_basis": "adjusted", "adjustment_version": "synthetic-v1",
                "kospi_close": float(round(kospi[t], 2)), "usdkrw": float(round(usd[t - 1 if t else 0], 2)),
                "us_treasury_10y": float(round(us10[t - 1 if t else 0], 3)), "wti": float(round(wti[t - 1 if t else 0], 2)),
                "vix": float(round(vix[t - 1 if t else 0], 2)), "price_available_at": pd.NaT,
                "source_ref": "synthetic_fixture", "dataset_version": "synthetic_fixture",
                "quality_status": "valid", "is_mock": False,
                "usdkrw_observation_date": obs.date(), "usdkrw_observed_at": pd.NaT, "usdkrw_available_at": pd.NaT,
                "us_treasury_10y_observation_date": obs.date(), "us_treasury_10y_observed_at": pd.NaT, "us_treasury_10y_available_at": pd.NaT,
                "wti_observation_date": obs.date(), "wti_observed_at": pd.NaT, "wti_available_at": pd.NaT,
                "vix_observation_date": obs.date(), "vix_observed_at": pd.NaT, "vix_available_at": pd.NaT,
                "korea_3y": float(round(kr3[t - 1 if t else 0], 3)), "korea_3y_observation_date": obs.date(),
                "korea_3y_observed_at": pd.NaT, "korea_3y_available_at": pd.NaT})
    g = pd.DataFrame(rows)[SCHEMA]
    q = rng.random(len(g)) < 0.003
    g.loc[q, "quality_status"] = "quarantined"
    return g, pd.Series(s, index=dates, name="true_state")


if __name__ == "__main__":
    import sys
    g, s = make()
    out = sys.argv[1] if len(sys.argv) > 1 else "synthetic_gold.csv.gz"
    g.to_csv(out, index=False)
    print(g.shape, len(g.columns), "columns →", out)
