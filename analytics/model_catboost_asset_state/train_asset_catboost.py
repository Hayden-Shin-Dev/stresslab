"""Asset-aware conditional return distribution and chronological benchmark."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from catboost import CatBoostRegressor, Pool, __version__ as catboost_version

ANALYTICS = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ANALYTICS / 'model_lightgbm_quantile'), str(ANALYTICS / 'model_compare')]
from experiment import C, DEFAULT_SOURCE, KEYS, keys_sha256, load_gold, paired
from extra_features import EXTRA_COLUMNS, build_extra_features
from conformal import conformal_quantile
import model_e_catboost_quantile_conformal as E

SLUG = 'model_catboost_asset_state'
VALIDATION_START = pd.Timestamp('2017-01-01')
TAUS = E.TAUS
EXTRA_ASSET = ['asset_ret5', 'asset_drawdown60', 'asset_rel_rank20', 'asset_beta_fx60',
               'asset_beta_vix60', 'asset_beta_oil60', 'asset_beta_us_rate60']
NUMERIC = [*C.INPUT_ORDER, 'kr3y_level', 'kr3y_change20_bp', 'asset_vol20', 'asset_vol60',
           *EXTRA_COLUMNS, *EXTRA_ASSET]
CATEGORIES = ['asset_id', 'sector_id']


def feature_table(clean, fs, market):
    """Compute each feature from the base date and earlier trading sessions."""
    base = build_extra_features(clean, fs)
    calendar = pd.Index(market['trading_date'], name='trading_date')
    valid = fs.asset_features.set_index(KEYS)['row_usable']
    prices = clean.set_index(KEYS)['close']
    wide = prices.where(valid.reindex(prices.index).fillna(False) & prices.gt(0)).unstack().reindex(calendar)
    returns = 100 * np.log(wide / wide.shift())
    factors = market.set_index('trading_date')
    movements = {
        'asset_beta_fx60': 100 * np.log(factors.usdkrw.where(factors.usdkrw > 0)).diff(),
        'asset_beta_vix60': factors.vix.diff(),
        'asset_beta_oil60': 100 * np.log(factors.wti.where(factors.wti > 0)).diff(),
        'asset_beta_us_rate60': 100 * factors.us_treasury_10y.diff(),
    }
    extra = {
        'asset_ret5': 100 * (wide / wide.shift(5) - 1),
        'asset_drawdown60': 100 * (wide / wide.rolling(60, min_periods=60).max() - 1),
        'asset_rel_rank20': (wide / wide.shift(20) - 1).rank(axis=1, pct=True),
    }
    for name, factor in movements.items():
        variance = factor.rolling(60, min_periods=60).var()
        extra[name] = returns.rolling(60, min_periods=60).cov(factor).div(variance.where(variance > 1e-9), axis=0)
    wide_extra = pd.concat({name: df for name, df in extra.items()}, axis=1)
    long = wide_extra.stack(level='asset_id').rename_axis(index=KEYS).reset_index()
    base = base.merge(long, on=KEYS, how='left', validate='one_to_one')
    return base.merge(clean[KEYS + ['sector_id']], on=KEYS, how='left', validate='one_to_one')


def design(frame):
    values = pd.DataFrame(C.design(frame, cols=NUMERIC), columns=NUMERIC, index=frame.index)
    values = values.replace([np.inf, -np.inf], np.nan)
    for col in CATEGORIES:
        values[col] = frame[col].astype('string').fillna('unknown').astype(str)
    return values


def fit_quantile(train, valid, full, tau):
    params = dict(loss_function=f'Quantile:alpha={tau}', depth=5, learning_rate=.035,
                  l2_leaf_reg=25, random_seed=C.SEED, one_hot_max_size=32,
                  allow_writing_files=False, verbose=False, thread_count=1)
    model = CatBoostRegressor(iterations=450, **params)
    model.fit(train, eval_set=valid, early_stopping_rounds=55, use_best_model=True)
    iterations = max(1, model.tree_count_)
    model = CatBoostRegressor(iterations=iterations, **params).fit(full)
    return model, iterations


def quantiles(models, frame):
    x = design(frame)
    raw = np.column_stack([model.predict(x, thread_count=1) for model in models])
    return np.sort(raw, axis=1)


def fit(ctx):
    train = ctx.train
    x = design(train)
    y = train[ctx.ycol].to_numpy() / ctx.scale(train)
    early = (train.target_date < VALIDATION_START).to_numpy()
    later = (train.trading_date >= VALIDATION_START).to_numpy()
    cats = [x.columns.get_loc(col) for col in CATEGORIES]
    train_pool = Pool(x[early], y[early], cat_features=cats)
    valid_pool = Pool(x[later], y[later], cat_features=cats, weight=ctx.scale(train)[later])
    full_pool = Pool(x, y, cat_features=cats)
    fitted = joblib.Parallel(n_jobs=4, prefer='threads')(
        joblib.delayed(fit_quantile)(train_pool, valid_pool, full_pool, tau) for tau in TAUS
    )
    models, rounds = map(list, zip(*fitted))
    cal = quantiles(models, ctx.cal)
    y_cal = ctx.y['cal'] / ctx.scale(ctx.cal)
    corrections = {}
    for level, (lo, hi) in C.LEVEL_Q.items():
        target_tail = (1 + level) / 2
        corrections[level] = (
            conformal_quantile(cal[:, TAUS.index(lo)] - y_cal, target_tail),
            conformal_quantile(y_cal - cal[:, TAUS.index(hi)], target_tail),
        )
    if not np.isfinite(list(corrections.values())).all():
        raise RuntimeError('Insufficient calibration rows')
    return {'models': models, 'rounds': rounds, 'tail_corrections': corrections,
            'horizon': ctx.h, 'assets': ctx.assets, 'numeric_inputs': NUMERIC, 'categorical_inputs': CATEGORIES}


def predict(package, frame, *, calibrated=True):
    q = quantiles(package['models'], frame)
    scale = C._floor(frame.asset_scale)
    center = q[:, TAUS.index(.5)]
    out = pd.DataFrame({'center': center * scale}, index=frame.index)
    prev_lo, prev_hi = center, center
    for level, (lo, hi) in C.LEVEL_Q.items():
        left, right = package['tail_corrections'][level] if calibrated else (0., 0.)
        prev_lo = np.minimum(prev_lo, q[:, TAUS.index(lo)] - left)
        prev_hi = np.maximum(prev_hi, q[:, TAUS.index(hi)] + right)
        out[f'lo_{C.lv(level)}'] = prev_lo * scale
        out[f'hi_{C.lv(level)}'] = prev_hi * scale
    return out


def summarize(h, name, pred, train, variant=None):
    for group, mask in C.regime_masks(train, pred).items():
        if not mask.any():
            continue
        frame = pred[mask]
        y = frame.y_actual.to_numpy()
        for level in C.LEVELS:
            suffix = f'{variant}_{C.lv(level)}' if variant else C.lv(level)
            lo, hi = frame[f'lo_{suffix}'].to_numpy(), frame[f'hi_{suffix}'].to_numpy()
            yield {'horizon': h, 'model': name, 'group': group, 'level': level, 'rows': len(frame),
                   'blocks': frame.overlap_block.nunique(), **C.point_metrics(y, frame.center.to_numpy()),
                   **C.interval_metrics(y, lo, hi, level), 'pinball_lower': C.pinball(y, lo, (1-level)/2)}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out', type=Path, default=ANALYTICS / 'outputs' / SLUG)
    ap.add_argument('--horizons', nargs='+', type=int, choices=C.HORIZONS, default=C.HORIZONS)
    args = ap.parse_args()
    tune = json.loads((C.OUT / 'tuning/best_params.json').read_text(encoding='utf-8'))
    if E.backend() != tune['backend']:
        raise RuntimeError('Tuned Model E backend does not match')
    clean, fs, market = C.load_inputs(load_gold(DEFAULT_SOURCE))
    additions = feature_table(clean, fs, market)
    args.out.mkdir(parents=True)
    metrics, diffs, report = [], [], {}
    for h in dict.fromkeys(args.horizons):
        print(f'Asset-state CatBoost: training {h}d', flush=True)
        ctx = C.Context(clean, fs, market, h)
        for split in ('train', 'cal', 'test'):
            part = getattr(ctx, split)
            setattr(ctx, split, part.merge(additions, on=KEYS, how='left', validate='one_to_one'))
        with C.Timer() as timer:
            package = fit(ctx)
        joblib.dump(package, args.out / f'model_{h}d.joblib', compress=3)
        keys = [*KEYS, 'target_date', 'overlap_block', *C.SHOCK_ORDER, ctx.ycol]
        base = ctx.test[keys].rename(columns={ctx.ycol: 'y_actual'}).assign(horizon=h)
        pred = base.join(predict(package, ctx.test))
        raw = base.join(predict(package, ctx.test, calibrated=False))
        C.write_table(pred, args.out / f'predictions_{h}d.parquet')
        metrics.extend(summarize(h, 'Asset-state CatBoost', pred, ctx.train))
        metrics.extend(summarize(h, 'Asset-state CatBoost raw', raw, ctx.train))
        print(f'{h}d candidate finished; evaluating comparators', flush=True)
        with joblib.parallel_backend('threading'):
            model_e = E.run(ctx, params=tune['best'][str(h)])['pred']
        comparators = [('Model E tuned', model_e, 'cqr')]
        for name, slug, variant in [
            ('NGBoost', 'model_ngboost', 'cqr'),
            ('Huber interactions', 'model_huber_interactions', 'stored'),
            ('LightGBM quantile', 'model_lightgbm_quantile', 'stored'),
        ]:
            saved = pd.read_parquet(ANALYTICS / f'outputs/{slug}/predictions_{h}d.parquet')
            if variant == 'stored':
                saved = saved.rename(columns={f'{side}_{C.lv(level)}': f'{side}_stored_{C.lv(level)}'
                                              for level in C.LEVELS for side in ('lo', 'hi')})
            comparators.append((name, saved, variant))
        for name, baseline, variant in comparators:
            diffs.extend(paired(pred, baseline, name, variant, h))
            metrics.extend(summarize(h, name, baseline, ctx.train, variant))
        report[h] = {**ctx.summary(), 'selected_rounds': dict(zip(map(str, TAUS), package['rounds'])),
                     'fit_seconds': timer.seconds, 'evaluation_keys_sha256': keys_sha256(pred.sort_values(KEYS))}
    pd.DataFrame(metrics).to_csv(args.out / 'metrics.csv', index=False, encoding='utf-8-sig')
    pd.DataFrame(diffs).to_csv(args.out / 'paired_differences.csv', index=False, encoding='utf-8-sig')
    info = {'model': SLUG, 'dataset_version': str(clean.dataset_version.iloc[0]), 'catboost': catboost_version,
            'numeric_inputs': NUMERIC, 'categorical_inputs': CATEGORIES, 'early_stop_from': str(VALIDATION_START.date()),
            'evaluation': 'previously exposed conditional reconstruction', 'horizons': report}
    (args.out / 'run_info.json').write_text(json.dumps(info, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
