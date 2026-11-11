"""Huber 계산 결과를 AI 토론 입력으로 변환한다."""
from __future__ import annotations
import hashlib
import json
import math
import numpy as np
import pandas as pd
from .model import FACTORS, predict
from .training import mature_training
from .intervals import CONTRACT, bounds
from .universe import NAMES

SHOCK_KEYS = ["shock_fx", "shock_rate", "shock_oil", "shock_vix"]


def contributions(frame, model):
    """4개 요인의 16개 조합을 계산한 정확한 Shapley 분해. 단위는 단순수익률 %p."""
    values = {}
    for mask in range(16):
        x = frame.copy()
        x[FACTORS] = frame[FACTORS].to_numpy() * np.array([bool(mask & (1 << i)) for i in range(4)])
        values[mask] = float(predict(x, model)["central_return"][0])
    result = {}
    for i, name in enumerate(SHOCK_KEYS):
        total = 0.
        for mask in range(16):
            if mask & (1 << i):
                continue
            k = mask.bit_count()
            weight = math.factorial(k) * math.factorial(3-k) / math.factorial(4)
            total += weight * (values[mask | (1 << i)] - values[mask])
        result[name] = total
    if not np.isclose(sum(result.values()), values[15]-values[0], atol=1e-10, rtol=1e-10):
        raise ValueError("기여도 합계 불일치")
    return result


def historical_examples(history, shock, as_of, horizon):
    h = history[(history.target_end < pd.Timestamp(as_of)) & history.horizon.eq(horizon)].copy()
    active = np.asarray(shock) != 0
    if h.empty or not active.any():
        return []
    floors = np.array([.25, 10., 2., 1.])
    tolerance = np.maximum(abs(shock)*.5, floors)
    diff = (h[FACTORS].to_numpy()-shock)/tolerance
    same_sign = (np.sign(h[FACTORS].to_numpy()[:, active]) == np.sign(np.asarray(shock)[active])).all(axis=1)
    matched = same_sign & (abs(diff[:, active]) <= 1).all(axis=1)
    h["distance"] = np.sqrt(np.mean(diff**2, axis=1))
    selected, occupied = [], []
    for r in h[matched].sort_values(["distance", "origin"]).itertuples():
        if any(r.origin <= end and r.target_end >= start for start, end in occupied):
            continue
        # 민철 2026-11-11 추가 (실제 과거 사례만 전달해야 하기 때문에 기준일 전에 끝난 비중복 사례만 선택했음.)
        selected.append({"start": str(r.origin.date()), "end": str(r.target_end.date()),
                         "actual_return_pct": float(r.target), "distance": float(r.distance),
                         "actual_shocks": {"shock_fx": float(100*np.expm1(r.fx_pct/100)),
                                           "shock_rate": float(r.us_rate_bp), "wti_usd": float(r.oil_usd),
                                           "shock_vix": float(r.vix_points)},
                         "shock_units": {"shock_fx": "%", "shock_rate": "bp", "wti_usd": "USD/bbl", "shock_vix": "pt"}})
        occupied.append((r.origin, r.target_end))
        if len(selected) == 2:
            break
    return selected


def scenario(features, packages, history, gold, request):
    horizon = request["horizon_trading_days"]
    if horizon not in [1, 5]:
        raise ValueError("분석 기간은 1 또는 5거래일")
    assets = request["asset_ids"]
    if not assets or len(assets) > 20 or len(set(assets)) != len(assets):
        raise ValueError("종목은 중복 없이 1~20개")
    package_map = {(p["model"]["asset_id"], p["model"]["horizon"]): p for p in packages}
    chosen = [package_map[(asset, horizon)] for asset in assets]
    dates = {p["as_of"] for p in chosen}
    if len(dates) != 1:
        raise ValueError("종목별 상태 날짜가 다름")
    as_of = next(iter(dates))
    raw_shocks = request["shocks"]
    if set(raw_shocks) != set(SHOCK_KEYS):
        raise ValueError("환율 %, 미국 10년 금리 bp, 유가 %, VIX pt 네 입력이 필요함")
    s = np.array([raw_shocks[k] for k in SHOCK_KEYS], dtype=float)
    if not np.isfinite(s).all() or s[0] <= -100 or s[2] <= -100:
        raise ValueError("유효하지 않은 충격")
    current = gold[pd.to_datetime(gold.trading_date).eq(pd.Timestamp(as_of))].set_index("asset_id")
    market = gold[["trading_date", "kospi_close", "usdkrw", "us_treasury_10y", "wti", "vix", "korea_3y"]].drop_duplicates().sort_values("trading_date")
    market = market[pd.to_datetime(market.trading_date) <= pd.Timestamp(as_of)].set_index("trading_date")
    log_returns = 100*np.log(market.kospi_close/market.kospi_close.shift())
    state_features = {"market_trend20": 100*(market.kospi_close/market.kospi_close.shift(20)-1).iloc[-1],
                      "market_vol20": log_returns.rolling(20).std().iloc[-1],
                      "fx_trend20": 100*(market.usdkrw/market.usdkrw.shift(20)-1).iloc[-1],
                      "rate_level": market.us_treasury_10y.iloc[-1], "oil_level": market.wti.iloc[-1],
                      "vix_level": market.vix.iloc[-1], "kr3y_level": market.korea_3y.iloc[-1],
                      "kr3y_change20": 100*market.korea_3y.diff(20).iloc[-1]}
    state_features = {k: float(v) if np.isfinite(v) else None for k, v in state_features.items()}
    oil = float(current.loc[assets[0], "wti"])
    if not np.isfinite(oil) or oil <= 0:
        raise ValueError("유가 비율 입력을 변환할 양수 기준 유가가 필요함")
    # 민철 2026-11-11 추가 (AI 입력 유가는 %이고 Huber는 달러 차이를 쓰기 때문에 기준 유가로 단위를 변환했음.)
    shock = np.array([100*np.log1p(s[0]/100), s[1], oil*s[2]/100, s[3]])
    if abs(s[0]) > 50 or abs(s[1]) > 500 or abs(shock[2]) > 150 or abs(s[3]) > 100:
        raise ValueError("기존 서비스 충격 입력 한도를 벗어남")
    if float(current.loc[assets[0], "vix"]) + s[3] < 0:
        raise ValueError("충격 이후 VIX는 음수가 될 수 없음")
    holdings = request.get("holdings_krw", {})
    if set(holdings)-set(assets) or any(not np.isfinite(v) or v < 0 for v in holdings.values()):
        raise ValueError("보유금액은 선택 종목의 유한한 0 이상 값이어야 함")
    records = []
    for asset, package in zip(assets, chosen):
        model = package["model"]
        if model["fit_origin"] > as_of:
            raise ValueError("미래 모델 사용 금지")
        own = features[features.asset_id.eq(asset) & features.horizon.eq(horizon)]
        x = own[own.origin.eq(pd.Timestamp(as_of)) & own.state_valid].copy()
        if len(x) != 1 or current.loc[asset, "quality_status"] != "valid":
            raise ValueError("종목의 최신 Gold 상태가 유효하지 않음")
        x[FACTORS] = np.tile(shock, (len(x), 1))
        out = predict(x, model)
        if package.get("interval_contract") != CONTRACT:
            raise ValueError("기존 구간 계약으로 만든 모델 패키지가 아님")
        # 민철 2026-11-11 수정 (응답 형식 때문에 계산이 바뀌면 안 되므로 검증된 구간 함수의 값을 그대로 전달함.)
        limits = bounds(out["central_return"], x.scale.to_numpy(), package["residuals_abs_scaled"])
        q = [float(limits[key][0]) for key in ["q05", "q10", "q90", "q95"]]
        train = mature_training(own, as_of)
        outside = [SHOCK_KEYS[i] for i in range(4) if shock[i] < train[FACTORS[i]].min() or shock[i] > train[FACTORS[i]].max()]
        holding = float(holdings.get(asset, 0))
        center = float(out["central_return"][0])
        rec = {"asset": asset, "name": request.get("asset_names", {}).get(asset, NAMES.get(asset, asset)),
               "conditional_center_return_pct": center,
               "zero_shock_center_pct": float(out["baseline_return"][0]),
               "scenario_difference_pp": float(out["shock_response"][0]),
               "model_contributions_pp": contributions(x, model),
               "model_q10_pct": float(q[1]), "model_q90_pct": float(q[2]),
               "model_q05_pct": float(q[0]), "model_q95_pct": float(q[3]),
               "conservative_lower_reference_pct": float(q[0]),
               "outside_training_marginal_range": outside,
               "input_features": state_features,
               "historical_examples": historical_examples(history[history.asset_id.eq(asset)], shock, as_of, horizon),
               "holding_value_krw": holding, "center_pnl_krw": holding*center/100,
               "conservative_lower_pnl_krw": holding*float(q[0])/100,
               "shock_increment_pnl_krw": holding*float(out["shock_response"][0])/100,
               "service_mode": "local_integration_candidate", "interval_contract": CONTRACT,
               "nominal_probability_approved": False,
               "joint_support_certified": False, "contributions_are_causal": False,
               "model_sha256": hashlib.sha256(json.dumps(model, sort_keys=True).encode()).hexdigest(),
               "interpretation": "수익률은 충격 조건의 대표값이며 확정 손실이 아님. scenario_difference는 추가 충격 0 대비 차이. 기여도는 모델 계산의 Shapley 분해. q05~q95는 기존 90% 목표 대칭 구간. q10~q90은 같은 오차 표본으로 추가한 80% 목표 대칭 구간이며 별도 성능 승인 전임. 필드명은 AI 계약을 따르며 비대칭 분포의 분위수 추정이 아님. 보수적 하단은 기존 90% 구간 하단. 충격은 원 관측일 자료를 기준으로 한 다음 거래일의 시나리오 변화이며 발표 상태 갱신량이나 5일 누적 충격이 아님. 과거 관측 충격은 사후 시나리오이고 실제 사전 입수값을 뜻하지 않음."}
        records.append(rec)
    return {"run_id": request["run_id"], "state_date": as_of, "horizon_trading_days": horizon,
            "schema_version": "huber-debate-v1", "shocks": dict(zip(SHOCK_KEYS, s.tolist())),
            "shock_units": dict(zip(SHOCK_KEYS, ["%", "bp", "%", "pt"])),
            "model_shocks": dict(zip(FACTORS, shock.tolist())), "wti_reference_usd": oil,
            "assets": records, "portfolio": {"holding_value_krw": sum(r["holding_value_krw"] for r in records),
                                               "center_pnl_krw": sum(r["center_pnl_krw"] for r in records)}}
