"""Local StressLab CatBoost location/scale experiment."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from catboost import CatBoostRegressor, __version__ as catboost_version
from scipy.stats import norm

ANALYTICS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ANALYTICS / 'model_ngboost'))
import train as reference

C = reference.C
NAME = 'CatBoost uncertainty'
OUT = ANALYTICS / 'outputs/model_catboost_uncertainty'


def parameters(model, frame):
    raw = model.predict(C.design(frame), prediction_type='RawFormulaVal')
    scale = C._floor(frame['asset_scale'])
    mu, sigma = raw[:, 0] * scale, np.exp(raw[:, 1]) * scale
    if not np.isfinite(mu).all() or not np.isfinite(sigma).all() or (sigma <= 0).any():
        raise ValueError('Invalid location or scale')
    return mu, sigma


def predict(package, frame, variant):
    mu, sigma = parameters(package['model'], frame)
    residuals = package['sorted_residuals']
    result = pd.DataFrame({'center': mu, 'sigma': sigma}, index=frame.index)
    for level in C.LEVELS:
        tag = C.lv(level)
        if variant == 'raw':
            lo, hi = norm.ppf([(1 - level) / 2, (1 + level) / 2])
        else:
            lo, hi = package['intervals'][tag]
        result[f'lo_{variant}_{tag}'] = mu + sigma * lo
        result[f'hi_{variant}_{tag}'] = mu + sigma * hi
    for loss in (5, 10):
        z = (100 * np.log1p(-loss / 100) - mu) / sigma
        result[f'prob_loss_{loss}pct'] = (norm.cdf(z) if variant == 'raw'
                                         else np.searchsorted(residuals, z, side='right') / len(residuals))
    return result


def fit(ctx):
    from conformal import asym_halfwidths

    model = CatBoostRegressor(
        loss_function='RMSEWithUncertainty', iterations=500, depth=4, learning_rate=.03,
        thread_count=4, random_seed=C.SEED, verbose=False, allow_writing_files=False,
    )
    with C.Timer() as timer:
        model.fit(C.design(ctx.train), ctx.y['train'] / ctx.scale(ctx.train))
    mu, sigma = parameters(model, ctx.cal)
    residual = (ctx.y['cal'] - mu) / sigma
    intervals = {}
    for level in C.LEVELS:
        below, above = asym_halfwidths(residual, level)
        if not np.isfinite([below, above]).all():
            raise ValueError('Insufficient calibration observations')
        intervals[C.lv(level)] = (-below, above)
    return {'model': model, 'sorted_residuals': np.sort(residual), 'intervals': intervals,
            'horizon': ctx.h, 'assets': ctx.assets, 'inputs': C.INPUT_ORDER, 'train_seconds': timer.seconds}


def main():
    from model_e_catboost_quantile_conformal import backend, run

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=OUT)
    args = parser.parse_args()
    tuning = json.loads((C.OUT / 'tuning/best_params.json').read_text(encoding='utf-8'))
    if tuning['backend'] != backend():
        raise RuntimeError('Tuned Model E requires its original CatBoost backend.')
    clean, fs, market = C.load_inputs(reference.load_gold(reference.DEFAULT_SOURCE))
    args.out.mkdir(parents=True)
    metrics, losses, paired, splits = [], [], [], {}
    for h in C.HORIZONS:
        print(f'{NAME}: fitting {h}d', flush=True)
        ctx = C.Context(clean, fs, market, h)
        package = fit(ctx)
        joblib.dump(package, args.out / f'catboost_uncertainty_{h}d.joblib', compress=3)
        keys = [*reference.KEYS, 'target_date', 'overlap_block', 'asset_scale', *C.SHOCK_ORDER, ctx.ycol]
        base = ctx.test[keys].rename(columns={ctx.ycol: 'y_actual'}).assign(horizon=h)
        for variant in ('raw', 'empirical'):
            pred = base.join(predict(package, ctx.test, variant))
            C.write_table(pred, args.out / f'predictions_{variant}_{h}d.parquet')
            for group, mask in C.regime_masks(ctx.train, pred).items():
                if mask.any():
                    metrics.extend(reference.metrics(pred[mask], NAME, variant, h, group))
            losses.extend(dict(row, model=NAME, variant=variant) for row in reference.loss_metrics(pred))
        with joblib.parallel_backend('threading'):
            e = run(ctx, params=tuning['best'][str(h)])['pred']
        baselines = [
            ('Model E tuned', 'cqr', e),
            ('NGBoost', 'cqr', pd.read_parquet(ANALYTICS / f'outputs/model_ngboost/predictions_{h}d.parquet')),
        ]
        as_cqr = pred.rename(columns={c: c.replace('_empirical_', '_cqr_') for c in pred if '_empirical_' in c})
        for label, variant, baseline in baselines:
            metrics.extend(reference.metrics(baseline, label, variant, h))
            for row in reference.paired_90(as_cqr, baseline, label, variant, h):
                row['candidate_minus_baseline'] = row.pop('ngboost_minus_baseline')
                paired.append(row)
        splits[h] = {**ctx.summary(), 'train_seconds': package['train_seconds'],
                     'evaluation_keys_sha256': reference.keys_sha256(pred.sort_values(reference.KEYS))}
        print(f'{NAME}: completed {h}d ({len(pred)} evaluation rows)', flush=True)
    for name, rows in [('metrics', metrics), ('loss_calibration', losses), ('paired_differences', paired)]:
        pd.DataFrame(rows).to_csv(args.out / f'{name}.csv', index=False, encoding='utf-8-sig')
    info = {'model': NAME, 'catboost': catboost_version, 'horizons': splits,
            'dataset_version': str(clean['dataset_version'].iloc[0]),
            'evaluation': 'previously exposed conditional shock reconstruction'}
    (args.out / 'run_info.json').write_text(json.dumps(info, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
