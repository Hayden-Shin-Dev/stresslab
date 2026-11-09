"""Selected shock-aware sector Ridge. Prior artifacts/API remain unchanged."""
import hashlib
import json
import math
import os
from functools import lru_cache
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException
from .api import Request
from .core import STATE, SHOCKS, market_search
from .final_service import model_info as ridge_info
from .scenario_scope import attach_scope

ROOT = Path(os.environ.get('STRESSLAB_SELECTED_MODEL_DIR', 'reports/web_model_selection_20261105'))
app = FastAPI(title='StressLab selected shock-aware sector Ridge', version='2.0')


@lru_cache(maxsize=1)
def bundle():
    info = json.loads((ROOT/'selection.json').read_text(encoding='utf8'))
    path = ROOT/info['model_file']
    if hashlib.sha256(path.read_bytes()).hexdigest() != info['artifact_sha256']:
        raise HTTPException(503, 'Selected model checksum mismatch')
    return joblib.load(path), info


def explain(model, row, features, shocks):
    """Use the selected model's actual equation, never a surrogate coefficient."""
    if hasattr(model, 'sector_models'):
        zero=row.copy();zero[SHOCKS]=0
        scenario=row.copy();scenario[SHOCKS]=[shocks[s] for s in SHOCKS]
        baseline=float(model.predict(zero)[0]);center=float(model.predict(scenario)[0])
        effects={s:float(model.slope_parts(row.iloc[0],s)['shared_coefficient']*shocks[s]) for s in SHOCKS}
        np.testing.assert_allclose(sum(effects.values()),center-baseline,atol=1e-9)
        return baseline,center,effects
    # CatBoost comparison retains exact four-input Shapley, not Ridge coefficients.
    inputs = pd.concat([row]*16, ignore_index=True)
    for j,s in enumerate(SHOCKS):
        inputs[s] = [shocks[s] if mask & (1<<j) else 0. for mask in range(16)]
    values = model.predict(inputs[features].to_numpy())*float(row.scale.iloc[0])
    effect = {}
    for j,s in enumerate(SHOCKS):
        effect[s] = float(sum(math.factorial(mask.bit_count())*math.factorial(3-mask.bit_count())/24
            *(values[mask | (1<<j)]-values[mask]) for mask in range(16) if not mask & (1<<j)))
    np.testing.assert_allclose(sum(effect.values()), values[15]-values[0], atol=1e-9)
    return float(values[0]), float(values[15]), effect


@app.get('/support')
def support():
    b,_ = bundle()
    return dict(assets=[dict(asset_id=a,name=b['names'][a]) for a in sorted(b['models'])],
                accepted_shocks_for_all=SHOCKS, count=len(b['models']), model='sector_ridge')


@app.get('/model-info')
def model_info():
    b,info = bundle(); state = ridge_info()['data_status']
    assert state['model_basis_date'] == str(b['snapshot'].date.iloc[0].date())
    return dict(artifact={'sha256':info['artifact_sha256'], 'model':info['selected_model']},
        data_status=state, selection=info, model_name=info['display_name'],
        service_model_selected=True, production_approved=False,
        deployment_status='local_only', contribution_method=info['contribution_method'])


@app.post('/analyze')
def analyze(request: Request):
    b,info = bundle()
    ids=[p.asset_id for p in request.positions]
    if len(set(ids)) != len(ids): raise HTTPException(422, 'Duplicate assets')
    if any(a not in b['models'] for a in ids): raise HTTPException(422, 'Asset outside final 50-stock support')
    shocks = request.shocks.model_dump()
    snap = b['snapshot']; history = b['history']; reference=b['training_reference']
    if float(snap.vix_level.iloc[0])+shocks['vix_points'] < 0:
        raise HTTPException(422, 'Negative VIX level')
    candidates = market_search(history, snap.iloc[0])
    spread = (history[SHOCKS].quantile(.75)-history[SHOCKS].quantile(.25)).replace(0,1)
    rows=[]
    for p in request.positions:
        a=p.asset_id; holding=p.value_krw; row=snap[snap.asset.eq(a)].copy()
        baseline,center,effects=explain(b['models'][a],row,b['features'],shocks)
        fitted=b['models'][a]
        cohort_assets=fitted.assets
        ref_full=reference[reference.asset.isin(cohort_assets)&reference.asset.map(b['sectors']).eq(b['sectors'][a])]
        ref=ref_full.sort_values('date').drop_duplicates('date').iloc[::6]
        bounds={s:[float(ref_full[s].min()),float(ref_full[s].max())] for s in SHOCKS}
        # Joint support checks both pre-shock state and all four shock coordinates.
        cols=STATE+SHOCKS
        scale=(ref[cols].quantile(.75)-ref[cols].quantile(.25)).replace(0,1)
        query=row.iloc[0][cols].astype(float).copy()
        for s in SHOCKS:query[s]=shocks[s]
        distances=((ref[cols]-query)/scale).pow(2).mean(axis=1)
        joint_count=int((distances<=1).sum())
        details={}; warnings=[]; plateau=[]
        for s in SHOCKS:
            outside=not bounds[s][0]<=shocks[s]<=bounds[s][1]
            coefficient=float(fitted.slope_parts(row.iloc[0],s)['shared_coefficient'])
            coefficients=[float(models[a].slope_parts(row.iloc[0],s)['shared_coefficient']) for models in b['model_vintages'].values()]
            coefficient_agreement=float(np.mean(np.sign(coefficients)==np.sign(coefficient)))
            stable=bool(coefficient_agreement==1 and abs(coefficient)>1e-8)
            details[s]=dict(source='sector_shock_ridge',coefficient_pp_per_unit=coefficient,
                attribution_per_input_unit=effects[s]/shocks[s] if shocks[s] else None,
                training_stable=stable, vintage_direction_agreement=coefficient_agreement,
                stability_scope='Coefficient sign across four annual fits; descriptive, not causal confidence',
                observed_range=bounds[s], outside_observed_range=outside,
                economic_nonexposure_not_inferred=True)
            if shocks[s]:
                probe=row.copy();probe[SHOCKS]=[shocks[x] for x in SHOCKS];probe[s]=shocks[s]*1.2
                extended=float(fitted.predict(probe)[0])
                if abs(extended-center)<1e-10:plateau.append(s)
                if outside:warnings.append(s+': outside fitted shock range')
        if joint_count<15:warnings.append('Insufficient joint market-state and shock support')
        if plateau:warnings.append('No output change for 20% stronger input: '+', '.join(plateau))
        h=history[history.asset.eq(a)&history.date.isin(candidates.date)].copy()
        h['distance']=((h[SHOCKS]-pd.Series(shocks))/spread).pow(2).mean(axis=1)
        examples=[dict(date=str(r.date.date()),response_end_date=str(r.end_date.date()),
            observed_shocks={s:float(getattr(r,s)) for s in SHOCKS},actual_return_pct=float(r.target),
            replay_pnl_krw=float(holding*r.target/100),evidence_kind='historical_observation_not_user_scenario')
            for r in h.sort_values('distance').head(5).itertuples()]
        if not np.isfinite([baseline,center,holding*center/100]).all():
            raise HTTPException(422, 'Non-finite scenario output')
        rows.append(dict(asset_id=a,name=b['names'][a],holding_krw=holding,
            analysis_class='model_scenario',sensitivities=details,
            baseline_model_return_pct=baseline,scenario_return_pct=center,
            change_from_baseline_pp=center-baseline,contributions_pp=effects,
            hypothetical_pnl_krw=holding*center/100,baseline_pnl_krw=holding*baseline/100,
            shock_incremental_pnl_krw=holding*(center-baseline)/100,
            shock_contribution_pnl_krw={s:holding*v/100 for s,v in effects.items()},
            historical_examples=examples,return_validation=b['validation'][a],
            model_version=b['version'],warnings=warnings,joint_support_nonoverlap_windows=joint_count,
            coefficient_source='sector_proxy_not_individual_stock',sector=b['sectors'][a],training_cohort=b['routing'][a],
            saturation_shocks=plateau,contribution_method='actual_sector_ridge_equation',
            scenario_support='limited' if warnings else 'within_observed_support'))
    result=dict(api_version='2.0',model_name=info['display_name'],service_model_selected=True,
        model_artifact_sha256=info['artifact_sha256'],state_date=str(snap.date.iloc[0].date()),
        horizon_trading_days=5,shocks=shocks,assets=rows,market_candidates=[str(d.date()) for d in candidates.date],
        data_status=model_info()['data_status'],
        analysis_flow={'A':'State-only historical search, no reweighting of B',
                      'B':'Shock-aware sector Ridge; shared sector coefficients, no stock-specific or state-conditioned coefficients'},
        portfolio_hypothetical_pnl_krw=sum(r['hypothetical_pnl_krw'] for r in rows),
        portfolio_baseline_pnl_krw=sum(r['baseline_pnl_krw'] for r in rows),
        portfolio_shock_incremental_pnl_krw=sum(r['shock_incremental_pnl_krw'] for r in rows),
        portfolio_analysis_class='model_scenario',production_approved=False,publication_verified=True)
    result=attach_scope(result)
    result['service_scope']['version']='sector-ridge-scenario-2'
    result['service_scope']['purpose']='충격 반영 업종 Ridge의 계수로 충격 변화와 가상 손익 계산'
    for r in rows:
        r['evidence_summary']['note']='업종 공통 계수의 연도별 부호 안정성입니다. 종목 고유 민감도나 인과효과 검증은 아닙니다.'
    return result
