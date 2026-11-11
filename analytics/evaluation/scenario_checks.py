"""가상 충격과 극단 조건 점검. (analytics/README.md 11절)

    python analytics/evaluation/scenario_checks.py        # VS Code ▶ 실행도 같습니다
    -> analytics/outputs/scenario_checks/{shock_sweep.csv, state_sweep.csv, scenario_support.csv,
                                          coef_stability.csv, coef_stability_by_feature.csv, event_dependence.csv,
                                          scenario_summary.json}

이 모듈은 평가 구간(2023~)을 열지 않습니다. 학습/보정 구간으로 만든 모델만 사용합니다.
가상 충격에는 직접적인 정답이 없습니다. 그래서 오차나 정확도를 계산하지 않고, 모델이 어떻게 반응하는지와
그 반응을 얼마나 믿을 수 있는지(학습 범위, 계수 안정성, 특정 사건 의존도, 외삽)만 보여줍니다.
충격이 커지면 반드시 손실이 늘도록 강제하지 않습니다. 단조롭지 않으면 그대로 표시합니다.

확인 항목
  shock_sweep     상태를 고정하고 충격 하나씩만 바꿔 반응(중심값, 분포)과 삼성전자+현대차 50:50 포트폴리오 반응을 봅니다.
  state_sweep     충격을 고정하고 상태 변수 하나씩만 바꿔 반응이 어디서 오는지 봅니다.
  scenario_support  각 가상 충격이 학습 범위 안인지, 비슷하게 큰 충격이 학습에 몇 번 있었는지(외삽 위험).
  coef_stability  학습 기간을 시간순 구간으로 나눠 다시 학습했을 때 계수의 부호와 크기가 유지되는지.
  event_dependence 특정 사건 기간(예: 2008 금융위기)을 빼고 다시 학습했을 때 반응이 얼마나 달라지는지.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ANALYTICS_ROOT = HERE.parent
sys.path.insert(0, str(ANALYTICS_ROOT / 'src'))
import predict as P  # noqa: E402
from analyze import Analyzer  # noqa: E402
from distribution import ALPHA, INPUT_ORDER, SHOCK_ORDER, STATE_ORDER, VARIANTS, ScaledRidgeModel, with_scales  # noqa: E402
from splits import DEFAULT_SAMPLES, assign_splits, select_split  # noqa: E402

DEFAULT_OUT = ANALYTICS_ROOT / 'outputs/scenario_checks'
SHOCK_KEYS = list(P.SHOCK_KEYS)                         # usdkrw_pct, us10y_bp, wti_pct, vix_pt
SHOCK_COL = dict(P.SHOCK_KEYS)                          # 사용자 키 -> 샘플 열
PORTFOLIO = {'005930': 50_000_000, '005380': 50_000_000}
SCENARIOS = {                                           # 조합 시나리오(사용자 키, 지정하지 않은 충격은 0)
    'fx+2/rate+50': {'usdkrw_pct': 2, 'us10y_bp': 50}, 'fx+5/rate+100': {'usdkrw_pct': 5, 'us10y_bp': 100},
    'fx+10/rate+200': {'usdkrw_pct': 10, 'us10y_bp': 200}, 'fx-5/rate-100': {'usdkrw_pct': -5, 'us10y_bp': -100},
    'oil-20': {'wti_pct': -20}, 'vix+15': {'vix_pt': 15}, 'vix+40': {'vix_pt': 40},
    'stress: fx+5/rate+50/oil-15/vix+20': {'usdkrw_pct': 5, 'us10y_bp': 50, 'wti_pct': -15, 'vix_pt': 20}}
EVENTS = [{'id': 'gfc', 'name': '글로벌 금융위기', 'start': '2008-09-12', 'end': '2008-11-20'},
          {'id': 'covid', 'name': '코로나19 급락', 'start': '2020-02-19', 'end': '2020-03-19'},
          {'id': 'tightening', 'name': '2022 금리 인상·강달러', 'start': '2022-08-16', 'end': '2022-09-30'}]


# ---------------------------------------------------------------- 도우미
def latest_as_of(ms: pd.DataFrame, scale: pd.DataFrame) -> pd.Timestamp:
    ok = ms.dropna(subset=STATE_ORDER).merge(scale.dropna(), on='trading_date')
    return pd.Timestamp(ok['trading_date'].max())


def with_state(ms: pd.DataFrame, as_of, overrides: dict) -> pd.DataFrame:
    out = ms.copy()
    m = out['trading_date'] == pd.Timestamp(as_of)
    for k, v in overrides.items():
        out.loc[m, k] = v
    return out


def train_shock_table(train: pd.DataFrame) -> pd.DataFrame:
    return train[[SHOCK_COL[k] for k in SHOCK_KEYS]].dropna()


def pct_rank(series: np.ndarray, v: float) -> float:
    return float((np.asarray(series) <= v).mean())


def build_model(train: pd.DataFrame, cal: pd.DataFrame, variant: str = 'state_ridge', alpha: float = ALPHA) -> ScaledRidgeModel:
    v = VARIANTS[variant]
    return ScaledRidgeModel(alpha=alpha, input_columns=v['input_columns'], mode=v['mode']).fit(train).calibrate(cal)


def _predict(model, ms, af, scale, shocks, as_of, assets):
    long, quant, meta = P.predict(model, ms, af, scale, shocks, as_of=as_of, assets=assets, card={})
    return quant, meta


# ---------------------------------------------------------------- 지지 범위(외삽)
def support_table(train: pd.DataFrame, scenarios: dict = SCENARIOS) -> pd.DataFrame:
    st = train_shock_table(train)
    rows = []
    for name, sh in scenarios.items():
        mask = pd.Series(True, index=st.index)
        info = {'scenario': name}
        out_of_range = []
        for k in SHOCK_KEYS:
            col = SHOCK_COL[k]
            v = float(sh.get(k, 0.0))
            lo, hi = float(st[col].min()), float(st[col].max())
            info[f'{k}'] = v
            info[f'{k}_train_percentile'] = pct_rank(st[col].to_numpy(), v)
            if k in sh and v != 0:
                mask &= (st[col] >= v) if v > 0 else (st[col] <= v)
                if not lo <= v <= hi:
                    out_of_range.append(k)
        specified = [k for k in sh if sh[k] != 0]
        info['train_rows_at_least_as_extreme_jointly'] = int(mask.sum()) if specified else None
        info['train_rows'] = int(len(st))
        info['out_of_train_range'] = ';'.join(out_of_range)
        info['extrapolation'] = bool(out_of_range)
        info['thin_support_lt30'] = bool(specified and int(mask.sum()) < 30)
        rows.append(info)
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- 상태 고정, 충격만 변경
def shock_sweep(model, ms, af, scale, train, as_of, assets=None, holdings=PORTFOLIO) -> pd.DataFrame:
    st = train_shock_table(train)
    an = Analyzer(model, {}, scale, ms, af, None)
    rows = []
    for k in SHOCK_KEYS:
        col = SHOCK_COL[k]
        s = st[col].to_numpy()
        grid = sorted({float(np.quantile(s, q)) for q in [0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99]}
                      | {float(s.min()), float(s.max()), 0.0, 1.5 * float(s.min()), 1.5 * float(s.max())})
        for v in grid:
            quant, meta = _predict(model, ms, af, scale, {k: v}, as_of, assets)
            port = an.analyze(dict(holdings), {k: v}, as_of=as_of)['model_estimate']
            for _, q in quant.iterrows():
                rows.append({'shock': k, 'value': v, 'train_percentile': pct_rank(s, v),
                             'in_train_range': bool(s.min() <= v <= s.max()), 'scope': 'asset', 'asset_id': q['asset_id'],
                             'center_pct': q['center_simple_return_pct'], 'q05_pct': q['q05'], 'median_pct': q['q50'], 'q95_pct': q['q95']})
            rows.append({'shock': k, 'value': v, 'train_percentile': pct_rank(s, v), 'in_train_range': bool(s.min() <= v <= s.max()),
                         'scope': 'portfolio', 'asset_id': '+'.join(holdings), 'median_pnl_krw': port['median_pnl_krw'],
                         'var95_krw': port['var95_krw'], 'es95_krw': port['es95_krw'], 'p05_pnl_krw': port['pnl_band_krw']['p05'],
                         'p95_pnl_krw': port['pnl_band_krw']['p95']})
    return pd.DataFrame(rows)


def monotonicity(sweep: pd.DataFrame) -> pd.DataFrame:
    """충격 값이 커질 때 중심 반응이 한 방향으로만 움직이는지. 강제하지 않고 표시만 합니다."""
    a = sweep[sweep['scope'] == 'asset']
    rows = []
    for (shock, aid), g in a.groupby(['shock', 'asset_id']):
        c = g.sort_values('value')['center_pct'].to_numpy()
        d = np.diff(c)
        rows.append({'shock': shock, 'asset_id': aid, 'center_at_min': float(c[0]), 'center_at_max': float(c[-1]),
                     'monotone_up': bool((d >= -1e-9).all()), 'monotone_down': bool((d <= 1e-9).all()),
                     'direction_changes': int((np.diff(np.sign(d[np.abs(d) > 1e-9])) != 0).sum())})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- 충격 고정, 상태만 변경
def state_sweep(model, ms, af, scale, train, as_of, shocks=None, assets=None) -> pd.DataFrame:
    shocks = shocks or SCENARIOS['fx+5/rate+100']
    base = ms.loc[ms['trading_date'] == pd.Timestamp(as_of)].iloc[0]
    rows = []
    for s in STATE_ORDER:
        vals = train[s].dropna().to_numpy()
        for q in [0.05, 0.25, 0.5, 0.75, 0.95]:
            v = float(np.quantile(vals, q))
            quant, _ = _predict(model, with_state(ms, as_of, {s: v}), af, scale, shocks, as_of, assets)
            for _, r in quant.iterrows():
                rows.append({'state': s, 'train_quantile': q, 'value': v, 'current_value': float(base[s]),
                             'asset_id': r['asset_id'], 'center_pct': r['center_simple_return_pct'],
                             'q05_pct': r['q05'], 'q95_pct': r['q95']})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- 계수 안정성
def coef_stability(train: pd.DataFrame, variant: str = 'state_ridge', blocks: int = 4, alpha: float = ALPHA,
                   min_rows: int = 100) -> tuple[pd.DataFrame, pd.DataFrame]:
    """종목별 표준화 계수를 전체 학습과 시간순 구간별 학습에서 비교합니다."""
    v = VARIANTS[variant]
    cols = v['input_columns']
    need = cols + ['scale_kospi', 'asset_scale', 'y_log_return_5d']
    d = train.dropna(subset=need).sort_values('trading_date')
    edges = d['trading_date'].quantile(np.linspace(0, 1, blocks + 1)).to_numpy()
    full = ScaledRidgeModel(alpha=alpha, input_columns=cols).fit(d)
    rows = []
    for b in range(blocks):
        hi = edges[b + 1]
        part = d[(d['trading_date'] >= edges[b]) & ((d['trading_date'] < hi) if b < blocks - 1 else (d['trading_date'] <= hi))]
        mb = ScaledRidgeModel(alpha=alpha, input_columns=cols).fit(part[part.groupby('asset_id')['asset_id'].transform('size') >= min_rows])
        for aid, model in mb.models.items():
            cf = full.models[aid][-1].coef_
            cb = model[-1].coef_
            for j, f in enumerate(cols):
                rows.append({'asset_id': aid, 'feature': f, 'block': b + 1, 'block_start': str(pd.Timestamp(edges[b]))[:10],
                             'block_end': str(pd.Timestamp(hi))[:10], 'coef_full': float(cf[j]), 'coef_block': float(cb[j]),
                             'same_sign': bool(np.sign(cf[j]) == np.sign(cb[j]))})
    t = pd.DataFrame(rows)
    by = (t.groupby('feature', sort=False)
          .agg(fits=('same_sign', 'size'), same_sign_share=('same_sign', 'mean'), median_coef_full=('coef_full', 'median'),
               median_coef_block=('coef_block', 'median'), coef_block_std=('coef_block', 'std')).reset_index())
    by['median_abs_coef_full'] = by['feature'].map(t.assign(a=t['coef_full'].abs()).groupby('feature')['a'].median())
    by['unstable'] = (by['same_sign_share'] < 0.75)
    return t, by


# ---------------------------------------------------------------- 사건 의존도
def event_dependence(train, cal, ms, af, scale, as_of, scenarios=SCENARIOS, events=EVENTS, assets=None,
                     variant: str = 'state_ridge') -> pd.DataFrame:
    """사건 기간(그 기간에 시작했거나 정답이 걸친 행)을 빼고 다시 학습했을 때 시나리오 반응이 바뀌는 정도."""
    full = build_model(train, cal, variant)
    out = []
    for ev in events:
        s, e = pd.Timestamp(ev['start']), pd.Timestamp(ev['end'])
        hit = ((train['trading_date'] <= e) & (train['target_date'] >= s))
        removed = int(hit.sum())
        if removed == 0:
            out.append({'event': ev['id'], 'name': ev['name'], 'rows_removed_from_train': 0, 'note': '학습 구간에 해당 기간 없음'})
            continue
        m = build_model(train[~hit], cal, variant)
        for sname, sh in scenarios.items():
            a, _ = _predict(full, ms, af, scale, sh, as_of, assets)
            b, _ = _predict(m, ms, af, scale, sh, as_of, assets)
            ca, cb = a['center_simple_return_pct'].to_numpy(), b['center_simple_return_pct'].to_numpy()
            out.append({'event': ev['id'], 'name': ev['name'], 'rows_removed_from_train': removed, 'scenario': sname,
                        'assets': int(len(ca)), 'max_abs_change_pct': float(np.abs(ca - cb).max()),
                        'mean_abs_change_pct': float(np.abs(ca - cb).mean()),
                        'sign_flips': int(((np.sign(ca) != np.sign(cb)) & (np.abs(ca) > 0.05) & (np.abs(cb) > 0.05)).sum()),
                        'mean_response_full_pct': float(ca.mean()), 'mean_response_without_event_pct': float(cb.mean())})
    return pd.DataFrame(out)


# ---------------------------------------------------------------- 실행
def run_checks(samples, kospi_scale, market_state, asset_features, *, as_of=None, alpha=ALPHA) -> dict:
    a = assign_splits(samples)
    d = with_scales(samples, kospi_scale)
    train, cal = select_split(d, a, 'train'), select_split(d, a, 'calibration')
    model = build_model(train, cal, 'state_ridge', alpha)
    as_of = pd.Timestamp(as_of) if as_of is not None else latest_as_of(market_state, kospi_scale)
    assets = model.assets
    sweep = shock_sweep(model, market_state, asset_features, kospi_scale, train, as_of, assets)
    mono = monotonicity(sweep)
    support = support_table(train)
    ssweep = state_sweep(model, market_state, asset_features, kospi_scale, train, as_of, assets=assets)
    ct, cb = coef_stability(train, alpha=alpha)
    ed = event_dependence(train, cal, market_state, asset_features, kospi_scale, as_of, assets=assets)
    summary = {
        'meaning': '가상 충격에는 정답이 없어 오차를 계산하지 않음. 모델 반응과 신뢰 한계만 점검',
        'evaluation_split_used': False, 'as_of': str(as_of)[:10], 'alpha': alpha, 'assets': len(assets),
        'train_period': [str(train['trading_date'].min())[:10], str(train['trading_date'].max())[:10]],
        'shock_train_range': {k: [float(train_shock_table(train)[SHOCK_COL[k]].min()), float(train_shock_table(train)[SHOCK_COL[k]].max())]
                              for k in SHOCK_KEYS},
        'scenarios_with_extrapolation': support.loc[support['extrapolation'], 'scenario'].tolist(),
        'scenarios_with_thin_support': support.loc[support['thin_support_lt30'], 'scenario'].tolist(),
        'non_monotone_asset_shock_pairs': int((~(mono['monotone_up'] | mono['monotone_down'])).sum()),
        'asset_shock_pairs': int(len(mono)),
        'unstable_features': cb.loc[cb['unstable'], 'feature'].tolist(),
        'coef_same_sign_share_by_feature': {r['feature']: round(float(r['same_sign_share']), 3) for _, r in cb.iterrows()},
        'event_sign_flips_total': int(ed['sign_flips'].fillna(0).sum()) if 'sign_flips' in ed else 0,
        'notes': ['충격이 커질수록 손실이 커지도록 강제하지 않았습니다. 단조롭지 않은 경우는 monotonicity로 표시합니다.',
                  '학습 범위를 벗어난 충격(extrapolation)의 반응은 선형 모델의 연장선일 뿐 검증되지 않았습니다.',
                  '현재 종목 결과를 코스피 전체에 일반화하지 않습니다.']}
    return {'shock_sweep': sweep, 'monotonicity': mono, 'scenario_support': support, 'state_sweep': ssweep,
            'coef_stability': ct, 'coef_stability_by_feature': cb, 'event_dependence': ed, 'summary': summary}


def write_checks(res: dict, out_dir) -> dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = {}
    for k in ['shock_sweep', 'monotonicity', 'scenario_support', 'state_sweep', 'coef_stability', 'coef_stability_by_feature',
              'event_dependence']:
        paths[k] = out / f'{k}.csv'
        res[k].to_csv(paths[k], index=False, encoding='utf-8-sig')
    paths['summary'] = out / 'scenario_summary.json'
    paths['summary'].write_text(json.dumps(res['summary'], ensure_ascii=False, indent=2, default=str) + '\n', encoding='utf8')
    return {k: str(v) for k, v in paths.items()}


def main(argv=None):
    p = argparse.ArgumentParser(description='가상 충격과 극단 조건 점검')
    p.add_argument('--samples', default=str(DEFAULT_SAMPLES))
    p.add_argument('--gold', default=None)
    p.add_argument('--features-dir', default=str(P.FEATURE_DIR))
    p.add_argument('--out', default=str(DEFAULT_OUT))
    p.add_argument('--as-of', default=None)
    a = p.parse_args(argv)
    from load_gold import DEFAULT_SOURCE, load_gold
    from train import market_scale_from_gold
    fd = Path(a.features_dir)
    scale = market_scale_from_gold(load_gold(a.gold or DEFAULT_SOURCE))
    res = run_checks(pd.read_parquet(a.samples), scale, pd.read_parquet(fd / 'market_state.parquet'),
                     pd.read_parquet(fd / 'asset_features.parquet'), as_of=a.as_of)
    paths = write_checks(res, a.out)
    s = res['summary']
    print(json.dumps({k: s[k] for k in ['as_of', 'scenarios_with_extrapolation', 'scenarios_with_thin_support',
                                        'non_monotone_asset_shock_pairs', 'asset_shock_pairs', 'unstable_features',
                                        'coef_same_sign_share_by_feature', 'event_sign_flips_total']}, ensure_ascii=False, indent=2))
    print(json.dumps(paths, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
