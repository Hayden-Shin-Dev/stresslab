"""Train a recent-history CatBoost and validate an adaptive return ensemble."""
from __future__ import annotations

import argparse
import json
import sys
from itertools import product
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from catboost import CatBoostRegressor, Pool, __version__ as catboost_version

ANALYTICS = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ANALYTICS / 'model_catboost_asset_state'),
                str(ANALYTICS / 'model_huber_interactions')]
import train_asset_catboost as asset
import train_huber_interactions as huber
from experiment import C, DEFAULT_SOURCE, KEYS, keys_sha256, load_gold, paired
from conformal import conformal_quantile, rolling_quantiles
import model_e_catboost_quantile_conformal as E

SLUG = 'model_adaptive_quantile_ensemble'
RECENT_START = pd.Timestamp('2010-01-01')
WINDOW_SELECTION_START = pd.Timestamp('2022-01-01')
OUT = ANALYTICS / 'outputs' / SLUG
TAUS = asset.TAUS
MIDDLE = TAUS.index(.5)
BLEND_GRID = np.linspace(0, 1, 5)


def fit_recent(ctx, global_package):
    rows = ctx.train.loc[ctx.train.trading_date >= RECENT_START]
    design = asset.design(rows)
    normalized = rows[ctx.ycol].to_numpy() / ctx.scale(rows)
    age_years = (rows.trading_date.max() - rows.trading_date).dt.days.to_numpy() / 365.25
    pool = Pool(design, normalized, cat_features=asset.CATEGORIES, weight=np.exp2(-age_years / 5))

    def fit_one(old_model):
        return CatBoostRegressor(**old_model.get_params()).fit(pool)

    models = joblib.Parallel(n_jobs=4, prefer='threads')(
        joblib.delayed(fit_one)(model) for model in global_package['models']
    )
    return models, len(rows)


def component_predictions(package, frame):
    global_q = asset.quantiles(package['global_models'], frame)
    recent_q = asset.quantiles(package['recent_models'], frame)
    robust_center = package['huber_model'].predict(huber.design(frame))
    return global_q, recent_q, robust_center


def tune_blend(components, target, scale):
    global_q, recent_q, robust_center = components
    centers = np.column_stack((global_q[:, MIDDLE], recent_q[:, MIDDLE], robust_center))
    weights = [(a, b, max(0., 1-a-b)) for a, b in product(BLEND_GRID, repeat=2) if a+b <= 1]
    center_rows = [{'global': a, 'recent': b, 'huber': c,
                    'mae': np.mean(np.abs(target - (centers @ [a, b, c]) * scale))}
                   for a, b, c in weights]
    tails = [i for i, tau in enumerate(TAUS) if tau != .5]
    qs = np.asarray(TAUS)[tails]
    tail_rows = []
    for weight in BLEND_GRID:
        raw = ((1 - weight) * global_q[:, tails] + weight * recent_q[:, tails]) * scale[:, None]
        residual = target[:, None] - raw
        pinball = np.maximum(qs * residual, (qs - 1) * residual).mean()
        tail_rows.append({'recent': float(weight), 'pinball': float(pinball)})
    center = min(center_rows, key=lambda row: row['mae'])
    tail = min(tail_rows, key=lambda row: row['pinball'])
    return [center[key] for key in ('global', 'recent', 'huber')], tail['recent'], center_rows, tail_rows


def blend(package, components):
    global_q, recent_q, robust_center = components
    centers = np.column_stack((global_q[:, MIDDLE], recent_q[:, MIDDLE], robust_center))
    w = package['recent_tail_weight']
    return centers @ package['center_weights'], (1 - w) * global_q + w * recent_q


def calibration_bank(frame, target, q):
    cols = [f'q{i}' for i in range(len(TAUS))]
    bank = pd.DataFrame(q, columns=cols)
    bank['target_pos'] = frame.target_pos.to_numpy()
    bank['y_norm'] = target / C._floor(frame.asset_scale)
    if (bank.target_pos < 0).any():
        raise ValueError('Calibration labels must have valid calendar positions.')
    return bank


def band(center, q, scale, positions, level, config, history, fallback):
    tau_lo, tau_hi = C.LEVEL_Q[level]
    ilo, ihi = TAUS.index(tau_lo), TAUS.index(tau_hi)
    qlo, qhi = f'q{ilo}', f'q{ihi}'

    def scores(frame):
        lo, hi, y = (frame[col].to_numpy() for col in (qlo, qhi, 'y_norm'))
        unit = np.maximum((hi-lo)/2, .15) if config['relative'] else 1.
        return (lo-y)/unit, (y-hi)/unit

    lo, hi = q[:, ilo], q[:, ihi]
    unit = np.maximum((hi-lo)/2, .15) if config['relative'] else 1.
    now = history.target_pos.to_numpy()
    if len(fallback) == 0 or fallback.target_pos.max() >= np.min(positions):
        raise ValueError('Static fallback must precede every query.')
    sl, sr = scores(history)
    fl, fr = scores(fallback)

    def correction(values, initial, quantile):
        fixed = conformal_quantile(initial, quantile)
        if not np.isfinite(fixed):
            raise ValueError('Insufficient fallback calibration rows.')
        if config['window'] is None:
            return fixed
        return rolling_quantiles(values, now, positions, quantile, config['window'], fallback=fixed)

    if config['style'] == 'joint':
        left = right = correction(np.maximum(sl, sr), np.maximum(fl, fr), level)
    else:
        tail_level = (1+level)/2
        left, right = correction(sl, fl, tail_level), correction(sr, fr, tail_level)
    return np.minimum(center, lo-left*unit)*scale, np.maximum(center, hi+right*unit)*scale


def tune_calibration(frame, target, center, q, history, initial):
    configs = [{'style': style, 'relative': relative, 'window': window}
               for style, relative, window in product(('tails', 'joint'), (False, True), (None, 63, 126, 252))]
    scale = C._floor(frame.asset_scale)
    rows = []
    for config in configs:
        lo, hi = band(center, q, scale, frame.row_pos.to_numpy(), .90, config, history, initial)
        score = C.interval_metrics(target, lo, hi, .90)
        rows.append({**config, **score})
    shortlisted = [row for row in rows if row['coverage'] >= .88] or rows
    selected = min(shortlisted, key=lambda row: row['interval_score'])
    return {field: selected[field] for field in ('style', 'relative', 'window')}, rows


def predict(package, frame, history=None):
    """Predict from enriched rows and optionally add known past calibration outcomes."""
    center, q = blend(package, component_predictions(package, frame))
    scale = C._floor(frame.asset_scale)
    positions = frame.row_pos.to_numpy()
    default = package['initial_history']
    history = default if history is None else pd.concat([default, history], ignore_index=True)
    output = pd.DataFrame({'center': center*scale}, index=frame.index)
    lower, upper = output.center.to_numpy(), output.center.to_numpy()
    for level in C.LEVELS:
        lo, hi = band(center, q, scale, positions, level, package['calibration'], history, default)
        lower, upper = np.minimum(lower, lo), np.maximum(upper, hi)
        tag = C.lv(level)
        output[f'lo_{tag}'], output[f'hi_{tag}'] = lower, upper
    return output


def checked_members(ctx, dataset):
    packages = []
    expected_keys = keys_sha256(ctx.test.sort_values(KEYS))
    for slug in ('model_catboost_asset_state', 'model_huber_interactions'):
        path = ANALYTICS / 'outputs' / slug
        run_info = json.loads((path / 'run_info.json').read_text(encoding='utf-8'))
        saved = run_info['horizons'][str(ctx.h)]
        if (run_info['dataset_version'] != dataset
                or saved['evaluation_keys_sha256'] != expected_keys
                or saved['train_rows'] != len(ctx.train)):
            raise ValueError(f'{slug} has a different dataset or split.')
        package = joblib.load(path / f'model_{ctx.h}d.joblib')
        if package['assets'] != ctx.assets:
            raise ValueError(f'{slug} has a different asset universe.')
        packages.append(package)
    return packages


def read_reference(slug, horizon):
    pred = pd.read_parquet(ANALYTICS / f'outputs/{slug}/predictions_{horizon}d.parquet')
    if slug != 'model_ngboost':
        pred = pred.rename(columns={f'{side}_{C.lv(level)}': f'{side}_stored_{C.lv(level)}'
                                    for level in C.LEVELS for side in ('lo', 'hi')})
    return pred


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=OUT)
    parser.add_argument('--horizons', nargs='+', type=int, choices=C.HORIZONS, default=C.HORIZONS)
    args = parser.parse_args()
    tune = json.loads((C.OUT / 'tuning/best_params.json').read_text(encoding='utf-8'))
    if E.backend() != tune['backend']:
        raise RuntimeError('Tuned Model E backend does not match.')
    clean, features, market = C.load_inputs(load_gold(DEFAULT_SOURCE))
    extra = asset.feature_table(clean, features, market)
    dataset = str(clean.dataset_version.iloc[0])
    args.out.mkdir(parents=True)
    metrics, differences, choices, splits = [], [], [], {}
    for h in dict.fromkeys(args.horizons):
        print(f'Adaptive ensemble: training recent CatBoost for {h}d', flush=True)
        ctx = C.Context(clean, features, market, h)
        for name in ('train', 'cal', 'test'):
            setattr(ctx, name, getattr(ctx, name).merge(extra, on=KEYS, how='left', validate='one_to_one'))
        global_package, huber_package = checked_members(ctx, dataset)
        with C.Timer() as timer:
            recent, recent_rows = fit_recent(ctx, global_package)
        package = {'global_models': global_package['models'], 'recent_models': recent,
                   'huber_model': huber_package['model'], 'horizon': h, 'assets': ctx.assets,
                   'numeric_inputs': asset.NUMERIC, 'categorical_inputs': asset.CATEGORIES}
        early = (ctx.cal.target_date < WINDOW_SELECTION_START).to_numpy()
        later = (ctx.cal.trading_date >= WINDOW_SELECTION_START).to_numpy()
        cal = component_predictions(package, ctx.cal)
        weights, tail, center_cv, tail_cv = tune_blend(tuple(arr[early] for arr in cal),
                                                     ctx.y['cal'][early], ctx.scale(ctx.cal)[early])
        package.update(center_weights=weights, recent_tail_weight=tail)
        center, q = blend(package, cal)
        cal_bank = calibration_bank(ctx.cal, ctx.y['cal'], q)
        candidates, cv = tune_calibration(ctx.cal.loc[later], ctx.y['cal'][later], center[later], q[later],
                                          cal_bank, cal_bank.loc[early])
        package.update(calibration=candidates, initial_history=cal_bank)
        print(f'{h}d weights {weights}; tail recent weight={tail}; calibration {candidates}', flush=True)
        joblib.dump(package, args.out / f'model_{h}d.joblib', compress=3)
        _, q_test = blend(package, component_predictions(package, ctx.test))
        test_bank = calibration_bank(ctx.test, ctx.y['test'], q_test)
        keys = [*KEYS, 'target_date', 'overlap_block', *C.SHOCK_ORDER, ctx.ycol]
        meta = ctx.test[keys].rename(columns={ctx.ycol: 'y_actual'}).assign(horizon=h)
        pred = meta.join(predict(package, ctx.test, test_bank))
        keeps = ctx.test[[*KEYS, 'row_pos', 'target_pos']].copy().join(test_bank.drop(columns='target_pos'))
        C.write_table(keeps, args.out / f'calibration_events_{h}d.parquet')
        C.write_table(pred, args.out / f'predictions_{h}d.parquet')
        metrics.extend(asset.summarize(h, 'Adaptive ensemble', pred, ctx.train))
        with joblib.parallel_backend('threading'):
            e_pred = E.run(ctx, params=tune['best'][str(h)])['pred']
        comparators = [
            ('Model E tuned', e_pred, 'cqr'),
            ('Model E tuned rolling', e_pred, 'cqr_roll'),
            ('Asset-state CatBoost', read_reference('model_catboost_asset_state', h), 'stored'),
            ('Huber interactions', read_reference('model_huber_interactions', h), 'stored'),
            ('NGBoost', read_reference('model_ngboost', h), 'cqr'),
        ]
        for name, baseline, variant in comparators:
            differences.extend(paired(pred, baseline, name, variant, h))
            metrics.extend(asset.summarize(h, name, baseline, ctx.train, variant))
        choices.extend({'horizon': h, 'stage': stage, **row}
                       for stage, rows in [('center', center_cv), ('tails', tail_cv), ('calibration', cv)]
                       for row in rows)
        splits[h] = {**ctx.summary(), 'fit_seconds_recent': timer.seconds, 'recent_train_rows': recent_rows,
                     'blend_selection_rows': int(early.sum()), 'calibration_selection_rows': int(later.sum()),
                     'purged_between_calibration_stages': int((~early & ~later).sum()),
                     'evaluation_keys_sha256': keys_sha256(pred.sort_values(KEYS)),
                     'center_weights': dict(zip(('global_catboost', 'recent_catboost', 'huber'), weights)),
                     'recent_tail_weight': tail, 'calibration': candidates}
        print(f'{h}d benchmark completed', flush=True)
    for name, rows in [('metrics', metrics), ('paired_differences', differences), ('validation_choices', choices)]:
        pd.DataFrame(rows).to_csv(args.out / f'{name}.csv', index=False, encoding='utf-8-sig')
    info = {'model': SLUG, 'dataset_version': dataset, 'catboost': catboost_version,
            'recent_train_start': str(RECENT_START.date()), 'recent_weight_half_life_years': 5,
            'window_selection_start': str(WINDOW_SELECTION_START.date()),
            'numeric_inputs': asset.NUMERIC, 'categorical_inputs': asset.CATEGORIES,
            'evaluation': 'previously exposed conditional reconstruction',
            'evaluation_uses_matured_residuals_only_if_rolling_selected': True, 'horizons': splits}
    (args.out / 'run_info.json').write_text(json.dumps(info, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
