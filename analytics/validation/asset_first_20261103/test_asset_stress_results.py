import pytest
try:
    from stresslab.asset_stress_results import apply_asset_returns
except ModuleNotFoundError:
    from asset_stress_results import apply_asset_returns


def result(ret,scenario='s'):
    return dict(point_return_pct=ret,market_state_id='m',scenario_id=scenario,horizon_days=5,
                q10=-20,q90=20)


def test_points_are_applied_to_holdings_not_marginal_intervals():
    r=apply_asset_returns({'005930':1_000_000,'005380':2_000_000},
                          {'005930':result(-10),'005380':result(5)})
    assert r['assets'][0]['scenario_pnl_krw']==-100_000
    assert r['scenario_pnl_krw']==0
    assert not any(k in r for k in ['q10','q90','var','es','portfolio_median'])


def test_mismatched_scenarios_and_missing_assets_are_rejected():
    with pytest.raises(ValueError):
        apply_asset_returns({'a':1,'b':1},{'a':result(1),'b':result(1,'other')})
    with pytest.raises(ValueError):
        apply_asset_returns({'a':1},{})
