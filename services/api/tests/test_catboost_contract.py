"""Validate pure CatBoost price/period contracts without remote calls."""
import copy,math
import pytest
from fastapi import HTTPException
from catboost_bridge import validate_result,ENGINE

SHOCKS=dict(shock_usdkrw_pct=1.,shock_us10y_bp=25.,shock_wti_pct=0.,shock_vix_pt=0.)

def result(h):
    p=dict(asset_id='005930',horizon_days=h,base_close=100000.,point_log_return_pct=1.,
        point_simple_return_pct=100*math.expm1(.01),predicted_close=100000*math.exp(.01))
    for tag,lo,hi in [(80,-2.,3.),(90,-3.,4.)]:
        for side,r in [('lower',lo),('upper',hi)]:
            p[f'{side}_{tag}_log_return_pct']=r;p[f'{side}_{tag}_close']=100000*math.exp(r/100)
    return dict(model='catboost',engine_model=ENGINE,asset_id='005930',horizon_days=h,shocks=SHOCKS,
        research_only=True,scenario_inputs_are_assumptions=True,production_approval='NOT_APPROVED',
        price_basis='adjusted',currency='KRW',horizon_unit='trading_days',model_package_id='test-package',
        manifest_sha256='a'*64,snapshot_sha256='b'*64,as_of_trading_date='2026-11-24',dataset_version='test',prediction=p)

@pytest.mark.parametrize('h',[1,5,20])
def test_period_and_log_to_price_contract(h):
    good=result(h);validate_result(good,'005930',h,SHOCKS)
    for mutate in [lambda r:r.update(horizon_days=10),lambda r:r.update(shocks={}),
                   lambda r:r['prediction'].update(predicted_close=1),lambda r:r.update(snapshot_sha256=''),
                   lambda r:r.update(engine_model='huber_catboost_hybrid_conditional')]:
        bad=copy.deepcopy(good);mutate(bad)
        with pytest.raises(HTTPException):validate_result(bad,'005930',h,SHOCKS)
