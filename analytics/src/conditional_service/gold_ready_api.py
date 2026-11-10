"""Local integration API. Reads trusted local model artifacts; never trains on requests."""
import os
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from .core import SHOCKS, STATE, market_search
from .gold_ready import read_gold, sha


class Position(BaseModel):
    model_config = ConfigDict(extra='forbid',allow_inf_nan=False)
    asset_id: str
    value_krw: float = Field(gt=0)


class Shocks(BaseModel):
    model_config = ConfigDict(extra='forbid',allow_inf_nan=False)
    fx_pct: float = Field(default=0,gt=-100)
    us_rate_bp: float = 0
    wti_pct: float = Field(default=0,gt=-100)
    vix_points: float = 0


class Request(BaseModel):
    model_config = ConfigDict(extra='forbid')
    positions: list[Position] = Field(min_length=1)
    shocks: Shocks = Field(default_factory=Shocks)


class Runtime:
    def __init__(self, artifact, gold, provenance=None, certificate=None):
        self.bundle = joblib.load(artifact)  # Only trusted locally generated joblib files.
        self.is_catboost = self.bundle.get('model_kind') == 'catboost'
        self.model_sha = sha(artifact)
        self.gold_sha = sha(gold)
        g, f, p = read_gold(gold,provenance,certificate)
        supported = set(self.bundle['assets'])
        if set(g.asset_id) != supported:
            raise ValueError('Gold universe differs from model support; explicit refit required')
        today = pd.Timestamp.now(tz='Asia/Seoul').tz_localize(None).normalize()
        # Confirmed daily state only; never use today's partial daily data.
        f = f[f.date<today]
        counts = f.groupby('date').asset.nunique()
        self.day = counts[counts.eq(len(supported))].index.max()
        if pd.isna(self.day):
            raise ValueError('No complete usable common Gold snapshot')
        self.snapshot = f[f.date.eq(self.day)].copy()
        self.provenance = p[p.date.eq(self.day)]
        self.history = f.dropna(subset=SHOCKS+['target','end_date','label_known_by'])
        cutoff = self.day.tz_localize('Asia/Seoul')+pd.Timedelta(hours=15,minutes=30)
        self.history = self.history[(self.history.end_date<self.day)&(self.history.label_known_by<=cutoff)]
        if self.history.empty:
            raise ValueError('No matured historical evidence')
        self.candidates = market_search(self.history,self.snapshot.iloc[0])
        self.source_last_day = pd.to_datetime(g.trading_date).max()
        self.certified_bounds = provenance is not None

    def info(self):
        age = (pd.Timestamp.now(tz='Asia/Seoul').date()-self.day.date()).days
        return dict(model_version=self.bundle['version'],model_sha256=self.model_sha,
            gold_sha256=self.gold_sha,source_gold_last_date=str(self.source_last_day.date()),
            market_basis_date=str(self.day.date()),model_training_label_end=self.bundle['training_label_end'],
            state_age_calendar_days=age,is_stale=age>3,latest_market_state_verified=False,
            freshness_policy='Calendar-age warning only; no claim of latest exchange session without calendar reconciliation',
            model_kind='catboost' if self.is_catboost else 'sector_ridge',
            market_state_in_B=self.is_catboost,
            coefficient_source='not_applicable_nonlinear' if self.is_catboost else 'sector_ridge',
            stock_specific_model=self.is_catboost,stock_specific_coefficients=False,
            contribution_method='exact_four_shock_shapley_relative_to_zero' if self.is_catboost else 'linear_coefficient_times_shock',
            selected_for_local_service=self.is_catboost,
            market_search_role='A supplies observed historical evidence; no similarity reweighting of B',
            interval_supported=False,production_promoted=False,
            macro_observations={r.source:dict(observation_date=str(r.observation_date.date()),
                known_by=r.known_by.isoformat(),available_at=None if self.certified_bounds else r.known_by.isoformat(),
                # 2026-11-09 13:00 KST 민철 수정 — 실제 수집 근거를 공식 공표 근거로 잘못 표시하지 않습니다.
                availability_precision=getattr(r,'availability_basis','conservative_official_date_bound') if self.certified_bounds else 'gold_available_at',
                source_ref=str(r.source_ref)) for r in self.provenance.itertuples()},
            validation=self.bundle['report'],evaluation_is_independent_blind=False)

    def analyze(self, request):
        ids = [p.asset_id for p in request.positions]
        if len(set(ids)) != len(ids):
            raise ValueError('Duplicate positions')
        if set(ids)-set(self.bundle['assets']):
            raise ValueError('Unsupported asset: '+','.join(sorted(set(ids)-set(self.bundle['assets']))))
        shocks = request.shocks.model_dump()
        if self.snapshot.vix_level.iloc[0]+shocks['vix_points']<0:
            raise ValueError('Scenario VIX level cannot be negative')
        model, reference = self.bundle['model'], self.bundle['training_reference']
        spread = (reference[SHOCKS].quantile(.75)-reference[SHOCKS].quantile(.25)).replace(0,1)
        joint_distance = ((reference[SHOCKS]-pd.Series(shocks))/spread).pow(2).mean(axis=1)
        min_joint = float(joint_distance.min())
        outside = [s for s in SHOCKS if not reference[s].min()<=shocks[s]<=reference[s].max()]
        results = []
        for position in request.positions:
            asset, value = position.asset_id, position.value_krw
            row = self.snapshot[self.snapshot.asset.eq(asset)].copy()
            zero = row.copy(); zero[SHOCKS] = 0.
            x = row.copy()
            for s in SHOCKS: x[s] = shocks[s]
            base, center = float(model.predict(zero)[0]), float(model.predict(x)[0])
            if self.is_catboost:
                # Nonlinear response has no fixed slope. Allocate interactions exactly
                # instead of fabricating Ridge-like coefficients or double counting.
                sensitivities = None
                contributions = model.contributions(row,shocks)
            else:
                sensitivities = {s:float(sum(model.slope_parts(row.iloc[0],s).values())) for s in SHOCKS}
                contributions = {s:sensitivities[s]*shocks[s] for s in SHOCKS}
            np.testing.assert_allclose(base+sum(contributions.values()),center,atol=1e-8)
            if not np.isfinite([base,center,value*center]).all():
                raise ValueError('Numerical overflow')
            examples = []
            stock_history = self.history[self.history.asset.eq(asset)].set_index('date')
            for candidate in self.candidates.itertuples():
                if candidate.date not in stock_history.index: continue
                h = stock_history.loc[candidate.date]
                examples.append(dict(date=str(candidate.date.date()),end_date=str(h.end_date.date()),
                    state_distance=float(candidate.state_distance),observed_shocks={s:float(h[s]) for s in SHOCKS},
                    observed_return_pct=float(h.target),historical_replay_pnl_krw=value*float(h.target)/100))
            stock_reference=reference[reference.asset.eq(asset)]
            stock_outside=[s for s in SHOCKS if not stock_reference[s].min()<=shocks[s]<=stock_reference[s].max()]
            stock_joint=float(((stock_reference[SHOCKS]-pd.Series(shocks))/spread).pow(2).mean(axis=1).min())
            unsupported=bool(stock_outside or stock_joint>1)
            change=center-base
            direction='unchanged' if abs(change)<1e-8 else ('decrease' if change<0 else 'increase')
            dominant=max(SHOCKS,key=lambda s:abs(contributions[s])) if abs(change)>1e-8 or any(abs(v)>1e-8 for v in contributions.values()) else None
            results.append(dict(asset_id=asset,name=self.bundle['names'][asset],value_krw=value,
                sector=self.bundle['sectors'][asset],coefficient_source='not_applicable_nonlinear' if self.is_catboost else 'sector_ridge',
                sensitivities_pp_per_input_unit=sensitivities,baseline_model_return_pct=base,
                shock_contributions_pp=contributions,change_from_zero_shocks_pp=center-base,
                conditional_return_pct=center,hypothetical_pnl_krw=value*center/100,
                shock_incremental_pnl_krw=value*(center-base)/100,
                historical_examples=examples,validation=self.bundle['validation'].get(asset),
                exploratory=unsupported,
                scenario_support=dict(outside_marginal=stock_outside,nearest_joint_iqr_squared_distance=stock_joint),
                insight=dict(model_change_direction=direction,change_from_reference_pp=change,
                    incremental_pnl_krw=value*change/100,largest_model_contribution_factor=dominant,
                    direction_evidence='Model response, not a verified future direction or isolated causal effect',
                    support_status='outside_historical_support' if unsupported else 'within_diagnostic_support_not_accuracy_guarantee'),
                evidence_level='Per-stock nonlinear model; model scenario contributions, not constant causal sensitivities' if self.is_catboost else 'Sector estimate; stock-specific sensitivity not validated'))
        return dict(**self.info(),horizon_trading_days=5,shocks=shocks,
            input_units=dict(fx_pct='percent USD/KRW change',us_rate_bp='US 10Y yield basis-point change',
                wti_pct='percent WTI change',vix_points='VIX index point change'),
            zero_means='No change from the observed level; not a zero absolute price or rate',
            market_state={s:float(self.snapshot.iloc[0][s]) for s in STATE},
            market_candidates=[dict(date=str(r.date.date()),end_date=str(r.end_date.date()),distance=float(r.state_distance)) for r in self.candidates.itertuples()],
            scenario_support=dict(outside_marginal=outside,nearest_joint_iqr_squared_distance=min_joint,
                diagnostic_only=True,not_a_confidence_probability=True),
            assets=results,portfolio_hypothetical_pnl_krw=sum(z['hypothetical_pnl_krw'] for z in results),
            portfolio_shock_incremental_pnl_krw=sum(z['shock_incremental_pnl_krw'] for z in results),
            explanation='Model scenario change, not a causal effect or guaranteed future return. Historical replay is separate evidence.')


def create_app(directory=None, gold=None, provenance=None, certificate=None):
    folder = Path(directory or os.environ['STRESSLAB_GOLD_BUNDLE'])
    gold = gold or os.environ.get('STRESSLAB_GOLD_FILE')
    provenance = provenance or os.environ.get('STRESSLAB_GOLD_PROVENANCE')
    certificate = certificate or os.environ.get('STRESSLAB_GOLD_CERTIFICATE')
    if bool(provenance) != bool(certificate):
        raise ValueError('Provenance and certificate must be supplied together')
    runtime = Runtime(folder/'model.joblib',gold or folder/'gold.parquet',
        provenance if gold else folder/'provenance.parquet',certificate if gold else folder/'certificate.json')
    app = FastAPI(title='StressLab Gold local integration')
    @app.get('/model-info')
    def info(): return runtime.info()
    @app.get('/support')
    def support():
        return dict(assets=[dict(asset_id=a,name=runtime.bundle['names'][a],sector=runtime.bundle['sectors'][a]) for a in runtime.bundle['assets']],shocks=SHOCKS)
    @app.post('/analyze')
    def analyze(request: Request):
        try: return runtime.analyze(request)
        except ValueError as exc: raise HTTPException(status_code=422,detail=str(exc)) from exc
    return app
