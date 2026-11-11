"""평가: 실제 충격 재구성 + 비교 실험. (analytics/README.md 11절)

    python analytics/evaluation/evaluate.py                    # VS Code ▶ 실행도 같습니다
    python analytics/evaluation/evaluate.py --record-exposure  # 평가 구간을 열람했다고 protocol.json에 기록
    -> analytics/outputs/evaluation/{eval_metrics.csv, eval_comparison.csv, eval_failures.csv,
                                     eval_failure_dates.csv, eval_summary.json}

이 평가는 평가 구간(2023~)의 실제 충격을 입력으로 넣고 종목 반응을 재구성한 "조건부 반응 재구성"입니다.
충격 발생 예측이나 인과 검증이 아닙니다. 가상 충격에는 정답이 없으므로 여기서 오차를 계산하지 않습니다(scenario_checks.py).

비교 모델 (모두 같은 (날짜, 종목)을 평가, 같은 train/calibration으로 학습)
  volatility        입력 없이 학습 중앙값 + 보정 잔차        (단순 변동성 기준)
  shock_only        충격 4개만
  state_ridge       일별 상태 6개 + 충격 4개                  (B 모델)
  state_ecos_ridge  위 + 국고채 3년(ECOS) 2개
지표(수익률은 일반 수익률 %): MAE, RMSE, 90% 구간 포함률과 폭, 구간 점수, 하위 5% 분위수(pinball) 손실,
  VaR 초과율, VaR을 넘은 날의 실제 손실과 모델 ES의 비율(1보다 크면 큰 손실을 과소평가)
범위: 종목 개별, 전체 종목 합산, 삼성전자 50% + 현대차 50% 포트폴리오(같은 날짜 공동 표본)
중복: 인접 날짜의 5거래일 구간은 겹칩니다. 행 수와 독립 블록 수를 함께 적고, 블록 단위 부트스트랩으로 차이의 불확실성을 보고합니다.

주의
  * 평가 구간은 한 번 열면 독립 블라인드가 아닙니다. 결과를 보고 모델을 고쳤다면 --record-exposure로 기록하세요.
  * 현재 종목(최대 18개) 결과를 코스피 전체에 일반화하지 않습니다.
  * 기존 ECOS 실험(18종목, 선정된 184개 시점)과는 같은 실험이 아닙니다. 여기서는 평가 구간의 모든 가능한 날짜를 씁니다.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ANALYTICS_ROOT = HERE.parent
sys.path.insert(0, str(ANALYTICS_ROOT / 'src'))
from distribution import ALPHA, MAX_DRAWS, VARIANTS, ScaledRidgeModel, _floor, with_scales  # noqa: E402
from splits import (DEFAULT_SAMPLES, PROTOCOL_PATH, assign_splits, evaluation_keys, keys_sha256,  # noqa: E402
                    mark_evaluation_exposed, select_split)
from targets import to_simple_return_pct  # noqa: E402

DEFAULT_OUT = ANALYTICS_ROOT / 'outputs/evaluation'
EVAL_VERSION = 'evaluation-v1.0'
SEED = 20261018
TAIL_PROB = 0.05
PORTFOLIO_ASSETS = ('005930', '005380')       # 삼성전자, 현대차 각 50%
PAIRS = [('shock_only', 'volatility'), ('state_ridge', 'volatility'), ('state_ridge', 'shock_only'),
         ('state_ecos_ridge', 'state_ridge')]
COMPARE_METRICS = ['abs_error', 'squared_error', 'interval_score', 'pinball05']


# ---------------------------------------------------------------- 표본 준비와 학습
def fit_variants(d: pd.DataFrame, a: pd.DataFrame, alpha: float = ALPHA, variants=None) -> dict:
    """같은 train, calibration 행으로 모든 변형을 학습/보정합니다. 평가 구간은 쓰지 않습니다."""
    variants = variants or list(VARIANTS)
    train, cal = select_split(d, a, 'train'), select_split(d, a, 'calibration')
    models = {}
    for name in variants:
        v = VARIANTS[name]
        models[name] = ScaledRidgeModel(alpha=alpha, input_columns=v['input_columns'], mode=v['mode']).fit(train).calibrate(cal)
    return models


def common_eval_rows(d: pd.DataFrame, a: pd.DataFrame, models: dict):
    """모든 변형이 평가할 수 있는 평가 구간의 같은 (날짜, 종목) 행. 반환: (행, 제외 집계)."""
    ev = select_split(d, a, 'evaluation')
    universe = len(ev)
    ok = pd.Series(True, index=ev.index)
    why = {}
    for name, m in models.items():
        has_model = ev['asset_id'].isin(m.models)
        has_input = ev[m.required_columns].notna().all(axis=1)
        why[f'{name}:no_model'] = int((~has_model).sum())
        why[f'{name}:missing_input_or_scale'] = int((has_model & ~has_input).sum())
        ok &= has_model & has_input
    rows = ev[ok].copy()
    blocks = a[['trading_date', 'asset_id', 'overlap_block']]
    rows = rows.merge(blocks, on=['trading_date', 'asset_id'], how='left', validate='one_to_one')
    rows = rows.sort_values(['asset_id', 'trading_date']).reset_index(drop=True)
    rows['first_in_block'] = ~rows.duplicated(['asset_id', 'overlap_block'])
    return rows, {'universe_rows': int(universe), 'evaluated_rows': int(len(rows)), 'dropped': why}


def _residual_sample(model: ScaledRidgeModel, assets) -> np.ndarray:
    """보정 잔차 행(요청 종목이 모두 있는 날짜). B 모델 draws와 같은 균등 간격 선택."""
    r = model.residuals[list(assets)].dropna().to_numpy()
    ids = np.linspace(0, len(r) - 1, min(model.max_draws, len(r))).astype(int)
    return r[ids]


def _draws_pct(model, g: pd.DataFrame, asset: str, resid_col: np.ndarray) -> np.ndarray:
    center = model.models[asset].predict(model.inputs(g))
    scale = _floor(g['asset_scale'].to_numpy())
    return to_simple_return_pct((center[:, None] + resid_col[None, :]) * scale[:, None])


def row_metrics(D: np.ndarray, actual: np.ndarray) -> pd.DataFrame:
    """D: (행, 표본) 일반 수익률 % 표본, actual: 실제 일반 수익률 %."""
    q05, med, q95 = np.quantile(D, [TAIL_PROB, 0.5, 0.95], axis=1)
    tail = int(math.ceil(TAIL_PROB * D.shape[1] - 1e-12))
    es05 = np.sort(D, axis=1)[:, :tail].mean(axis=1)             # portfolio.py와 같은 꼬리 정의
    width = q95 - q05
    breach = actual < q05
    return pd.DataFrame({
        'actual': actual, 'median': med, 'q05': q05, 'q95': q95, 'es05': es05, 'n_draws': D.shape[1],
        'abs_error': np.abs(actual - med), 'squared_error': (actual - med) ** 2,
        'covered': ((actual >= q05) & (actual <= q95)).astype(float), 'width': width,
        'interval_score': width + 20 * np.maximum(q05 - actual, 0) + 20 * np.maximum(actual - q95, 0),
        'pinball05': np.maximum(TAIL_PROB * (actual - q05), (TAIL_PROB - 1) * (actual - q05)),
        'breach': breach.astype(float), 'shortfall': np.maximum(q05 - actual, 0)})


def evaluate_rows(models: dict, rows: pd.DataFrame, portfolio_assets=PORTFOLIO_ASSETS) -> pd.DataFrame:
    """변형 x (종목 개별, 포트폴리오) 행 단위 지표."""
    out = []
    key = ['asset_id', 'trading_date']
    for name, m in models.items():
        for asset, g in rows.groupby('asset_id', sort=True):
            g = g.reset_index(drop=True)
            res = m.residuals[asset].dropna().to_numpy()
            res = res[np.linspace(0, len(res) - 1, min(m.max_draws, len(res))).astype(int)]
            D = _draws_pct(m, g, asset, res)
            y = to_simple_return_pct(g['y_log_return_5d'].to_numpy())
            r = row_metrics(D, y)
            r[['asset_id', 'trading_date', 'overlap_block', 'first_in_block']] = g[key + ['overlap_block', 'first_in_block']].to_numpy()
            r['scope'], r['variant'], r['asset_scale'] = 'asset', name, g['asset_scale'].to_numpy()
            out.append(r)
        pa = [a for a in portfolio_assets if a in m.models]
        if len(pa) == len(portfolio_assets) and len(pa) > 1:
            sub = rows[rows['asset_id'].isin(pa)]
            dates = sub.groupby('trading_date')['asset_id'].nunique()
            dates = dates[dates == len(pa)].index
            sub = sub[sub['trading_date'].isin(dates)].sort_values(['trading_date', 'asset_id'])
            joint = _residual_sample(m, pa)                           # (표본, 종목) 같은 날짜 잔차 행
            Dp, ya = 0, 0
            for i, asset in enumerate(pa):
                g = sub[sub['asset_id'] == asset].reset_index(drop=True)
                Dp = Dp + _draws_pct(m, g, asset, joint[:, i]) / len(pa)
                ya = ya + to_simple_return_pct(g['y_log_return_5d'].to_numpy()) / len(pa)
            g0 = sub[sub['asset_id'] == pa[0]].reset_index(drop=True)
            r = row_metrics(Dp, ya)
            r['asset_id'], r['trading_date'] = 'portfolio', g0['trading_date'].to_numpy()
            r['overlap_block'], r['first_in_block'] = g0['overlap_block'].to_numpy(), g0['first_in_block'].to_numpy()
            r['scope'], r['variant'] = 'portfolio', name
            r['asset_scale'] = np.nan
            out.append(r)
    return pd.concat(out, ignore_index=True)


# ---------------------------------------------------------------- 집계
def _agg(g: pd.DataFrame) -> dict:
    b = g['breach'] > 0
    obs_loss = float(-g.loc[b, 'actual'].mean()) if b.any() else np.nan
    est_loss = float(-g.loc[b, 'es05'].mean()) if b.any() else np.nan
    return {'rows': int(len(g)), 'dates': int(g['trading_date'].nunique()), 'blocks': int(g['overlap_block'].nunique()),
            'mae_pct': float(g['abs_error'].mean()), 'rmse_pct': float(np.sqrt(g['squared_error'].mean())),
            'coverage90': float(g['covered'].mean()), 'mean_width_pct': float(g['width'].mean()),
            'interval_score': float(g['interval_score'].mean()), 'pinball05': float(g['pinball05'].mean()),
            'var_breach_rate': float(g['breach'].mean()), 'breaches': int(b.sum()),
            'mean_shortfall_beyond_var_pct': float(g['shortfall'].mean()),
            'breach_observed_mean_loss_pct': obs_loss, 'breach_model_es_loss_pct': est_loss,
            'es_ratio_observed_over_model': (obs_loss / est_loss) if b.any() and est_loss > 0 else np.nan}


def metrics_table(r: pd.DataFrame, train_p80: pd.Series) -> pd.DataFrame:
    r = r.copy()
    r['high_vol'] = r['asset_scale'] > r['asset_id'].map(train_p80)
    rows = []
    for name, g in r.groupby('variant', sort=False):
        label = VARIANTS[name]['label']
        subsets = {'all': g, 'nonoverlap_first_in_block': g[g['first_in_block']]}
        for y, gy in g.groupby(g['trading_date'].dt.year):
            subsets[f'year={y}'] = gy
        scopes = {'portfolio': g[g['scope'] == 'portfolio'], 'pooled_assets': g[g['scope'] == 'asset']}
        pa = g[g['scope'] == 'asset']
        for aid, ga in pa.groupby('asset_id'):
            scopes[f'asset:{aid}'] = ga
        for sname, part in scopes.items():
            if part.empty:
                continue
            subs = dict(subsets) if sname == 'pooled_assets' else {'all': part, 'nonoverlap_first_in_block': part[part['first_in_block']]}
            if sname == 'pooled_assets':
                subs = {k: v[v['scope'] == 'asset'] for k, v in subsets.items()}
                subs['high_vol'], subs['normal_vol'] = part[part['high_vol']], part[~part['high_vol'].fillna(False)]
            if sname == 'portfolio':
                subs = {'all': part, 'nonoverlap_first_in_block': part[part['first_in_block']]}
                for y, gy in part.groupby(part['trading_date'].dt.year):
                    subs[f'year={y}'] = gy
            for sub, gg in subs.items():
                if len(gg):
                    rows.append({'variant': name, 'label': label, 'scope': sname, 'subset': sub, **_agg(gg)})
        # 종목별 평균(종목 수가 다른 영향을 줄임)
        per = [(_agg(ga)) for _, ga in pa.groupby('asset_id')]
        if per:
            macro = {k: float(np.nanmean([p[k] for p in per])) for k in per[0] if k not in ('rows', 'dates', 'blocks', 'breaches')}
            rows.append({'variant': name, 'label': label, 'scope': 'macro_mean_over_assets', 'subset': 'all',
                         'rows': int(sum(p['rows'] for p in per)), 'dates': int(pa['trading_date'].nunique()),
                         'blocks': int(pa['overlap_block'].nunique()), **macro})
    return pd.DataFrame(rows)


def compare_table(r: pd.DataFrame, n_boot: int = 2000, seed: int = SEED, pairs=PAIRS) -> pd.DataFrame:
    """같은 행에서 두 모델의 지표 차이(A - B, 음수면 A가 좋음). 블록 단위 부트스트랩 95% 구간."""
    rng = np.random.default_rng(seed)
    keys = ['scope', 'asset_id', 'trading_date']
    rows = []
    for scope in ['asset', 'portfolio']:
        base = r[r['scope'] == scope]
        for A, B in pairs:
            a, b = base[base['variant'] == A].set_index(keys), base[base['variant'] == B].set_index(keys)
            idx = a.index.intersection(b.index)
            if len(idx) == 0:
                continue
            a, b = a.loc[idx], b.loc[idx]
            blk = a['overlap_block'].to_numpy()
            ub, inv = np.unique(blk, return_inverse=True)
            cnt = np.bincount(inv).astype(float)
            for met in COMPARE_METRICS:
                diff = (a[met] - b[met]).to_numpy()
                s = np.bincount(inv, weights=diff)
                point = s.sum() / cnt.sum()
                draw = rng.integers(0, len(ub), size=(n_boot, len(ub)))
                boot = s[draw].sum(axis=1) / cnt[draw].sum(axis=1)
                rows.append({'scope': 'pooled_assets' if scope == 'asset' else 'portfolio', 'model_a': A, 'model_b': B,
                             'metric': met, 'rows': int(len(idx)), 'blocks': int(len(ub)),
                             'mean_diff_a_minus_b': float(point), 'ci95_lo': float(np.quantile(boot, 0.025)),
                             'ci95_hi': float(np.quantile(boot, 0.975)),
                             'baseline_mean': float(b[met].mean()), 'relative_change': float(point / b[met].mean()),
                             'blocks_where_a_better': float((s < 0).mean()),
                             'ci_excludes_zero': bool(np.quantile(boot, 0.025) > 0 or np.quantile(boot, 0.975) < 0)})
    return pd.DataFrame(rows)


def failure_tables(r: pd.DataFrame, variant: str = 'state_ridge', top: int = 30):
    """VaR을 크게 넘은 사례와, 여러 종목이 같은 날 함께 넘은 날짜. 사건 의존도(상위 날짜 기여)도 함께."""
    g = r[(r['variant'] == variant) & (r['scope'] == 'asset')]
    cases = (g[g['breach'] > 0].sort_values('shortfall', ascending=False).head(top)
             [['trading_date', 'asset_id', 'actual', 'q05', 'es05', 'shortfall']].reset_index(drop=True))
    by_date = g.groupby('trading_date').agg(assets=('asset_id', 'nunique'), breaches=('breach', 'sum'),
                                            mean_shortfall=('shortfall', 'mean'), total_shortfall=('shortfall', 'sum'))
    by_date['breach_share'] = by_date['breaches'] / by_date['assets']
    dates = by_date.sort_values('total_shortfall', ascending=False).head(top).reset_index()
    total = by_date['total_shortfall'].sum()
    blocks = g.groupby('overlap_block')['shortfall'].sum().sort_values(ascending=False)
    dependence = {'variant': variant, 'total_shortfall': float(total),
                  'top5_blocks_share_of_shortfall': float(blocks.head(5).sum() / total) if total > 0 else None,
                  'blocks_with_breach': int((blocks > 0).sum()), 'blocks': int(len(blocks))}
    return cases, dates, dependence


# ---------------------------------------------------------------- 전체 실행
def run_evaluation(samples: pd.DataFrame, kospi_scale: pd.DataFrame, *, alpha: float = ALPHA,
                   portfolio_assets=PORTFOLIO_ASSETS, n_boot: int = 2000, protocol: dict | None = None) -> dict:
    a = assign_splits(samples)
    d = with_scales(samples, kospi_scale)
    models = fit_variants(d, a, alpha)
    rows, counts = common_eval_rows(d, a, models)
    r = evaluate_rows(models, rows, portfolio_assets)
    train = select_split(d, a, 'train')
    p80 = train.groupby('asset_id')['asset_scale'].quantile(0.8)
    metrics = metrics_table(r, p80)
    comp = compare_table(r, n_boot)
    cases, fdates, dep = failure_tables(r)

    keys = evaluation_keys(a)
    used = rows[['trading_date', 'asset_id']]
    ev_assign = a[a['trading_date'] >= pd.Timestamp(a.loc[a['split'] == 'evaluation', 'trading_date'].min())]
    excl = ev_assign[ev_assign['split'] != 'evaluation']
    reasons = excl['split_reason'].str.split(';').explode().value_counts()
    summary = {
        'evaluation_version': EVAL_VERSION, 'created_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'meaning': '실제 충격을 사후 입력해 종목 반응을 재구성한 조건부 반응 평가. 충격 발생 예측이나 인과 검증이 아님',
        'variants': {k: VARIANTS[k]['label'] for k in models}, 'alpha': alpha, 'seed_for_bootstrap': SEED, 'bootstrap_resamples': n_boot,
        'period': [str(rows['trading_date'].min())[:10], str(rows['trading_date'].max())[:10]],
        'rows': counts, 'assets_evaluated': int(rows['asset_id'].nunique()),
        'assets_without_model': sorted(set(a['asset_id']) - set(models['state_ridge'].models)),
        'dates': int(rows['trading_date'].nunique()), 'independent_blocks': int(rows['overlap_block'].nunique()),
        'overlap_note': '인접 날짜의 5거래일 구간은 겹칩니다. 행 수는 독립 표본 수가 아닙니다. independent_blocks를 보세요.',
        'evaluation_period_non_evaluated_rows_by_reason': {k: int(v) for k, v in reasons.items()},
        'keys_sha256_universe': keys_sha256(keys), 'keys_sha256_evaluated': keys_sha256(used),
        'universe_matches_protocol': (None if protocol is None else
                                      protocol.get('evaluation_universe', {}).get('keys_sha256') == keys_sha256(keys)),
        'portfolio': {'assets': list(portfolio_assets), 'weights': 'equal, 시작 시점 기준'},
        'calibration': {v: m.card.get('calibration') for v, m in models.items()},
        'event_dependence': dep,
        'generalization': '이 결과는 Gold에 있는 종목에 한정됩니다. 코스피 전체로 일반화하지 않습니다.',
        'ecos_note': '기존 ECOS 실험(18종목, 선정 184개 시점, MAE 4.6578 -> 4.6344, 삼성전자+현대차 50% 포트폴리오는 오차 증가)과는 '
                     '표본이 달라 같은 실험이 아닙니다. ECOS 계약 추가는 성능 승인이 아닙니다.'}
    return {'models': models, 'row_metrics': r, 'metrics': metrics, 'comparison': comp, 'failure_cases': cases,
            'failure_dates': fdates, 'summary': summary, 'rows': rows}


def write_evaluation(res: dict, out_dir) -> dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = {'metrics': out / 'eval_metrics.csv', 'comparison': out / 'eval_comparison.csv',
             'failures': out / 'eval_failures.csv', 'failure_dates': out / 'eval_failure_dates.csv',
             'summary': out / 'eval_summary.json'}
    res['metrics'].to_csv(paths['metrics'], index=False, encoding='utf-8-sig')
    res['comparison'].to_csv(paths['comparison'], index=False, encoding='utf-8-sig')
    res['failure_cases'].to_csv(paths['failures'], index=False, encoding='utf-8-sig', date_format='%Y-%m-%d')
    res['failure_dates'].to_csv(paths['failure_dates'], index=False, encoding='utf-8-sig', date_format='%Y-%m-%d')
    paths['summary'].write_text(json.dumps(res['summary'], ensure_ascii=False, indent=2, default=str) + '\n', encoding='utf8')
    return {k: str(v) for k, v in paths.items()}


def main(argv=None):
    p = argparse.ArgumentParser(description='평가(실제 충격 재구성, 비교 실험)')
    p.add_argument('--samples', default=str(DEFAULT_SAMPLES))
    p.add_argument('--gold', default=None, help='Gold 원본 (생략하면 load_gold 기본 경로)')
    p.add_argument('--out', default=str(DEFAULT_OUT))
    p.add_argument('--alpha', type=float, default=ALPHA)
    p.add_argument('--bootstrap', type=int, default=2000)
    p.add_argument('--record-exposure', action='store_true', help='평가 구간 열람을 protocol.json에 기록')
    a = p.parse_args(argv)
    from load_gold import DEFAULT_SOURCE, load_gold
    from train import market_scale_from_gold
    samples = pd.read_parquet(a.samples)
    scale = market_scale_from_gold(load_gold(a.gold or DEFAULT_SOURCE))
    protocol = json.loads(Path(PROTOCOL_PATH).read_text(encoding='utf8')) if Path(PROTOCOL_PATH).exists() else None
    res = run_evaluation(samples, scale, alpha=a.alpha, n_boot=a.bootstrap, protocol=protocol)
    paths = write_evaluation(res, a.out)
    if a.record_exposure:
        if protocol is None:
            print('protocol.json이 없어 기록하지 못했습니다. splits.py를 먼저 실행하세요.')
        else:
            mark_evaluation_exposed('evaluation/evaluate.py 실행: 평가 구간 결과를 확인함')
            print('평가 구간 열람을 protocol.json에 기록했습니다.')
    else:
        print('주의: 평가 구간을 열람했습니다. 결과를 보고 모델을 바꿀 계획이면 --record-exposure로 기록하세요.')
    m = res['metrics']
    show = m[(m['scope'].isin(['pooled_assets', 'portfolio'])) & (m['subset'] == 'all')]
    print(show[['variant', 'scope', 'rows', 'blocks', 'mae_pct', 'rmse_pct', 'coverage90', 'mean_width_pct',
                'interval_score', 'var_breach_rate', 'es_ratio_observed_over_model']].round(3).to_string(index=False))
    print(json.dumps(paths, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
