"""공통 API가 계산한 값만 AI 담당자의 기존 근거 형식으로 옮깁니다."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone


def attach_context(result, snapshot_metadata, market_response, market_error=None):
    # 2026-11-12 민철 추가: 일별 ML 입력과 장중 설명 자료의 기준 시각을 분리합니다.
    # 장중 값을 일별 ML 입력에 주입하거나 모델값을 보정하지 않습니다.
    snapshot = (market_response or {}).get("snapshot")
    now = datetime.now(timezone.utc)
    observed = (snapshot or {}).get("as_of")
    age = None
    if observed:
        try:
            stamp = datetime.fromisoformat(observed.replace("Z", "+00:00"))
            if stamp.tzinfo is not None:
                age = (now - stamp).total_seconds()
        except (TypeError, ValueError):
            pass
    result["model_context"] = dict(snapshot_metadata)
    result["market_context"] = {
        "status": "unavailable" if snapshot is None else "observed_snapshot",
        "snapshot": snapshot,
        "snapshot_age_seconds": age,
        "freshness": "unverified" if age is None or age < 0 else "stale" if age > 120 else "recent",
        "applied_to_daily_ml": False,
        "error": market_error,
    }
    result["created_at"] = now.isoformat()
    # 응답 내용의 식별자이며, 영구 저장된 결과 ID는 아닙니다.
    digest = hashlib.sha256(json.dumps(result, sort_keys=True, ensure_ascii=False,
                                      allow_nan=False, separators=(",", ":")).encode()).hexdigest()
    result["analysis_id"] = "a-" + digest[:24]
    shocks = result["shocks"]
    assets = []
    for row in result["assets"]:
        assets.append({
            "asset": row["asset_id"],
            "holding_value_krw": row["holding_krw"],
            "conditional_center_return_pct": row["scenario_return_pct"],
            "zero_shock_center_pct": row["baseline_model_return_pct"],
            "scenario_difference_pp": row["change_from_baseline_pp"],
            "center_pnl_krw": row["hypothetical_pnl_krw"],
            "model_interval_90_return_pct": row["model_interval_90_return_pct"],
            "model_contributions_pp": None,
            "historical_examples": None,
            "service_mode": "research_only",
            "nominal_probability_approved": False,
            "joint_support_certified": False,
            "contributions_are_causal": False,
            "interpretation": "학습된 모델의 조건부 계산값입니다. 기준 시나리오와의 차이는 인과효과가 아닙니다. "
                              "90% 명목 구간은 보장된 손실 한도가 아니며 80% 구간으로 바꾸어 해석하지 않습니다. "
                              "충격별 기여도와 과거 유사 사례는 현재 모델 API에서 제공하지 않습니다.",
        })
    # 2026-11-12 민철 추가: 기존 evidence.build_bundle 입력과 필드/단위를 맞춥니다.
    # 저장·조회 경로가 연결되기 전에는 이 내용을 토론 큐에 자동 전송하지 않습니다.
    result["ai_context"] = {
        "contract_version": "stress-run-evidence-v1",
        "stress_run": {
            "run_id": result["analysis_id"],
            "state_date": snapshot_metadata.get("as_of_trading_date"),
            "horizon_trading_days": result["horizon_trading_days"],
            "shocks": {"shock_fx": shocks["fx_pct"], "shock_rate": shocks["us_rate_bp"],
                       "shock_oil": shocks["wti_pct"], "shock_vix": shocks["vix_points"]},
            "assets": assets,
            "portfolio": {"holding_value_krw": sum(a["holding_krw"] for a in result["assets"]),
                          "center_pnl_krw": result["portfolio_hypothetical_pnl_krw"]},
            "model_context": dict(snapshot_metadata),
        },
        "market_snapshot": snapshot,
    }
    result["ai_handoff"] = {
        "ready": False,
        "status": "evidence_prepared_not_delivered",
        "persisted": False,
        "reason": "공통 API 결과의 영구 저장·조회 경로와 토론 실행기의 결과 조회 연결이 아직 없습니다.",
    }
    return result
