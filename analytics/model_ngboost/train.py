"""Train and evaluate a conditional NGBoost stress model using the D/E protocol."""
from __future__ import annotations

import argparse
import json
import sys
from importlib.metadata import version
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from ngboost import NGBRegressor
from ngboost.distns import Normal
from ngboost.scores import LogScore
from scipy.stats import norm
from sklearn.tree import DecisionTreeRegressor

ANALYTICS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ANALYTICS / 'model_de'))
import common as C
from compare_models import SCENARIOS, block_bootstrap
from conformal import cqr_adjustment
from load_gold import DEFAULT_SOURCE, load_gold
from splits import keys_sha256
from splits import DEFAULT_CALIBRATION_START, DEFAULT_EVALUATION_START
from targets import SHOCK_FACTORS

MODEL_VERSION = 'ngboost-normal-v1'
KEYS = ['trading_date', 'asset_id']
MATCH_COLUMNS = ['target_date', 'y_actual', 'asset_scale', *C.SHOCK_ORDER]
LOSS_THRESHOLDS = (-5, -10)  # simple percentage return


def predict_distribution(package, frame):
    """Return per-asset marginal distributions and intervals in log-return %."""
    if frame.empty or not frame['asset_id'].isin(package['assets']).all():
        raise ValueError('예측할 종목이 없거나 학습 대상에 포함되지 않은 종목입니다.')
    x, scale = C.design(frame), C._floor(frame['asset_scale'].to_numpy(float))
    if not np.isfinite(x).all() or not np.isfinite(scale).all():
        raise ValueError('예측 입력과 변동성 척도는 유한해야 합니다.')
    params = package['model'].pred_dist(x).params
    mu = params['loc'] * scale
    sigma = params['scale'] * scale
    if not (np.isfinite(mu).all() and np.isfinite(sigma).all() and (sigma > 0).all()):
        raise ValueError('NGBoost가 유효하지 않은 분포 파라미터를 반환했습니다.')
    out = pd.DataFrame({'center': mu, 'sigma': sigma}, index=frame.index)
    for level in C.LEVELS:
        tag = C.lv(level)
        half = norm.ppf((1 + level) / 2) * sigma
        # A negative CQR correction may shrink an interval, but never invert it.
        adjusted = np.maximum(half + package['calibration'][tag] * scale, 0)
        out[f'lo_raw_{tag}'], out[f'hi_raw_{tag}'] = mu - half, mu + half
        out[f'lo_cqr_{tag}'], out[f'hi_cqr_{tag}'] = mu - adjusted, mu + adjusted
    for threshold in LOSS_THRESHOLDS:
        cutoff = 100 * np.log1p(threshold / 100)
        out[f'prob_loss_{-threshold}pct'] = norm.cdf(cutoff, loc=mu, scale=sigma)
    return out


def fit(ctx, rounds):
    model = NGBRegressor(
        Dist=Normal, Score=LogScore, Base=DecisionTreeRegressor(max_depth=3),
        natural_gradient=True, n_estimators=rounds, learning_rate=0.01,
        random_state=C.SEED, verbose=False,
    )
    with C.Timer() as timer:
        model.fit(C.design(ctx.train), ctx.y['train'] / ctx.scale(ctx.train))
    package = {
        'model': model, 'version': MODEL_VERSION, 'dataset_version': str(ctx.train['dataset_version'].iloc[0]),
        'horizon': ctx.h, 'assets': ctx.assets, 'input_order': C.INPUT_ORDER,
        'train_seconds': timer.seconds, 'calibration': {C.lv(level): 0.0 for level in C.LEVELS},
    }
    cal = predict_distribution(package, ctx.cal)
    scale = ctx.scale(ctx.cal)
    for level in C.LEVELS:
        tag = C.lv(level)
        adjustment = cqr_adjustment(
            ctx.y['cal'] / scale, cal[f'lo_raw_{tag}'] / scale, cal[f'hi_raw_{tag}'] / scale, level,
        )
        if not np.isfinite(adjustment):
            raise ValueError(f'{ctx.h}거래일 {tag}% 구간을 보정할 표본이 부족합니다.')
        package['calibration'][tag] = adjustment
    return package


def evaluate(ctx, package):
    columns = [*KEYS, 'target_date', 'overlap_block', 'point_in_time_verified',
               'asset_scale', *C.SHOCK_ORDER, ctx.ycol]
    pred = ctx.test[columns].rename(columns={ctx.ycol: 'y_actual'}).join(
        predict_distribution(package, ctx.test)
    )
    pred['horizon'] = ctx.h
    pred['raw_nll'] = -norm.logpdf(pred['y_actual'], loc=pred['center'], scale=pred['sigma'])
    return pred


def metrics(pred, model, variant, horizon, group='all'):
    y, mu = pred['y_actual'].to_numpy(), pred['center'].to_numpy()
    rows = []
    for level in C.LEVELS:
        tag = C.lv(level)
        lo, hi = pred[f'lo_{variant}_{tag}'].to_numpy(), pred[f'hi_{variant}_{tag}'].to_numpy()
        rows.append({
            'model': model, 'variant': variant, 'horizon': horizon, 'group': group,
            'coverage_target': level, 'rows': len(pred), 'overlap_blocks': pred['overlap_block'].nunique(),
            **C.point_metrics(y, mu), **C.interval_metrics(y, lo, hi, level),
            'pinball_lower': C.pinball(y, lo, (1 - level) / 2),
        })
    return rows


def paired_90(pred, baseline, name, variant, horizon):
    base = baseline.set_index(KEYS).reindex(pd.MultiIndex.from_frame(pred[KEYS]))
    for col in MATCH_COLUMNS:
        left, right = pred[col].to_numpy(), base[col].to_numpy()
        matches = np.array_equal(left, right) if col == 'target_date' else np.allclose(left, right)
        if len(baseline) != len(pred) or not matches:
            raise ValueError(f'{name}의 {horizon}거래일 평가 표본 불일치 ({col})')
    y = pred['y_actual'].to_numpy()
    left = pred['lo_cqr_90'].to_numpy()
    right = base[f'lo_{variant}_90'].to_numpy()
    up_left = pred['hi_cqr_90'].to_numpy()
    up_right = base[f'hi_{variant}_90'].to_numpy()
    deltas = pd.DataFrame({
        'mae': abs(y - pred['center'].to_numpy()) - abs(y - base['center'].to_numpy()),
        'interval_score_90': (
            up_left - left + 20 * (np.maximum(left - y, 0) + np.maximum(y - up_left, 0))
            - (up_right - right + 20 * (np.maximum(right - y, 0) + np.maximum(y - up_right, 0)))
        ),
        'pinball_05': np.maximum(.05 * (y - left), -.95 * (y - left))
        - np.maximum(.05 * (y - right), -.95 * (y - right)),
    })
    grouped = deltas.assign(n=1).groupby(pred['overlap_block']).sum()
    ci = block_bootstrap(grouped)
    return [{
        'baseline': name, 'baseline_variant': variant, 'horizon': horizon, 'metric': col,
        'ngboost_minus_baseline': deltas[col].mean(), 'ci_lo': ci.loc[col, 'lo'],
        'ci_hi': ci.loc[col, 'hi'], 'overlap_blocks': len(grouped),
    } for col in deltas]


def loss_metrics(pred):
    rows = []
    for threshold in LOSS_THRESHOLDS:
        p = pred[f'prob_loss_{-threshold}pct']
        happened = pred['y_actual'] <= 100 * np.log1p(threshold / 100)
        bins = pd.cut(p, [0, .05, .1, .2, .4, .6, .8, 1], include_lowest=True)
        data = pd.DataFrame({'probability': p, 'event': happened, 'brier': (p - happened) ** 2})
        for label, group in [('all', data), *data.groupby(bins, observed=True)]:
            rows.append({
                'horizon': pred['horizon'].iloc[0], 'simple_loss_pct': -threshold, 'probability_bin': str(label),
                'rows': len(group), 'mean_probability': group['probability'].mean(),
                'event_rate': group['event'].mean(), 'brier': group['brier'].mean(),
            })
    return rows


def scenarios(ctx, package):
    # Two historical states allow both a shock sweep and a state comparison.
    size = ctx.test.groupby('trading_date').size()
    dates = size[size == size.max()].index
    base = ctx.test[ctx.test['trading_date'].isin([dates[0], dates[-1]])]
    train_shocks = ctx.train.drop_duplicates('trading_date')[C.SHOCK_ORDER]
    results = []
    for name, shocks in SCENARIOS.items():
        frame = base.assign(**shocks)
        support = C.range_check(train_shocks, shocks)
        outside = [col for col, item in support.items() if item['outside']]
        rare = [col for col, value in shocks.items() if
                value < train_shocks[col].quantile(.01) or value > train_shocks[col].quantile(.99)]
        status = 'OUT_OF_RANGE' if outside else 'RARE' if rare else 'WITHIN_MARGINAL_RANGE'
        results.append(
            frame[[*KEYS, 'point_in_time_verified', *C.SHOCK_ORDER]]
            .join(predict_distribution(package, frame))
            .assign(horizon=ctx.h, scenario=name, range_status=status,
                    outside_shocks=','.join(outside), rare_shocks=','.join(rare))
        )
    return pd.concat(results, ignore_index=True)


def shock_observation_dates(split_keys, market):
    """Preserve provider observation dates at the Korean-calendar shock endpoints."""
    observations = market.set_index('trading_date')
    dates = split_keys[['horizon', 'trading_date', 'target_date']].drop_duplicates().copy()
    for factor in SHOCK_FACTORS:
        source = observations[f'{factor}_observation_date']
        dates[f'{factor}_obs_start'] = dates['trading_date'].map(source)
        dates[f'{factor}_obs_end'] = dates['target_date'].map(source)
    return dates.reset_index(drop=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--gold', type=Path, default=DEFAULT_SOURCE)
    parser.add_argument('--out', type=Path, default=ANALYTICS / 'outputs/model_ngboost')
    parser.add_argument('--horizons', type=int, nargs='+', choices=C.HORIZONS, default=C.HORIZONS)
    parser.add_argument('--rounds', type=int, default=300)
    parser.add_argument('--compare-tuned-e', action='store_true')
    args = parser.parse_args()
    if args.rounds < 1:
        parser.error('--rounds must be positive')
    out = args.out
    if out.exists():
        parser.error('--out must be a new directory for each run')
    gold = load_gold(args.gold)
    run_experiment(gold, out, horizons=args.horizons, rounds=args.rounds,
                   compare_tuned_e=args.compare_tuned_e, source={'location': str(args.gold)})
    print(out)


def run_experiment(gold, out, *, horizons=C.HORIZONS, rounds=300,
                   calibration_start=DEFAULT_CALIBRATION_START, evaluation_start=DEFAULT_EVALUATION_START,
                   compare_tuned_e=False, baseline_dir=C.OUT, source=None):
    """Train from validated Gold and write audit artifacts to a new directory."""
    out = Path(out)
    horizons = tuple(dict.fromkeys(horizons))
    if not horizons or any(h not in C.HORIZONS for h in horizons) or rounds < 1:
        raise ValueError('1·5·20거래일 중 하나 이상과 양의 학습 반복 수를 지정하세요.')
    clean, features, market = C.load_inputs(gold)
    out.mkdir(parents=True)
    comparisons, pairwise, losses, splits, scenario_tables = [], [], [], [], []
    info = {'model_version': MODEL_VERSION, 'gold': source, 'seed': C.SEED,
            'rounds': rounds, 'learning_rate': .01, 'max_depth': 3,
            'calibration_start': str(calibration_start), 'evaluation_start': str(evaluation_start),
            'packages': {pkg: version(pkg) for pkg in ('ngboost', 'numpy', 'pandas', 'scipy', 'scikit-learn', 'joblib')},
            'input_order': C.INPUT_ORDER, 'dataset_version': str(gold['dataset_version'].iloc[0]),
            'evaluation': 'conditional_reconstruction', 'blind_evaluation_claimed': False, 'horizons': {}}
    saved_baselines = {}
    if baseline_dir is not None:
        for key, variant in [('d', 'sym'), ('e', 'cqr')]:
            path = Path(baseline_dir) / f'model_{key}_predictions.parquet'
            try:
                saved_baselines[f'Model {key.upper()}'] = (C.read_table(path), variant)
            except FileNotFoundError:
                print(f'기준 예측 파일 없음 {path.name}', flush=True)
    for h in horizons:
        ctx = C.Context(clean, features, market, h, calibration_start=calibration_start,
                        evaluation_start=evaluation_start)
        if not ctx.assets:
            raise ValueError(f'{h}거래일 모델의 공통 학습·보정·평가 종목이 없습니다.')
        print(f'{h}거래일 NGBoost 학습 중', flush=True)
        package = fit(ctx, rounds)
        pred = evaluate(ctx, package)
        joblib.dump(package, out / f'ngboost_{h}d.joblib', compress=3)
        C.write_table(pred, out / f'predictions_{h}d.parquet')
        losses.extend(loss_metrics(pred))
        for regime, mask in C.regime_masks(ctx.train, pred).items():
            if mask.any():
                for variant in ('raw', 'cqr'):
                    comparisons.extend(metrics(pred[mask], 'NGBoost', variant, h, regime))
        baselines = {name: (saved[saved['horizon'] == h], variant)
                     for name, (saved, variant) in saved_baselines.items()}
        if compare_tuned_e:
            from model_e_catboost_quantile_conformal import backend, run
            tuning = json.loads((C.OUT / 'tuning/best_params.json').read_text(encoding='utf-8'))
            if tuning['backend'] != backend():
                raise ValueError('튜닝 당시의 Model E 백엔드가 필요합니다.')
            # CatBoost runs each quantile in native code. Threads also avoid
            # loky's temporary-path encoding issue on Windows.
            with joblib.parallel_backend('threading'):
                tuned = run(ctx, params=tuning['best'][str(h)])
            baselines['Model E tuned'] = (tuned['pred'], 'cqr')
        for name, (baseline, variant) in baselines.items():
            try:
                pairwise.extend(paired_90(pred, baseline, name, variant, h))
            except ValueError as exc:
                print(f'기준 모델 비교 생략 {exc}', flush=True)
                continue
            comparisons.extend(metrics(baseline, name, variant, h))
        for name in ('train', 'cal', 'test'):
            part = getattr(ctx, name)
            splits.append(part[['dataset_version', *KEYS, 'target_date', 'overlap_block',
                                'point_in_time_verified']].assign(horizon=h, split=name))
        scenario_tables.append(scenarios(ctx, package))
        info['horizons'][h] = {
            **ctx.summary(), 'evaluation_keys_sha256': keys_sha256(pred.sort_values(KEYS)),
            'calibration_adjustments': package['calibration'], 'train_seconds': package['train_seconds'],
            'raw_mean_nll': float(pred['raw_nll'].mean()),
            'point_in_time_verified_test_rows': int(pred['point_in_time_verified'].sum()),
            'exclusions': ctx.assign['split_reason'].value_counts().drop('', errors='ignore').to_dict(),
        }
    pd.DataFrame(comparisons).to_csv(out / 'metrics.csv', index=False, encoding='utf-8-sig')
    pd.DataFrame(losses).to_csv(out / 'loss_calibration.csv', index=False, encoding='utf-8-sig')
    if pairwise:
        pd.DataFrame(pairwise).to_csv(out / 'paired_differences.csv', index=False, encoding='utf-8-sig')
    split_keys = pd.concat(splits, ignore_index=True)
    C.write_table(split_keys, out / 'split_keys.parquet')
    C.write_table(shock_observation_dates(split_keys, market), out / 'shock_observation_dates.parquet')
    split_keys.groupby(['horizon', 'split', 'asset_id']).size().rename('rows').to_csv(out / 'split_asset_counts.csv')
    pd.concat(scenario_tables, ignore_index=True).to_csv(out / 'scenarios.csv', index=False, encoding='utf-8-sig')
    (out / 'run_info.json').write_text(json.dumps(info, indent=2, ensure_ascii=False), encoding='utf-8')
    return info


if __name__ == '__main__':
    main()
