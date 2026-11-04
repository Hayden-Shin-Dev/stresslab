"""Gold v1.1 adapter and conditional factor service. No cloud mutations."""
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler

MACRO = ['usdkrw', 'us_treasury_10y', 'wti', 'vix', 'korea_3y']
SHOCKS = ['fx_pct', 'us_rate_bp', 'wti_pct', 'vix_points']
STATE = ['market_trend20', 'market_vol20', 'fx_trend20', 'rate_level',
         'oil_level', 'vix_level', 'kr3y_level', 'kr3y_change20']
ASSET = ['asset_trend5', 'asset_trend20', 'asset_vol20', 'asset_vol60',
         'volume_ratio20', 'drawdown60']
SCHEMA = Path(__file__).resolve().parents[3] / 'contracts/daily/schema.json'


def validate(g, research=False):
    required = json.loads(SCHEMA.read_text(encoding='utf8'))['items']['required']
    if set(required) != set(g):
        raise ValueError('Gold columns differ from v1.1')
    if g.dataset_version.nunique() != 1 or g.duplicated(['trading_date', 'asset_id']).any():
        raise ValueError('Read exactly one dataset version without duplicate keys')
    if not g.asset_id.map(lambda x: isinstance(x, str)).all():
        raise ValueError('asset_id must be a string')
    if g.is_mock.isna().any() or not g.is_mock.eq(False).all():
        raise ValueError('Mock/unknown origin rows are not accepted')
    if not g.instrument_kind.eq('stock').all():
        raise ValueError('This engine accepts individual stocks only')
    if not g.price_basis.eq('adjusted').all():
        raise ValueError('Verified adjusted-price series is required')
    for col in ['kospi_close'] + MACRO:
        if g.groupby('trading_date')[col].nunique(dropna=False).gt(1).any():
            raise ValueError(f'Conflicting market values: {col}')
    missing_time = {c: int(g[c].isna().sum()) for c in required
                    if c.endswith('_available_at')}
    if any(missing_time.values()) and not research:
        raise ValueError('Publication timestamps unresolved; research mode only')
    # Do not invent publication dates. Production rows must be available at daily close.
    cutoff = pd.to_datetime(g.trading_date, utc=True) + pd.Timedelta(hours=6, minutes=30)
    for c in missing_time:
        ts = pd.to_datetime(g[c], utc=True, errors='coerce')
        if (ts.notna() & (ts > cutoff)).any():
            raise ValueError(f'{c} is later than the feature cutoff')
    return {'rows': len(g), 'assets': g.asset_id.nunique(),
            'dataset_version': str(g.dataset_version.iloc[0]),
            'missing_publication_times': missing_time,
            'publication_verified': not any(missing_time.values()),
            'research_mode': research}


def features(g):
    """Same frozen Gold features as prior research, without a portfolio target."""
    dates = pd.DatetimeIndex(sorted(pd.to_datetime(g.trading_date).unique()))
    frames = []
    for asset, z in g.groupby('asset_id'):
        z = z.copy().set_index(pd.to_datetime(z.trading_date)).reindex(dates)
        valid = z.quality_status.eq('valid') & z.close.gt(0) & z.volume.gt(0)
        close = z.close.where(valid)
        r = close.pct_change(fill_method=None) * 100
        mr = z.kospi_close.pct_change(fill_method=None) * 100
        x = pd.DataFrame({'date': dates, 'asset': asset}, index=dates)
        for n in [5, 20]:
            x[f'asset_trend{n}'] = close.pct_change(n, fill_method=None) * 100
        for n in [20, 60]:
            x[f'asset_vol{n}'] = r.rolling(n).std()
        x['volume_ratio20'] = z.volume / z.volume.rolling(20).mean()
        x['drawdown60'] = (close / close.rolling(60).max() - 1) * 100
        x['market_trend20'] = z.kospi_close.pct_change(20, fill_method=None) * 100
        x['market_vol20'] = mr.rolling(20).std()
        x['fx_trend20'] = z.usdkrw.pct_change(20, fill_method=None) * 100
        for a, b in zip(['rate_level', 'oil_level', 'vix_level', 'kr3y_level'], MACRO[1:]):
            x[a] = z[b]
        x['kr3y_change20'] = z.korea_3y.diff(20) * 100
        x['fx_pct'] = (z.usdkrw.shift(-5) / z.usdkrw - 1) * 100
        x['us_rate_bp'] = (z.us_treasury_10y.shift(-5) - z.us_treasury_10y) * 100
        x['wti_pct'] = ((z.wti.shift(-5) / z.wti - 1) * 100).where(z.wti.gt(0) & z.wti.shift(-5).gt(0))
        x['vix_points'] = z.vix.shift(-5) - z.vix
        x['target'] = ((close.shift(-5) / close - 1) * 100).where(valid.rolling(6).sum().shift(-5).eq(6))
        x['end_date'] = pd.Series(dates, index=dates).shift(-5)
        x['scale'] = np.sqrt((x.asset_vol20**2 + x.asset_vol60**2) / 2 * 5).clip(lower=.1)
        # Entire lookback must be usable; do not bridge suspended or quarantined prices.
        x.loc[~valid.rolling(61).sum().eq(61), 'scale'] = np.nan
        frames.append(x.reset_index(drop=True))
    return pd.concat(frames).replace([np.inf, -np.inf], np.nan).dropna(subset=STATE + ASSET + ['scale'])


def anchors(d):
    dates = sorted(d.date.unique())[::6]
    return d[d.date.isin(dates)].copy()


class Factor:
    def __init__(self, shocks=True):
        self.shocks = shocks

    def design(self, d, fit=False):
        x = d[STATE + ASSET].copy()
        if self.shocks:
            for s in SHOCKS:
                x[s] = d[s]
                for c in ['market_trend20', 'market_vol20']:
                    x[s + '__' + c] = d[s] * d[c]
        if fit:
            self.assets = sorted(d.asset.unique())
            self.columns = list(x)
            self.scaler = StandardScaler().fit(x)
        z = self.scaler.transform(x)
        one = np.eye(len(self.assets))[[self.assets.index(a) for a in d.asset]] / 10
        parts = [z, one]
        if self.shocks:
            sh = z[:, [self.columns.index(s) for s in SHOCKS]]
            parts.append((one[:, :, None] * sh[:, None, :]).reshape(len(d), -1))
        return np.column_stack(parts)

    def fit(self, d):
        weights = 1 / d.groupby('date').date.transform('size')
        self.model = Ridge(alpha=300).fit(self.design(d, True), d.target / d.scale,
                                         sample_weight=weights / weights.mean())
        return self

    def predict(self, d):
        return self.model.predict(self.design(d)) * d.scale.to_numpy()


def metrics(d):
    y, c, lo, hi = [d[k].to_numpy() for k in ['actual', 'center', 'lo', 'hi']]
    crash = y <= -5
    return dict(n=len(d), dates=d.date.nunique(), mae=float(abs(y-c).mean()),
                direction=float((np.sign(y)==np.sign(c)).mean()),
                coverage80=float(((y>=lo)&(y<=hi)).mean()), width80=float((hi-lo).mean()),
                interval_score=float((hi-lo+10*np.maximum(lo-y,0)+10*np.maximum(y-hi,0)).mean()),
                crash_n=int(crash.sum()), crash_mae=float(abs(y[crash]-c[crash]).mean()) if crash.any() else None,
                crash_lower_breach=float((y[crash]<lo[crash]).mean()) if crash.any() else None)


def market_search(history, state, limit=12):
    """Stage A has no shock argument and no shock-dependent ranking."""
    h = history.drop_duplicates('date').sort_values('date').copy()
    scale = (h[STATE].quantile(.75)-h[STATE].quantile(.25)).replace(0, 1)
    h['state_distance'] = ((h[STATE]-state[STATE].astype(float))/scale).pow(2).mean(axis=1)
    chosen = []
    for _, r in h.sort_values(['state_distance', 'date']).iterrows():
        if all(r.end_date < v.date or r.date > v.end_date for v in chosen):
            chosen.append(r)
        if len(chosen) == limit: break
    return pd.DataFrame(chosen)


def analyze(bundle, positions, shocks):
    if set(shocks) - set(SHOCKS): raise ValueError('Unknown shock')
    shock = {s: float(shocks.get(s, 0)) for s in SHOCKS}
    if not np.isfinite(list(shock.values())).all(): raise ValueError('Finite shocks required')
    if shock['fx_pct'] <= -100 or shock['wti_pct'] <= -100: raise ValueError('Relative change must exceed -100%')
    if not positions or len({p['asset_id'] for p in positions}) != len(positions): raise ValueError('Unique positions required')
    snap = bundle['snapshot']; model = bundle['model']; history = bundle['history']
    candidates = market_search(history, snap.iloc[0])
    mid, spread = bundle['shock_mid'], bundle['shock_iqr']
    candidates['shock_distance'] = ((candidates[SHOCKS]-pd.Series(shock))/spread).pow(2).mean(axis=1)
    # Stage A determines candidates. Stage B annotations never replace fitted coefficients.
    ranked = candidates.sort_values('shock_distance')
    results = []
    for p in positions:
        a = p['asset_id']; value = float(p['value_krw'])
        if not np.isfinite(value) or value <= 0: raise ValueError('Positive finite value required')
        x = snap[snap.asset==a].copy()
        if x.empty or a not in model.assets: raise ValueError(f'Unsupported asset: {a}')
        if x.vix_level.iloc[0] + shock['vix_points'] < 0: raise ValueError('Negative VIX level')
        zero = x.copy(); zero[SHOCKS] = 0; base = float(model.predict(zero)[0])
        for s in SHOCKS: x[s] = shock[s]
        center = float(model.predict(x)[0]); contributions = {}
        for s in SHOCKS:
            single = zero.copy(); single[s] = shock[s]
            contributions[s] = float(model.predict(single)[0]-base)
        np.testing.assert_allclose(base+sum(contributions.values()), center, atol=1e-8)
        lo, hi = center + np.asarray(bundle['q']) * float(x.scale.iloc[0])
        if not np.isfinite([center, lo, hi, center*value]).all(): raise ValueError('Numerical overflow')
        refs = history[history.asset==a]
        dist = ((refs[SHOCKS]-pd.Series(shock))/spread).pow(2).mean(axis=1)
        near = refs[dist<=1].sort_values('date'); independent=[]
        for r in near.itertuples():
            if not independent or r.date>independent[-1].end_date: independent.append(r)
        outside = [s for s in SHOCKS if not refs[s].min() <= shock[s] <= refs[s].max()]
        examples=[]
        for r in ranked.itertuples():
            z=refs[refs.date==r.date]
            if z.empty: continue
            row=z.iloc[0];examples.append(dict(date=str(r.date.date()),end=str(r.end_date.date()),
                observed_shocks={s:float(row[s]) for s in SHOCKS},actual_return_pct=float(row.target),
                replay_pnl_krw=float(value*row.target/100),shock_distance=float(r.shock_distance)))
        results.append(dict(asset_id=a, value_krw=value, baseline_model_pct=base,
            center_pct=center, change_from_zero_shocks_pp=center-base,
            statistical_contributions_pp=contributions, historical_residual_band_pct=[float(lo),float(hi)],
            hypothetical_pnl_krw=value*center/100, support=dict(outside_marginal=outside,
                similar_nonoverlapping_windows=len(independent), distance_rule='mean squared shock IQR distance <= 1; not a confidence score'),
            evidence=examples, validation=bundle['asset_metrics'].get(a),
            response_status='exploratory' if outside or len(independent)<30 else 'historical_support_not_probability_approval'))
    return dict(model_version=bundle['version'], dataset_version=bundle['audit']['dataset_version'],
        state_date=str(snap.date.iloc[0].date()), horizon_trading_days=5,
        input_shocks=shock, market_state={s:float(snap.iloc[0][s]) for s in STATE},
        market_candidates=[dict(date=str(r.date.date()),distance=float(r.state_distance)) for r in candidates.itertuples()],
        assets=results, total_hypothetical_pnl_krw=sum(r['hypothetical_pnl_krw'] for r in results),
        production_approved=False, publication_verified=bundle['audit']['publication_verified'],
        notices=['조건부 통계 추정이며 인과효과가 아닙니다.',
                 '네 충격의 0은 수준을 0으로 만드는 것이 아니라 변화 없음입니다.',
                 '검색 사례의 실제 반응과 모델 추정은 별도 근거입니다. 검색이 모델을 재학습시키지 않습니다.',
                 '종목별 구간을 합산한 포트폴리오 확률 구간은 제공하지 않습니다.',
                 '공표 시각과 반복 사용한 평가 기간의 한계가 남은 서비스 통합 후보입니다.'])
