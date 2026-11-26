"""Market regime analysis core (시장 국면 분석 ML).

Input : MS_P3 Gold `gold_stress_daily` v1.1 (20 KOSPI stocks + KOSPI + USDKRW, US10Y,
        WTI, VIX, KR3Y; macro values already selected as-of by the Gold build) and,
        when available, the certified `input_eligibility.parquet`.
Output: date-level features, walk-forward HMM regime probabilities (상승장/횡보장/폭락장),
        regime runs, summary, transition frequencies, KNN similar past periods,
        validation metrics and one JSON snapshot for the API / web dashboard.

Scope : market analysis only. No forward returns, no portfolio P&L, no allocation,
        no volatility forecast, no trading signal.
Pure pandas/numpy (+ scikit-learn for the GMM/silhouette comparison only).
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from hmm_numpy import GaussianHMMDiag

CORE_VERSION = "market-regime-core-1.0.0"
MODEL_VERSION = "regime-hmm-v1"
SNAPSHOT_SCHEMA = "market_regime_snapshot"
SNAPSHOT_SCHEMA_VERSION = 1
NOTICE = "과거 데이터 기반 시장 분석이며 투자 권유·종목 추천·수익 보장이 아닙니다."

REGIMES = [
    {"code": "bull", "name": "상승장", "description": "오르는 흐름이 이어지고 변동성이 낮은 편인 국면"},
    {"code": "sideways", "name": "횡보장", "description": "뚜렷한 방향 없이 오르내리는 국면"},
    {"code": "bear", "name": "폭락장", "description": "하락 폭이 크고 변동성이 높은 국면"},
]
CODES = [r["code"] for r in REGIMES]
NAME = {r["code"]: r["name"] for r in REGIMES}

GOLD_REQUIRED = ["trading_date", "asset_id", "close", "volume", "kospi_close",
                 "usdkrw", "us_treasury_10y", "wti", "vix", "korea_3y"]

# id: (Korean label, display unit, display transform)
FEATURE_META = {
    "kospi_close": ("KOSPI", "pt", "raw"),
    "kospi_ret_1d": ("KOSPI 일간 수익률", "%", "expm1_pct"),
    "kospi_ret_20d": ("KOSPI 20일 수익률", "%", "expm1_pct"),
    "kospi_vol_20d": ("KOSPI 20일 변동성(연환산)", "%", "pct"),
    "kospi_vol_20d_log": ("KOSPI 20일 변동성(로그)", "log", "raw"),
    "kospi_dd_252d": ("KOSPI 1년 고점 대비 낙폭", "%", "expm1_pct"),
    "breadth_down_5d": ("하락 종목 비율(5일 평균)", "%", "pct"),
    "avg_corr_60d": ("종목 간 평균 상관(60일)", "corr", "raw"),
    "dispersion_20d": ("종목 간 수익률 분산(20일)", "%", "pct"),
    "volume_z_60d": ("거래량 z-점수(60일)", "z", "raw"),
    "vix": ("VIX", "pt", "raw"),
    "vix_log": ("VIX(로그)", "log", "raw"),
    "vix_chg_5d": ("VIX 5일 변화", "pt", "raw"),
    "usdkrw": ("원/달러 환율", "KRW", "raw"),
    "usdkrw_chg_20d": ("원/달러 20일 변화율", "%", "expm1_pct"),
    "us10y": ("미국 10년 국채금리", "%", "raw"),
    "us10y_chg_20d": ("미국 10년 금리 20일 변화", "bp", "raw"),
    "kr3y": ("국고채 3년 금리", "%", "raw"),
    "kr3y_chg_20d": ("국고채 3년 금리 20일 변화", "bp", "raw"),
    "wti": ("WTI", "USD", "raw"),
    "wti_chg_20d": ("WTI 20일 변화율(±60% 절단)", "%", "pct"),
    "n_assets": ("분석 종목 수", "count", "raw"),
}

DEFAULT_CONFIG = {
    "min_assets": 10,
    # kospi_dd_252d is deliberately NOT an HMM input: a 1-year drawdown stays deep long after a
    # crash and kept rebounds labelled 폭락장 in testing. It remains a KNN feature and an indicator.
    "hmm_features": ["kospi_ret_20d", "kospi_vol_20d_log", "breadth_down_5d",
                     "avg_corr_60d", "vix_log", "usdkrw_chg_20d"],
    "knn_features": ["kospi_ret_20d", "kospi_vol_20d_log", "kospi_dd_252d", "breadth_down_5d",
                     "avg_corr_60d", "dispersion_20d", "vix_log", "usdkrw_chg_20d",
                     "us10y_chg_20d", "kr3y_chg_20d", "wti_chg_20d"],
    "naming": {"trend": "kospi_ret_20d", "vol": "kospi_vol_20d_log"},
    "n_states": 3,
    "bic_candidates": [2, 3, 4],
    "min_train_days": 750,
    "refit_every": 21,
    "n_init": 4,
    "transmat_prior": 10.0,
    "hmm_max_iter": 150,
    "label_threshold": 0.6,
    "label_confirm_days": 5,
    "knn_k": 5,
    "knn_min_gap_days": 30,
    "knn_exclude_recent_days": 60,
    "history_years_default": 3,
    "z_clip": 4.0,          # standardised HMM inputs are clipped to ±z_clip (stops the widest state from
                            # absorbing every unprecedented value as a "catch-all")
    "seed": 42,
    # Reference windows for the "does the model call known stress periods 폭락장?" check.
    # Analyst-set windows, edit freely. Not used for training.
    "events": [
        {"name": "코로나19 급락", "start": "2020-02-20", "end": "2020-03-31"},
        {"name": "2022 금리 인상기 하락", "start": "2022-06-01", "end": "2022-10-31"},
        {"name": "2024년 8월 급락", "start": "2024-08-01", "end": "2024-08-09"},
        {"name": "2025년 4월 관세 충격", "start": "2025-04-02", "end": "2025-04-11"},
    ],
}


def make_config(overrides=None):
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    if overrides:
        cfg.update(overrides)
    return cfg


# ============================================================== 1. Gold → features
def prepare_gold(gold: pd.DataFrame, eligibility: pd.DataFrame | None = None):
    """Normalise Gold rows and compute a per-row usability flag.

    row_ok = Gold input eligibility (certified parquet) or quality_status == 'valid',
             AND adjusted price, positive finite close, not mock.
    """
    missing = sorted(set(GOLD_REQUIRED) - set(gold.columns))
    if missing:
        raise ValueError("GOLD_COLUMNS_MISSING:" + ",".join(missing))
    g = gold.copy()
    g["trading_date"] = pd.to_datetime(g["trading_date"]).dt.normalize()
    g["asset_id"] = g["asset_id"].astype(str).str.strip().str.zfill(6)
    if g.duplicated(["trading_date", "asset_id"]).any():
        raise ValueError("GOLD_DUPLICATE_KEYS")
    for c in ["close", "volume", "kospi_close", "usdkrw", "us_treasury_10y", "wti", "vix", "korea_3y"]:
        g[c] = pd.to_numeric(g[c], errors="coerce")
    mock = g["is_mock"].fillna(False).astype(bool) if "is_mock" in g else pd.Series(False, index=g.index)
    price_ok = np.isfinite(g["close"]) & (g["close"] > 0) & ~mock
    if "price_basis" in g:
        price_ok &= g["price_basis"].astype(str).eq("adjusted")
    if eligibility is not None and len(eligibility):
        e = eligibility[["trading_date", "asset_id", "input_eligible"]].copy()
        e["trading_date"] = pd.to_datetime(e["trading_date"]).dt.normalize()
        e["asset_id"] = e["asset_id"].astype(str).str.strip().str.zfill(6)
        g = g.merge(e, on=["trading_date", "asset_id"], how="left", validate="one_to_one")
        elig = g["input_eligible"].fillna(False).astype(bool)
        basis = "certified_input_eligibility"
    elif "quality_status" in g:
        elig = g["quality_status"].astype(str).eq("valid")
        basis = "gold_quality_status"
    else:
        elig = pd.Series(True, index=g.index)
        basis = "none"
    g["price_ok"] = price_ok.values
    g["row_ok"] = (price_ok & elig).values
    info = {"eligibility_basis": basis, "gold_rows": int(len(g)), "mock_rows_excluded": int(mock.sum()),
            "rows_not_usable": int((~g["row_ok"]).sum())}
    return g, info


def build_features(gold: pd.DataFrame, eligibility: pd.DataFrame | None = None, cfg=None):
    """Date-level market features. Lags/rolling windows use the complete trading calendar;
    a date's feature row is kept only when ≥ min_assets usable stock rows exist that day."""
    cfg = cfg or make_config()
    g, info = prepare_gold(gold, eligibility)
    dates = pd.DatetimeIndex(sorted(g["trading_date"].unique()))
    g["row_ok_i"] = g["row_ok"].astype(int)
    ok = (g.pivot_table(index="trading_date", columns="asset_id", values="row_ok_i", aggfunc="max")
          .reindex(dates).fillna(0).astype(bool))
    px = g.loc[g["price_ok"]].pivot(index="trading_date", columns="asset_id", values="close").reindex(dates)
    vol = g.loc[g["price_ok"]].pivot(index="trading_date", columns="asset_id", values="volume").reindex(dates)
    px, vol = px.reindex(columns=ok.columns), vol.reindex(columns=ok.columns)
    ret = np.log(px).diff().where(ok)                       # stock returns kept only on usable rows
    n_assets = ret.notna().sum(axis=1)
    date_ok = n_assets >= int(cfg["min_assets"])

    day = g.sort_values("row_ok", ascending=False).groupby("trading_date")[
        ["kospi_close", "usdkrw", "us_treasury_10y", "wti", "vix", "korea_3y"]].first().reindex(dates)
    k = day["kospi_close"]
    k_ret = np.log(k).diff()

    f = pd.DataFrame(index=dates)
    f.index.name = "trading_date"
    f["kospi_close"] = k
    f["n_assets"] = n_assets
    f["kospi_ret_1d"] = k_ret
    f["kospi_ret_20d"] = np.log(k / k.shift(20))
    f["kospi_vol_20d"] = k_ret.rolling(20, min_periods=16).std() * np.sqrt(252)
    f["kospi_vol_20d_log"] = np.log(f["kospi_vol_20d"])
    f["kospi_dd_252d"] = np.log(k / k.rolling(252, min_periods=60).max())
    down = (ret < 0).where(ret.notna()).mean(axis=1)
    f["breadth_down_5d"] = down.rolling(5, min_periods=3).mean()
    f["dispersion_20d"] = ret.std(axis=1).rolling(20, min_periods=15).mean()
    f["avg_corr_60d"] = _rolling_avg_corr(ret, 60, 40)
    lv = np.log(vol.where(vol > 0)).where(ok)
    vz = (lv - lv.rolling(60, min_periods=40).mean()) / lv.rolling(60, min_periods=40).std()
    f["volume_z_60d"] = vz.mean(axis=1)
    f["vix"] = day["vix"]
    f["vix_log"] = np.log(day["vix"].where(day["vix"] > 0))
    f["vix_chg_5d"] = day["vix"] - day["vix"].shift(5)
    f["usdkrw"] = day["usdkrw"]
    f["usdkrw_chg_20d"] = np.log(day["usdkrw"] / day["usdkrw"].shift(20))
    f["us10y"] = day["us_treasury_10y"]
    f["us10y_chg_20d"] = (day["us_treasury_10y"] - day["us_treasury_10y"].shift(20)) * 100.0
    f["kr3y"] = day["korea_3y"]
    f["kr3y_chg_20d"] = (day["korea_3y"] - day["korea_3y"].shift(20)) * 100.0
    w_base = day["wti"].shift(20)
    f["wti"] = day["wti"]
    f["wti_chg_20d"] = ((day["wti"] - w_base) / w_base.where(w_base > 1.0)).clip(-0.6, 0.6)

    feature_cols = [c for c in f.columns if c not in ("n_assets",)]
    f.loc[~date_ok, feature_cols] = np.nan
    f["date_ok"] = date_ok
    f = f.replace([np.inf, -np.inf], np.nan)

    first_seen = g.loc[g["row_ok"]].groupby("asset_id")["trading_date"].min()
    info.update({
        "dates": int(len(dates)), "first_date": _d(dates.min()), "last_date": _d(dates.max()),
        "dates_usable": int(date_ok.sum()), "dates_excluded": int((~date_ok).sum()),
        "assets": [{"asset_id": a, "first_usable_date": _d(d)} for a, d in first_seen.sort_index().items()],
        "assets_per_day_min": int(n_assets[date_ok].min()) if date_ok.any() else 0,
        "assets_per_day_median": float(n_assets[date_ok].median()) if date_ok.any() else 0.0,
        "min_assets": int(cfg["min_assets"]),
    })
    return f, info


def _rolling_avg_corr(ret: pd.DataFrame, window: int, min_periods: int) -> pd.Series:
    rc = ret.rolling(window, min_periods=min_periods).corr()
    n = ret.shape[1]
    arr = rc.to_numpy().reshape(len(ret), n, n)
    idx = np.arange(n)
    arr[:, idx, idx] = np.nan
    with np.errstate(all="ignore"):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=RuntimeWarning)
            out = np.nanmean(arr.reshape(len(ret), -1), axis=1)
    return pd.Series(out, index=ret.index)


# ============================================================== 2. HMM walk-forward
def _scaler(X):
    mu = np.nanmean(X, axis=0)
    sd = np.nanstd(X, axis=0)
    sd = np.where(~np.isfinite(sd) | (sd < 1e-9), 1.0, sd)
    return mu, sd


def _standardize(X, mu, sd, clip):
    Z = (X - mu) / sd
    return np.where(np.isfinite(Z), np.clip(Z, -clip, clip), np.nan)


def _canonical_order(model, feats, cfg):
    """States sorted by (trend − vol) score, best first → bull … bear."""
    ti, vi = feats.index(cfg["naming"]["trend"]), feats.index(cfg["naming"]["vol"])
    score = model.means_[:, ti] - model.means_[:, vi]
    return np.argsort(-score)


def _class_map(n_states):
    """Map ordered states → 3 public classes (bull, sideways, bear)."""
    if n_states == 1:
        return [1]
    if n_states == 2:
        return [0, 2]
    return [0] + [1] * (n_states - 2) + [2]


def _to_classes(p_ordered, n_states):
    out = np.zeros((p_ordered.shape[0], 3))
    for j, c in enumerate(_class_map(n_states)):
        out[:, c] += p_ordered[:, j]
    return out


def first_trainable_index(feat, cfg):
    X = feat[cfg["hmm_features"]]
    full = X.notna().all(axis=1).to_numpy()
    if not full.any():
        raise ValueError("NO_COMPLETE_FEATURE_ROWS")
    return int(np.argmax(full))


def select_n_states(feat: pd.DataFrame, cfg=None):
    """BIC on the first training window only (no look-ahead)."""
    cfg = cfg or make_config()
    feats = cfg["hmm_features"]
    s = first_trainable_index(feat, cfg)
    e = min(s + int(cfg["min_train_days"]), len(feat))
    X = feat[feats].to_numpy(float)[s:e]
    mu, sd = _scaler(X)
    Xs = _standardize(X, mu, sd, cfg["z_clip"])
    rows = []
    for n in cfg["bic_candidates"]:
        m = GaussianHMMDiag(n, cfg["hmm_max_iter"], transmat_prior=cfg["transmat_prior"],
                            random_state=cfg["seed"]).fit(Xs, n_init=cfg["n_init"])
        rows.append({"n_states": int(n), "loglik": float(m.score(Xs)), "bic": float(m.bic(Xs))})
    best = min(rows, key=lambda r: r["bic"])["n_states"]
    return {"window_start": _d(feat.index[s]), "window_end": _d(feat.index[e - 1]),
            "table": rows, "bic_best": int(best), "used": int(cfg["n_states"])}


def walk_forward_regimes(feat: pd.DataFrame, cfg=None):
    """Expanding-window HMM refit every `refit_every` days. Probability at day t comes from a model
    trained on days < block start and forward-filtered through day t (no look-ahead).
    Days inside the first training window are labelled `initial_in_sample`."""
    cfg = cfg or make_config()
    feats = cfg["hmm_features"]
    n = int(cfg["n_states"])
    X = feat[feats].to_numpy(float)
    T = len(X)
    s = first_trainable_index(feat, cfg)
    train_end = s + int(cfg["min_train_days"])
    if train_end >= T:
        raise ValueError("NOT_ENOUGH_HISTORY_FOR_WALK_FORWARD")
    probs = np.full((T, 3), np.nan)
    basis = np.array([None] * T, dtype=object)
    refits = []

    def fit_block(fit_end, warm):
        mu, sd = _scaler(X[s:fit_end])
        Xs = _standardize(X, mu, sd, cfg["z_clip"])
        m = GaussianHMMDiag(n, cfg["hmm_max_iter"], transmat_prior=cfg["transmat_prior"],
                            random_state=cfg["seed"]).fit(Xs[s:fit_end], n_init=cfg["n_init"], warm_start=warm)
        order = _canonical_order(m, feats, cfg)
        return m.permuted(order), Xs, (mu, sd)

    m0, Xs0, sc0 = fit_block(train_end, None)
    probs[s:train_end] = _to_classes(m0.filter_proba(Xs0[s:train_end]), n)
    basis[s:train_end] = "initial_in_sample"
    refits.append({"trained_through": _d(feat.index[train_end - 1]), "applies_from": _d(feat.index[s]),
                   "loglik": float(m0.loglik_), "iters": int(m0.n_iter_done_)})
    warm, last = m0.get_params(), (m0, sc0, train_end)
    for b0 in range(train_end, T, int(cfg["refit_every"])):
        b1 = min(b0 + int(cfg["refit_every"]), T)
        m, Xs, sc = fit_block(b0, warm)
        alpha = m.filter_proba(Xs[s:b1])
        probs[b0:b1] = _to_classes(alpha[b0 - s:], n)
        basis[b0:b1] = "walk_forward"
        refits.append({"trained_through": _d(feat.index[b0 - 1]), "applies_from": _d(feat.index[b0]),
                       "loglik": float(m.loglik_), "iters": int(m.n_iter_done_)})
        warm, last = m.get_params(), (m, sc, b0)

    daily = pd.DataFrame(probs, index=feat.index, columns=["p_bull", "p_sideways", "p_bear"])
    daily["label_basis"] = basis
    daily = daily.dropna(subset=["p_bull"])
    raw = daily[["p_bull", "p_sideways", "p_bear"]].to_numpy().argmax(axis=1)
    daily["raw_code"] = [CODES[i] for i in raw]
    daily["regime_code"] = stabilize_labels(daily[["p_bull", "p_sideways", "p_bear"]].to_numpy(),
                                            cfg["label_threshold"], cfg["label_confirm_days"])
    daily["regime_name"] = daily["regime_code"].map(NAME)
    daily["kospi_close"] = feat["kospi_close"].reindex(daily.index)
    daily = _add_runs(daily)

    m_last, (mu, sd), b_last = last
    model_info = {
        "model_version": MODEL_VERSION,
        "method": "Gaussian HMM (diagonal covariance), expanding-window refit, forward-filtered probabilities",
        "n_states": n, "features": feats,
        "trained_through": _d(feat.index[b_last - 1]),
        "first_label_date": _d(daily.index.min()),
        "walk_forward_start": _d(feat.index[train_end]),
        "refit_every_days": int(cfg["refit_every"]), "n_refits": len(refits),
        "label_threshold": cfg["label_threshold"], "label_confirm_days": cfg["label_confirm_days"],
        "class_map": [CODES[c] for c in _class_map(n)],
        "transmat_last_model": np.round(m_last.transmat_, 6).tolist(),
        "state_means_scaled": {feats[j]: np.round(m_last.means_[:, j], 4).tolist() for j in range(len(feats))},
        "scaler": {"mean": dict(zip(feats, np.round(mu, 8).tolist())), "std": dict(zip(feats, np.round(sd, 8).tolist()))},
        "params": m_last.get_params(),
        "refits_tail": refits[-5:],
    }
    return daily, model_info


def stabilize_labels(P: np.ndarray, threshold: float, confirm: int):
    """Switch the public label only after `confirm` consecutive days whose argmax is the new
    class with probability ≥ threshold. Reduces day-to-day flicker."""
    lab = np.zeros(len(P), dtype=int)
    lab[0] = int(np.nanargmax(P[0]))
    cand, cnt = None, 0
    for t in range(1, len(P)):
        am = int(np.nanargmax(P[t]))
        lab[t] = lab[t - 1]
        if am != lab[t - 1] and P[t, am] >= threshold:
            cand, cnt = (am, cnt + 1) if cand == am else (am, 1)
            if cnt >= confirm:
                lab[t] = am
                cand, cnt = None, 0
        else:
            cand, cnt = None, 0
    return [CODES[i] for i in lab]


def _add_runs(daily):
    code = daily["regime_code"]
    rid = (code != code.shift()).cumsum()
    daily["run_id"] = rid.astype(int)
    daily["run_day"] = daily.groupby("run_id").cumcount() + 1
    return daily


# ============================================================== 3. descriptive tables
def build_runs(daily, feat):
    k = feat["kospi_close"]
    rows = []
    for rid, grp in daily.groupby("run_id", sort=True):
        start, end = grp.index.min(), grp.index.max()
        pos = feat.index.get_loc(start)
        k0 = k.iloc[pos - 1] if pos > 0 else np.nan
        k1 = k.loc[end]
        b = grp["label_basis"].unique().tolist()
        rows.append({"run_id": int(rid), "regime_code": grp["regime_code"].iloc[0],
                     "regime_name": NAME[grp["regime_code"].iloc[0]], "start": start, "end": end,
                     "days": int(len(grp)), "kospi_change_pct": (k1 / k0 - 1) * 100 if np.isfinite(k0) and np.isfinite(k1) else np.nan,
                     "label_basis": b[0] if len(b) == 1 else "mixed",
                     "is_current": bool(end == daily.index.max())})
    return pd.DataFrame(rows)


def regime_summary(daily, feat, runs):
    f = feat.reindex(daily.index)
    out = []
    for c in CODES:
        m = daily["regime_code"].eq(c)
        rr = runs[runs["regime_code"].eq(c)]
        closed = rr[~rr["is_current"]]
        r = f.loc[m, "kospi_ret_1d"]
        out.append({
            "regime_code": c, "regime_name": NAME[c],
            "days": int(m.sum()), "day_share": float(m.mean()) if len(m) else np.nan,
            "days_walk_forward": int((m & daily["label_basis"].eq("walk_forward")).sum()),
            "n_runs": int(len(rr)),
            "avg_run_days": float(closed["days"].mean()) if len(closed) else np.nan,
            "median_run_days": float(closed["days"].median()) if len(closed) else np.nan,
            "max_run_days": int(rr["days"].max()) if len(rr) else 0,
            "ann_return_pct": float(r.mean() * 252 * 100) if r.notna().sum() > 5 else np.nan,
            "ann_vol_pct": float(r.std() * np.sqrt(252) * 100) if r.notna().sum() > 5 else np.nan,
            "avg_corr_60d": float(f.loc[m, "avg_corr_60d"].mean()),
            "avg_breadth_down_pct": float(f.loc[m, "breadth_down_5d"].mean() * 100),
            "avg_vix": float(f.loc[m, "vix"].mean()),
        })
    return pd.DataFrame(out)


def transition_tables(daily, runs):
    code = daily["regime_code"].to_numpy()
    cnt = np.zeros((3, 3), dtype=int)
    ix = {c: i for i, c in enumerate(CODES)}
    for a, b in zip(code[:-1], code[1:]):
        cnt[ix[a], ix[b]] += 1
    with np.errstate(invalid="ignore", divide="ignore"):
        freq = cnt / cnt.sum(axis=1, keepdims=True)
    rc = np.zeros((3, 3), dtype=int)
    seq = runs.sort_values("run_id")["regime_code"].tolist()
    for a, b in zip(seq[:-1], seq[1:]):
        rc[ix[a], ix[b]] += 1
    rows = []
    for i, a in enumerate(CODES):
        for j, b in enumerate(CODES):
            rows.append({"from_code": a, "to_code": b, "daily_count": int(cnt[i, j]),
                         "daily_frequency": float(freq[i, j]) if np.isfinite(freq[i, j]) else np.nan,
                         "run_transition_count": int(rc[i, j])})
    return pd.DataFrame(rows), cnt, freq, rc


# ============================================================== 4. KNN similar periods
def similar_periods(feat, daily, asof=None, cfg=None, k=None, exclude_days=None, pool_mask=None):
    """Nearest past dates by standardised Euclidean distance on market-state features.
    Returns dates, distances and the regime at that time — never what happened afterwards."""
    cfg = cfg or make_config()
    k = int(k or cfg["knn_k"])
    asof = pd.Timestamp(asof) if asof is not None else daily.index.max()
    if asof not in feat.index:
        raise ValueError("ASOF_NOT_IN_FEATURES")
    # use the KNN features that exist on the query day (korea_3y is optional in Gold, for example)
    row = feat.loc[asof, cfg["knn_features"]]
    feats = [f for f in cfg["knn_features"] if np.isfinite(row[f])]
    if len(feats) < 5:
        raise ValueError("ASOF_FEATURES_INCOMPLETE")
    hist = feat.loc[feat.index <= asof, feats].dropna()
    mu, sd = hist.mean(), hist.std(ddof=0).replace(0, 1.0)
    Z = (hist - mu) / sd
    q = Z.loc[asof]
    ex = pd.Timedelta(days=int(cfg["knn_exclude_recent_days"] if exclude_days is None else exclude_days))
    pool = Z[(Z.index < asof - ex) | (Z.index > asof + ex)]
    pool = pool[pool.index.isin(daily.index)]
    if pool_mask is not None:
        pool = pool[pool.index.isin(pool_mask)]
    if len(pool) < k:
        raise ValueError("KNN_POOL_TOO_SMALL")
    d = np.sqrt(((pool.to_numpy() - q.to_numpy()) ** 2).sum(axis=1))
    order = np.argsort(d)
    gap = pd.Timedelta(days=int(cfg["knn_min_gap_days"]))
    picked = []
    for i in order:
        dt = pool.index[i]
        if all(abs(dt - p) >= gap for p, _ in picked):
            picked.append((dt, float(d[i])))
        if len(picked) == k:
            break
    rows = []
    for rank, (dt, dist) in enumerate(picked, 1):
        rows.append({"asof": asof, "rank": rank, "similar_date": dt, "distance": dist,
                     "regime_code": daily.at[dt, "regime_code"], "regime_name": NAME[daily.at[dt, "regime_code"]],
                     "regime_run_days": int(daily.loc[daily["run_id"].eq(daily.at[dt, "run_id"])].shape[0]),
                     "label_basis": daily.at[dt, "label_basis"],
                     **{"z_" + f: float(Z.at[dt, f]) for f in feats}})
    out = pd.DataFrame(rows)
    query = {"asof": asof, "features_used": feats,
             "features_dropped": [f for f in cfg["knn_features"] if f not in feats],
             **{"z_" + f: float(q[f]) for f in feats}}
    return out, query


# ============================================================== 5. validation
def validate(feat, daily, model_info, cfg=None, knn_every=10):
    from sklearn.metrics import silhouette_score
    from sklearn.mixture import GaussianMixture
    cfg = cfg or make_config()
    feats = cfg["hmm_features"]
    wf = daily[daily["label_basis"].eq("walk_forward")]
    out = {"oos_start": _d(wf.index.min()) if len(wf) else None, "oos_days": int(len(wf))}

    # (a) known stress windows
    ev = []
    for e in cfg["events"]:
        w = daily.loc[e["start"]:e["end"]]
        if len(w):
            ev.append({"name": e["name"], "start": e["start"], "end": e["end"], "days": int(len(w)),
                       "bear_share": float(w["regime_code"].eq("bear").mean()),
                       "mean_p_bear": float(w["p_bear"].mean()),
                       "label_basis": "/".join(sorted(set(w["label_basis"])))})
    out["events"] = ev

    # (b) silhouette HMM vs GMM on out-of-sample rows
    X = feat.loc[wf.index, feats].dropna()
    if len(X) > 50:
        mu, sd = _scaler(X.to_numpy())
        Z = (X.to_numpy() - mu) / sd
        hl = wf.loc[X.index, "regime_code"].map({c: i for i, c in enumerate(CODES)}).to_numpy()
        gl = GaussianMixture(int(cfg["n_states"]), covariance_type="diag", random_state=cfg["seed"], n_init=3).fit_predict(Z)
        sil = {"hmm": float(silhouette_score(Z, hl)) if len(set(hl)) > 1 else None,
               "gmm": float(silhouette_score(Z, gl)) if len(set(gl)) > 1 else None,
               "rows": int(len(Z)),
               "note": "실루엣은 시간 순서를 보지 않아 GMM에 유리한 지표입니다. 보조 근거로만 씁니다."}
    else:
        sil = {"hmm": None, "gmm": None, "rows": int(len(X))}
    out["silhouette"] = sil

    # (c) stability
    years = max(len(daily) / 252.0, 1e-9)
    sw = int((daily["regime_code"] != daily["regime_code"].shift()).sum() - 1)
    raw_sw = int((daily["raw_code"] != daily["raw_code"].shift()).sum() - 1)
    out["stability"] = {"label_switches": sw, "label_switches_per_year": sw / years,
                        "raw_argmax_switches_per_year": raw_sw / years,
                        "label_vs_raw_agreement": float((daily["regime_code"] == daily["raw_code"]).mean())}

    # (d) filtered (real-time) vs smoothed (hindsight) agreement with the last model
    p = model_info["params"]
    m = GaussianHMMDiag(int(cfg["n_states"]))
    m.startprob_, m.transmat_ = np.array(p["startprob"]), np.array(p["transmat"])
    m.means_, m.vars_ = np.array(p["means"]), np.array(p["vars"])
    mu = np.array([model_info["scaler"]["mean"][f] for f in feats])
    sd = np.array([model_info["scaler"]["std"][f] for f in feats])
    s0 = first_trainable_index(feat, cfg)
    Xs = _standardize(feat[feats].to_numpy(float)[s0:], mu, sd, cfg["z_clip"])
    sm = _to_classes(m.smooth_proba(Xs), int(cfg["n_states"])).argmax(axis=1)
    fi = _to_classes(m.filter_proba(Xs), int(cfg["n_states"])).argmax(axis=1)
    idx = feat.index[s0:]
    mask = idx.isin(wf.index)
    out["filtered_vs_smoothed_agreement"] = float((sm[mask] == fi[mask]).mean()) if mask.any() else None

    # (e) KNN neighbours share the regime of the query day more often than chance?
    agree, base = [], float((daily["regime_code"].value_counts(normalize=True) ** 2).sum())
    for dt in wf.index[::knn_every]:
        try:
            nb, _ = similar_periods(feat, daily, dt, cfg, exclude_days=30)
        except ValueError:
            continue
        agree.append(float(nb["regime_code"].eq(daily.at[dt, "regime_code"]).mean()))
    out["knn_regime_agreement"] = {"mean": float(np.mean(agree)) if agree else None,
                                   "random_baseline": base, "samples": len(agree)}
    return out


# ============================================================== 6. current card
def current_state(daily, feat, cfg=None):
    cfg = cfg or make_config()
    last = daily.index.max()
    row = daily.loc[last]
    code = row["regime_code"]
    p = {"bull": float(row["p_bull"]), "sideways": float(row["p_sideways"]), "bear": float(row["p_bear"])}
    run = daily[daily["run_id"].eq(row["run_id"])]
    recent = daily.iloc[-252:]
    changes = int((recent["regime_code"] != recent["regime_code"].shift()).iloc[1:].sum())
    pending = None
    if row["raw_code"] != code and p[row["raw_code"]] >= cfg["label_threshold"]:
        n = 0
        for _, r in daily.iloc[::-1].iterrows():
            if r["raw_code"] == row["raw_code"] and r["p_" + row["raw_code"]] >= cfg["label_threshold"]:
                n += 1
            else:
                break
        pending = {"to_code": row["raw_code"], "to_name": NAME[row["raw_code"]], "consecutive_days": n,
                   "required_days": int(cfg["label_confirm_days"])}
    ind_ids = ["kospi_close", "kospi_ret_20d", "kospi_vol_20d", "kospi_dd_252d", "breadth_down_5d",
               "avg_corr_60d", "vix", "usdkrw_chg_20d", "us10y_chg_20d", "kr3y_chg_20d"]
    hist = feat.loc[:last]
    inds = []
    for fid in ind_ids:
        v = hist[fid].iloc[-1] if fid in hist else np.nan
        col = hist[fid].dropna()
        pct = float((col <= v).mean() * 100) if len(col) > 20 and np.isfinite(v) else None
        inds.append({"id": fid, "label": FEATURE_META[fid][0], "unit": FEATURE_META[fid][1],
                     "value": display_value(fid, v), "percentile": pct})
    return {"date": _d(last), "regime_code": code, "regime_name": NAME[code],
            "confidence": p[code], "probabilities": p, "raw_argmax_code": row["raw_code"],
            "days_in_regime": int(len(run)), "regime_since": _d(run.index.min()),
            "changes_last_252d": changes, "label_basis": row["label_basis"],
            "pending_switch": pending, "indicators": inds}


def display_value(fid, v):
    if v is None or not np.isfinite(v):
        return None
    tr = FEATURE_META.get(fid, (None, None, "raw"))[2]
    if tr == "expm1_pct":
        return float(np.expm1(v) * 100)
    if tr == "pct":
        return float(v * 100)
    return float(v)


# ============================================================== 7. snapshot JSON
def build_snapshot(feat, daily, runs, summary, trans, sim, sim_query, validation, model_info, bic_info,
                   quality, cfg=None, data_mode="fabric_gold", data_version=None, generated_at=None):
    cfg = cfg or make_config()
    generated_at = generated_at or datetime.now(timezone.utc)
    as_of = daily.index.max()
    trans_df, cnt, freq, rc = trans
    hist_rows = []
    for dt, r in daily.iterrows():
        hist_rows.append({"date": _d(dt), "kospi": _n(r["kospi_close"], 2), "regime": r["regime_code"],
                          "p_bull": _n(r["p_bull"], 4), "p_sideways": _n(r["p_sideways"], 4),
                          "p_bear": _n(r["p_bear"], 4), "raw": r["raw_code"],
                          "basis": "wf" if r["label_basis"] == "walk_forward" else "is"})
    knn_feats = sim_query.get("features_used", cfg["knn_features"])
    model_public = {k: v for k, v in model_info.items() if k not in ("params", "scaler", "state_means_scaled")}
    snap = {
        "schema": SNAPSHOT_SCHEMA, "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "snapshot_version": generated_at.strftime("%Y%m%dT%H%M%SZ"),
        "generated_at": generated_at.isoformat(), "as_of": _d(as_of),
        "data_mode": data_mode, "core_version": CORE_VERSION,
        "data_version": data_version or {},
        "notice": NOTICE,
        "regimes": REGIMES,
        "current": current_state(daily, feat, cfg),
        "history": hist_rows,
        "runs": [{"run_id": int(r.run_id), "regime_code": r.regime_code, "regime_name": r.regime_name,
                  "start": _d(r.start), "end": _d(r.end), "days": int(r.days),
                  "kospi_change_pct": _n(r.kospi_change_pct, 2), "label_basis": r.label_basis,
                  "is_current": bool(r.is_current)} for r in runs.itertuples()],
        "summary": [{k: (_n(v, 4) if isinstance(v, float) else v) for k, v in row.items()}
                    for row in summary.to_dict("records")],
        "transitions": {"order": CODES, "daily_counts": cnt.tolist(),
                        "daily_frequency": [[_n(x, 6) for x in row] for row in freq],
                        "run_transition_counts": rc.tolist()},
        "similar": {
            "asof": _d(sim_query["asof"]), "k": int(len(sim)),
            "method": "표준화한 시장 상태 피처의 유클리디안 거리. 기준일 직전 {}일은 제외하고, 이웃끼리 {}일 이상 떨어진 날짜만 고릅니다. 이후 수익률은 계산하지 않습니다.".format(cfg["knn_exclude_recent_days"], cfg["knn_min_gap_days"]),
            "features": [{"id": f, "label": FEATURE_META[f][0]} for f in knn_feats],
            "features_dropped": [{"id": f, "label": FEATURE_META[f][0]} for f in sim_query.get("features_dropped", [])],
            "query_z": {f: _n(sim_query["z_" + f], 3) for f in knn_feats},
            "neighbors": [{"rank": int(r["rank"]), "date": _d(r["similar_date"]), "distance": _n(r["distance"], 3),
                           "regime_code": r["regime_code"], "regime_name": r["regime_name"],
                           "regime_run_days": int(r["regime_run_days"]), "label_basis": r["label_basis"],
                           "z": {f: _n(r["z_" + f], 3) for f in knn_feats}} for _, r in sim.iterrows()],
        },
        "validation": _clean(validation),
        "model": _clean({**model_public, "bic_selection": bic_info, "core_version": CORE_VERSION}),
        "quality": _clean(quality),
    }
    return _clean(snap)


def snapshot_bytes(snap):
    """Canonical UTF-8 JSON + sha256 (used as payload_sha256 in PostgreSQL / certificate)."""
    b = json.dumps(snap, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return b, hashlib.sha256(b).hexdigest()


# ============================================================== 8. one-call runner
def run_all(gold, eligibility=None, cfg=None, data_mode="fabric_gold", data_version=None, log=print):
    cfg = cfg or make_config()
    feat, quality = build_features(gold, eligibility, cfg)
    log("features", feat.shape, quality["first_date"], "→", quality["last_date"])
    bic = select_n_states(feat, cfg)
    log("BIC", bic["table"], "best", bic["bic_best"], "used", bic["used"])
    daily, model_info = walk_forward_regimes(feat, cfg)
    log("regimes", daily["regime_code"].value_counts().to_dict())
    runs = build_runs(daily, feat)
    summary = regime_summary(daily, feat, runs)
    trans = transition_tables(daily, runs)
    sim, sim_query = similar_periods(feat, daily, None, cfg)
    validation = validate(feat, daily, model_info, cfg)
    log("validation", json.dumps(_clean({k: validation[k] for k in ("events", "silhouette", "stability")}), ensure_ascii=False)[:600])
    quality["warnings"] = quality_warnings(bic, quality)
    snap = build_snapshot(feat, daily, runs, summary, trans, sim, sim_query, validation, model_info, bic,
                          quality, cfg, data_mode, data_version)
    return {"features": feat, "daily": daily, "runs": runs, "summary": summary, "transitions": trans[0],
            "similar": sim, "validation": validation, "model": model_info, "bic": bic,
            "quality": quality, "snapshot": snap}


def quality_warnings(bic, quality):
    w = []
    if bic["bic_best"] != bic["used"]:
        w.append(f"BIC 최적 상태 수({bic['bic_best']})와 사용 상태 수({bic['used']})가 다릅니다. 해석 가능성을 위해 3개 국면을 유지했습니다.")
    late = [a["asset_id"] for a in quality["assets"] if a["first_usable_date"] and a["first_usable_date"] > quality["first_date"]]
    if late:
        w.append("상장일이 늦어 초기 구간에 없는 종목: " + ", ".join(late))
    return w


def publish_checks(snap, gold_version=None, allow_synthetic=False):
    """Gate before a snapshot becomes `latest`. Returns a list of failure codes (empty = pass)."""
    fails = []
    c = snap.get("current") or {}
    p = c.get("probabilities") or {}
    if not p or any(p.get(k) is None for k in CODES) or abs(sum(p.values()) - 1.0) > 1e-3:
        fails.append("CURRENT_PROBABILITIES_INVALID")
    if c.get("regime_code") not in CODES:
        fails.append("CURRENT_REGIME_INVALID")
    if len(snap.get("history", [])) < 252:
        fails.append("HISTORY_TOO_SHORT")
    if (snap.get("validation") or {}).get("oos_days", 0) < 252:
        fails.append("OUT_OF_SAMPLE_TOO_SHORT")
    if not allow_synthetic and snap.get("data_mode") != "fabric_gold":
        fails.append("NOT_FABRIC_GOLD_DATA")
    if gold_version and gold_version.get("latest_gold_date") and snap.get("as_of") != gold_version["latest_gold_date"]:
        fails.append("AS_OF_NOT_GOLD_LATEST:" + str(snap.get("as_of")) + "!=" + str(gold_version["latest_gold_date"]))
    if len(snap.get("similar", {}).get("neighbors", [])) == 0:
        fails.append("SIMILAR_EMPTY")
    return fails


# ============================================================== helpers
def _d(x):
    if x is None or (isinstance(x, float) and math.isnan(x)) or x is pd.NaT:
        return None
    return pd.Timestamp(x).strftime("%Y-%m-%d")


def _n(x, nd=4):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return round(x, nd) if math.isfinite(x) else None


def _clean(o):
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating, float)):
        return _n(o, 6)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, (pd.Timestamp, datetime)):
        return _d(o)
    return o
