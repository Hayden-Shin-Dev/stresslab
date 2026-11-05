"""근거 묶음(evidence bundle) 조립.

입력
  stress_run : Stress Engine 결과. assets[]는 scenario_examples.json의 종목 레코드 형식
               (analytics/validation/tail_reliability_20261103/scenario_examples.json).
               portfolio는 ML에서 추가 예정인 포트폴리오 블록(VaR/ES, ES 기여도, 분산 효과). 없으면 None.
  snapshot   : 시장 상태 스냅샷 (contracts/realtime market_state_snapshot v2). 없으면 None.

출력
  묶음 전체(dict). D_sources/S_sources에 ID(D1, S1 …)를 붙이고 역할별 범위(role_scope)를 표시합니다.
  묶음은 만든 뒤 바꾸지 않고, 같은 토론의 모든 발언이 같은 묶음을 봅니다.

숫자는 계산하지 않고 원본 값을 그대로 옮깁니다. (도구 API README: 별도 손익 계산 금지)
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Optional

ALL = ["macro", "market", "risk", "portfolio"]
MAX_ASSETS = 20          # 한 묶음에 넣을 종목 수 상한 (보유 금액 큰 순)
MAX_HISTORY_PER_ASSET = 2

SHOCK_UNITS = {"shock_fx": ("scenario_shock_usdkrw", "%"), "shock_rate": ("scenario_shock_us10y", "bp"),
               "shock_oil": ("scenario_shock_wti", "%"), "shock_vix": ("scenario_shock_vix", "pt")}
MACRO_FEATURES = {  # input_features 중 시장 공통 상태 (종목마다 같은 값)
    "market_trend20": "%", "market_vol20": "%", "fx_trend20": "%", "rate_level": "%",
    "oil_level": "USD/bbl", "vix_level": "pt", "kr3y_level": "%", "kr3y_change20": "bp",
}


# 모델이 본문에서 쓸 한국어 지표 이름. metric_id가 접두어로 시작하면 해당 이름을 씁니다.
LABELS = {
    "scenario_shock_usdkrw": "원/달러 환율 변화 가정",
    "scenario_shock_us10y": "미국 10년 금리 변화 가정",
    "scenario_shock_wti": "국제 유가(WTI) 변화 가정",
    "scenario_shock_vix": "미국 증시 불안 지수(VIX) 변화 가정",

    "model_service_mode": "모델 운영 상태",
    "model_nominal_probability_approved": "확률 해석 승인 여부",
    "model_joint_support_certified": "충격 조합 검증 여부",
    "model_contributions_are_causal": "기여도를 원인으로 해석해도 되는지 여부",

    "state_market_trend20": "시장 20일 흐름",
    "state_market_vol20": "시장 20일 변동 폭",
    "state_fx_trend20": "환율 20일 흐름",
    "state_rate_level": "미국 10년 금리 수준",
    "state_oil_level": "국제 유가(WTI) 수준",
    "state_vix_level": "미국 증시 불안 지수(VIX) 수준",
    "state_kr3y_level": "한국 3년 국채 금리",
    "state_kr3y_change20": "한국 3년 국채 금리 20일 변화",

    "conditional_center_return": "시나리오 예상 수익률",
    "zero_shock_center_return": "충격이 없을 때 예상 수익률",
    "scenario_difference": "충격으로 달라진 수익률",
    "model_contribution_shock_fx": "환율 충격 기여",
    "model_contribution_shock_rate": "금리 충격 기여",
    "model_contribution_shock_oil": "유가 충격 기여",
    "model_contribution_shock_vix": "미국 증시 불안 지수(VIX) 충격 기여",

    "model_q10_return": "하위 10% 예상 수익률",
    "model_q90_return": "상위 10% 예상 수익률",
    "conservative_lower_reference_return": "보수적으로 본 하단 참고 수익률",
    "outside_training_marginal_range": "학습 범위를 벗어난 충격",
    "historical_observed_return": "비슷한 과거 상황의 실제 수익률",

    "holding_value": "보유 금액",
    "center_pnl": "예상 손익",
    "conservative_lower_pnl": "보수적으로 본 하단 참고 손익",

    "portfolio_holding_value_krw": "전체 보유 금액",
    "portfolio_center_pnl_krw": "전체 예상 손익",
    "portfolio_var95_krw": "95% 기준 손실 한도(VaR)",
    "portfolio_es95_krw": "최악의 5% 상황에서 평균 손실",
    "portfolio_sum_standalone_es95_krw": "종목을 따로 봤을 때 최악 5% 평균 손실의 합",
    "portfolio_diversification_benefit_krw": "분산 투자로 줄어든 손실",
    "portfolio_diversification_benefit_pct": "분산 투자로 줄어든 손실 비율",
    "portfolio_es_contribution_krw": "최악 5% 평균 손실에 대한 종목별 기여",
    "portfolio_standalone_es95_krw": "해당 종목만 보유했을 때 평균 손실",

    "intraday_market_phase": "분석 시점의 장 상태",
    "intraday_valid_asset_count": "장중 분석된 종목 수",
    "intraday_universe": "장중 분석 대상 종목",
    "intraday_declining_ratio": "장중 최근 5분간 하락한 종목 비율",
    "intraday_mean_return_5m": "장중 최근 5분 평균 수익률",
    "intraday_mean_return_since_previous_close": "장중 전일 종가 대비 평균 수익률",
    "intraday_mean_return_since_open": "장중 오늘 시가 대비 평균 수익률",
    "intraday_mean_correlation_60m": "장중 최근 1시간 종목 간 움직임 유사도",
    "intraday_joint_down_ratio_60m": "장중 최근 1시간 중 대부분 종목이 함께 떨어진 시간 비율",
    "intraday_sector_mean_return_5m": "장중 업종 최근 5분 평균 수익률",
    "intraday_sector_mean_return_since_previous_close": "장중 업종 전일 종가 대비 수익률",
    "intraday_asset_return_since_previous_close": "장중 종목 전일 종가 대비 수익률",
    "intraday_asset_return_since_open": "장중 종목 오늘 시가 대비 수익률",
    "intraday_signal_": "장중 시장 경고 신호",
    "intraday_applied_to_daily_ml": "장중 정보를 일별 모델에 반영했는지 여부",
}


def label_for(metric_id: str) -> str:
    if metric_id in LABELS:
        return LABELS[metric_id]
    for key, name in LABELS.items():
        if key.endswith("_") and metric_id.startswith(key):
            return f"{name}({metric_id[len(key):]})"
    return metric_id


class _Builder:
    def __init__(self, as_of: str, horizon: str):
        self.d: list[dict] = []
        self.s: list[dict] = []
        self.as_of = as_of
        self.horizon = horizon

    def add_d(self, metric_id, value, unit, roles, record_id, asset=None, horizon=None, **extra):
        item = {
            "id": f"D{len(self.d) + 1}",
            "metric_id": metric_id,
            "label": label_for(metric_id),
            "value": value,
            "unit": unit,
            "horizon": horizon or self.horizon,
            "as_of": extra.pop("as_of", self.as_of),
            "quality": extra.pop("quality", "model_output"),
            "record_id": record_id,
            "role_scope": list(roles),
        }
        if asset:
            item["asset_id"], item["asset_name"] = asset
        item.update(extra)
        self.d.append(item)

    def add_s(self, doc_id, title, excerpt, roles, source_uri):
        self.s.append({"id": f"S{len(self.s) + 1}", "doc_id": doc_id, "title": title, "excerpt": excerpt,
                       "source_uri": source_uri, "role_scope": list(roles)})


def _holding(rec: dict) -> float:
    return float(rec.get("holding_value_krw") or rec.get("holding_krw_example") or 0)


def build_bundle(debate_id: str, stress_run: dict, snapshot: Optional[dict]) -> dict:
    run_id = stress_run["run_id"]
    assets = sorted(stress_run.get("assets", []), key=_holding, reverse=True)
    omitted = [a["asset"] for a in assets[MAX_ASSETS:]]
    assets = assets[:MAX_ASSETS]
    first = assets[0] if assets else {}
    b = _Builder(as_of=stress_run.get("state_date") or first.get("state_date", ""),
                 horizon=f"D+{stress_run.get('horizon_trading_days', 5)}")

    # ---- 공통: 시나리오 충격, 모델 상태 ------------------------------------
    shocks = stress_run.get("shocks") or first.get("shocks") or {}
    for key, (metric, unit) in SHOCK_UNITS.items():
        if key in shocks:
            b.add_d(metric, shocks[key], unit, ALL, f"{run_id}/shocks/{key}", horizon="scenario_assumption")
    for flag in ("service_mode", "nominal_probability_approved", "joint_support_certified", "contributions_are_causal"):
        if flag in first:
            b.add_d(f"model_{flag}", first[flag], "flag", ALL, f"{run_id}/model/{flag}", quality="model_metadata")

    # ---- 거시: 시장 공통 입력 상태 -----------------------------------------
    feats = first.get("input_features", {})
    for key, unit in MACRO_FEATURES.items():
        if key in feats:
            b.add_d(f"state_{key}", feats[key], unit, ["macro"], f"{run_id}/state/{key}",
                    horizon="state_at_t0", quality="observed_input")

    # ---- 종목별 -----------------------------------------------------------
    for rec in assets:
        asset = (rec["asset"], rec.get("name", rec["asset"]))
        rid = f"{run_id}/assets/{rec['asset']}"
        b.add_d("conditional_center_return", rec["conditional_center_return_pct"], "%", ALL, rid + "/center", asset)
        b.add_d("zero_shock_center_return", rec.get("zero_shock_center_pct"), "%", ["macro", "risk"], rid + "/zero", asset)
        b.add_d("scenario_difference", rec.get("scenario_difference_pp"), "%p", ["macro", "risk", "portfolio"], rid + "/diff", asset)
        for shock, v in (rec.get("model_contributions_pp") or {}).items():
            if v:  # 0인 충격 기여는 넣지 않음
                b.add_d(f"model_contribution_{shock}", v, "%p", ["macro", "risk", "portfolio"], f"{rid}/contrib/{shock}", asset)
        b.add_d("model_q10_return", rec.get("model_q10_pct"), "%", ["risk"], rid + "/q10", asset)
        b.add_d("model_q90_return", rec.get("model_q90_pct"), "%", ["risk"], rid + "/q90", asset)
        b.add_d("conservative_lower_reference_return", rec.get("conservative_lower_reference_pct"), "%",
                ["risk", "portfolio"], rid + "/guard", asset)
        out_range = rec.get("outside_training_marginal_range") or []
        b.add_d("outside_training_marginal_range", out_range, "list", ["macro", "risk"], rid + "/support", asset,
                quality="model_metadata")
        for i, h in enumerate((rec.get("historical_examples") or [])[:MAX_HISTORY_PER_ASSET]):
            b.add_d("historical_observed_return", h.get("actual_return_pct"), "%", ["risk"], f"{rid}/history/{i}",
                    asset, horizon=f"{h.get('start')}~{h.get('end')}", quality="observed_history",
                    observed_shocks=h.get("actual_shocks"))
        if _holding(rec):
            b.add_d("holding_value", _holding(rec), "KRW", ["portfolio"], rid + "/holding", asset, quality="user_input")
            b.add_d("center_pnl", rec.get("center_pnl_krw"), "KRW", ["portfolio"], rid + "/pnl", asset)
            b.add_d("conservative_lower_pnl", rec.get("conservative_lower_pnl_krw"), "KRW", ["portfolio", "risk"],
                    rid + "/guard_pnl", asset)

    # ---- 포트폴리오 블록 (ML 추가 예정) -----------------------------------
    pf = stress_run.get("portfolio")
    if pf:
        for key, unit in (("holding_value_krw", "KRW"), ("center_pnl_krw", "KRW"), ("var95_krw", "KRW"),
                          ("es95_krw", "KRW"), ("sum_standalone_es95_krw", "KRW"),
                          ("diversification_benefit_krw", "KRW"), ("diversification_benefit_pct", "%")):
            if key in pf:
                b.add_d(f"portfolio_{key}", pf[key], unit, ["portfolio", "risk"], f"{run_id}/portfolio/{key}")
        names = {a["asset"]: a.get("name", a["asset"]) for a in assets}
        for key in ("es_contribution_krw", "standalone_es95_krw"):
            for aid, v in (pf.get(key) or {}).items():
                b.add_d(f"portfolio_{key}", v, "KRW", ["portfolio", "risk"], f"{run_id}/portfolio/{key}/{aid}",
                        (aid, names.get(aid, aid)))

    if first.get("interpretation"):
        b.add_s("stress-run-interpretation", "스트레스 결과 해석 기준", first["interpretation"], ALL, f"stress-run:{run_id}")

    # ---- 장중 시장 상태 ---------------------------------------------------
    snap_id = None
    if snapshot:
        snap_id = snapshot["snapshot_id"]
        m = snapshot.get("market", {})
        q = snapshot.get("quality_status", "unknown")
        def add_m(metric, value, unit, roles=("market",), **kw):
            key = (kw.get("asset") or (None,))[0] or kw.get("sector_id")
            rid = f"{snap_id}/{metric}" + (f"/{key}" if key else "")
            b.add_d(f"intraday_{metric}", value, unit, roles, rid, horizon="intraday_snapshot",
                    as_of=snapshot["as_of"], quality=q, **kw)
        add_m("market_phase", snapshot.get("market_phase"), "label")
        add_m("valid_asset_count", f"{snapshot.get('valid_asset_count')}/{snapshot.get('expected_asset_count')}", "count")
        add_m("universe", snapshot.get("universe_id"), "label", whole_kospi=snapshot.get("whole_kospi"))
        add_m("declining_ratio", snapshot.get("declining_ratio"), "ratio")
        add_m("mean_return_5m", m.get("mean_return_5m_pct"), "%")
        add_m("mean_return_since_previous_close", m.get("mean_return_since_previous_close_pct"), "%",
              previous_close_coverage=m.get("previous_close_coverage"))
        add_m("mean_return_since_open", m.get("mean_return_since_open_pct"), "%")
        add_m("mean_correlation_60m", m.get("mean_correlation_60m"), "corr", ("market", "risk", "portfolio"))
        add_m("joint_down_ratio_60m", m.get("joint_down_ratio_60m"), "ratio", ("market", "risk", "portfolio"))
        for sec in snapshot.get("sectors", []):
            add_m("sector_mean_return_5m", sec.get("mean_return_5m_pct"), "%", sector_id=sec.get("sector_id"),
                  direction=sec.get("recent_direction"), declining_ratio=sec.get("declining_ratio"))
            add_m("sector_mean_return_since_previous_close", sec.get("mean_return_since_previous_close_pct"), "%",
                  sector_id=sec.get("sector_id"), previous_close_coverage=sec.get("previous_close_coverage"))
        # 근거 묶음에 들어간 종목(보유 종목)의 오늘 움직임: 일봉 시나리오 결과와 맞대어 보기 위함
        names = {a["asset"]: a.get("name", a["asset"]) for a in assets}
        for row in snapshot.get("assets", []):
            aid = row.get("asset_id")
            if aid in names:
                add_m("asset_return_since_previous_close", row.get("return_since_previous_close_pct"), "%",
                      ("market", "portfolio"), asset=(aid, names[aid]))
                add_m("asset_return_since_open", row.get("return_since_open_pct"), "%",
                      ("market", "portfolio"), asset=(aid, names[aid]))
        for sig in snapshot.get("signals", []):
            add_m(f"signal_{sig.get('kind')}", sig.get("triggered"), "flag", value_observed=sig.get("value"),
                  threshold=sig.get("threshold"), rule_status=sig.get("status"))
        add_m("applied_to_daily_ml", snapshot.get("applied_to_daily_ml"), "flag", ALL)
        for i, text in enumerate(snapshot.get("limitations", [])):
            b.add_s(f"market-state-limitation-{i}", "장중 시장 상태의 한계", text, ["market"], f"market-state:{snap_id}")

    core = {
        "debate_id": debate_id,
        "run_id": run_id,
        "snapshot_id": snap_id,
        "state_date": b.as_of,
        "model_sha256": first.get("model_sha256"),
        "omitted_assets": omitted,
        "D_sources": b.d,
        "S_sources": b.s,
    }
    digest = hashlib.sha256(json.dumps(core, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()
    core["evidence_bundle_id"] = "E-" + digest[:16]
    core["sha256"] = digest
    return core


def for_role(bundle: dict, role: str) -> tuple[list[dict], list[dict]]:
    """역할에게 보여줄 D/S 근거. role_scope는 모델 입력에서 뺍니다."""
    def strip(items):
        return [{k: v for k, v in it.items() if k != "role_scope"} for it in items if role in it["role_scope"]]
    return strip(bundle["D_sources"]), strip(bundle["S_sources"])


def ids_for_role(bundle: dict, role: str) -> set[str]:
    return {it["id"] for it in bundle["D_sources"] + bundle["S_sources"] if role in it["role_scope"]}
