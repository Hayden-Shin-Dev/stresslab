"""Presentation and arithmetic for the agreed sensitivity-scenario service."""
import numpy as np
from .core import SHOCKS

SCOPE = {
    'version':'sensitivity-scenario-1',
    'purpose':'종목별 학습 민감도에 사용자 충격을 적용한 가상 손익 비교',
    'calculation_kind':'model_based_hypothetical_scenario',
    'forecast_accuracy_approved':False,
    'causal_effect_verified':False,
    'probabilistic_loss_limit_provided':False,
    'holding_basis':'user_supplied_current_valuation_krw',
    'zero_shock_meaning':'level_unchanged_not_level_zero',
    'state_policy':'last_verified_confirmed_daily_state',
}

def attach_scope(result):
    result['service_scope']=dict(SCOPE)
    active=[s for s in SHOCKS if result['shocks'][s]!=0]
    total_holding=sum(r['holding_krw'] for r in result['assets'])
    losses=sum(max(-r['shock_incremental_pnl_krw'],0) for r in result['assets'])
    factors={s:sum(r['shock_contribution_pnl_krw'][s] for r in result['assets']) for s in SHOCKS}
    for r in result['assets']:
        sensitivities=r['sensitivities']
        outside=[s for s in active if sensitivities[s]['outside_observed_range']]
        unstable=[s for s in active if not sensitivities[s]['training_stable']]
        evidence_level=('no_shock' if not active else 'extrapolation' if outside else
                        'limited_evidence' if unstable or r['joint_support_nonoverlap_windows']<15 else
                        'training_stable_oos_limited')
        r['evidence_summary']={
            'level':evidence_level,'active_shocks':active,'extrapolated_shocks':outside,
            'unstable_shocks':unstable,'displayed_historical_windows':len(r['historical_examples']),
            'historical_examples_are_scenario_answers':False,
            'return_validation':r['return_validation'],
            'note':'학습 계수의 안정성과 실제 수익률 예측 성능은 별도입니다.',
        }
        r['comparison']={
            'baseline_return_pct':r['baseline_model_return_pct'],
            'scenario_return_pct':r['scenario_return_pct'],
            'change_pp':r['change_from_baseline_pp'],
            'baseline_pnl_krw':r['baseline_pnl_krw'],
            'scenario_pnl_krw':r['hypothetical_pnl_krw'],
            'incremental_pnl_krw':r['shock_incremental_pnl_krw'],
        }
        r['portfolio_weight_pct']=100*r['holding_krw']/total_holding
        r['share_of_gross_incremental_loss_pct']=(100*max(-r['shock_incremental_pnl_krw'],0)/losses if losses else None)
        np.testing.assert_allclose(r['baseline_pnl_krw']+r['shock_incremental_pnl_krw'],r['hypothetical_pnl_krw'],atol=1e-6)
        np.testing.assert_allclose(sum(r['shock_contribution_pnl_krw'].values()),r['shock_incremental_pnl_krw'],atol=1e-6)
    ranked=sorted(result['assets'],key=lambda r:(r['shock_incremental_pnl_krw'],r['asset_id']))
    adverse=[r for r in ranked if r['shock_incremental_pnl_krw']<0]
    negative_factors=[s for s in SHOCKS if factors[s]<0]
    summary={
        'total_holding_krw':total_holding,
        'baseline_pnl_krw':result['portfolio_baseline_pnl_krw'],
        'scenario_pnl_krw':result['portfolio_hypothetical_pnl_krw'],
        'incremental_pnl_krw':result['portfolio_shock_incremental_pnl_krw'],
        'scenario_return_pct':100*result['portfolio_hypothetical_pnl_krw']/total_holding,
        'change_pp':100*result['portfolio_shock_incremental_pnl_krw']/total_holding,
        'shock_contributions_krw':factors,
        'gross_incremental_loss_krw':losses,
        'largest_adverse_asset_id':adverse[0]['asset_id'] if adverse else None,
        'largest_adverse_shock':min(negative_factors,key=lambda s:factors[s]) if negative_factors else None,
        'asset_contributions':[dict(asset_id=r['asset_id'],name=r['name'],
            incremental_pnl_krw=r['shock_incremental_pnl_krw'],scenario_pnl_krw=r['hypothetical_pnl_krw'],
            share_of_gross_incremental_loss_pct=r['share_of_gross_incremental_loss_pct']) for r in ranked],
        'interpretation':'충격 전후 모델값의 차이입니다. 실제 인과효과나 미래 손익의 보장이 아닙니다.',
    }
    np.testing.assert_allclose(sum(factors.values()),summary['incremental_pnl_krw'],atol=1e-6)
    result['portfolio_summary']=summary
    return result
