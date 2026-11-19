"""Factor decomposition with market Huber and asset residual CatBoost."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from catboost import Pool, __version__ as catboost_version
from sklearn.impute import SimpleImputer
from sklearn.linear_model import HuberRegressor
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

ANALYTICS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ANALYTICS / 'model_catboost_asset_state'))
import train_asset_catboost as asset
from experiment import C, DEFAULT_SOURCE, KEYS, keys_sha256, load_gold, paired
from extra_features import EXTRA_MARKET
from conformal import conformal_quantile
import model_e_catboost_quantile_conformal as E

SLUG = 'model_market_factor_catboost'
OUT = ANALYTICS / 'outputs' / SLUG
MARKET_INPUTS = [*C.INPUT_ORDER, 'kr3y_level', 'kr3y_change20_bp', *EXTRA_MARKET]
TAUS = asset.TAUS


def market_design(frame):
    x = C.design(frame, cols=MARKET_INPUTS)
    x[~np.isfinite(x)] = np.nan
    n = len(C.SHOCK_ORDER)
    cross = x[:, :n, None] * x[:, None, n:]
    return np.column_stack([x, cross.reshape(len(x), -1)])


def exposure(frame):
    """Shrink noisy betas toward one and limit leverage in the factor term."""
    beta = frame.asset_beta60.replace([np.inf, -np.inf], np.nan).fillna(1.).to_numpy()
    return .25 + .75 * np.clip(beta, -.5, 2.5)


def fit(ctx, market):
    close = market.set_index('trading_date')['kospi_close']
    train = ctx.train.copy()
    train['market_target'] = 100 * np.log(train.target_date.map(close) / train.trading_date.map(close))
    train = train.loc[np.isfinite(train.market_target)].reset_index(drop=True)
    market_rows = train.drop_duplicates('trading_date')
    market_model = make_pipeline(SimpleImputer(strategy='median', add_indicator=True),
                                 StandardScaler(), HuberRegressor(alpha=8., epsilon=1.35, max_iter=1000))
    market_model.fit(market_design(market_rows),
                     market_rows.market_target / C._floor(market_rows.scale_kospi))
    x = asset.design(train)
    normalized = (train[ctx.ycol] - exposure(train) * train.market_target).to_numpy() / ctx.scale(train)
    early = (train.target_date < asset.VALIDATION_START).to_numpy()
    later = (train.trading_date >= asset.VALIDATION_START).to_numpy()
    pools = (Pool(x[early], normalized[early], cat_features=asset.CATEGORIES),
             Pool(x[later], normalized[later], cat_features=asset.CATEGORIES, weight=ctx.scale(train)[later]),
             Pool(x, normalized, cat_features=asset.CATEGORIES))
    fitted = joblib.Parallel(n_jobs=4, prefer='threads')(
        joblib.delayed(asset.fit_quantile)(*pools, tau) for tau in TAUS
    )
    models, rounds = map(list, zip(*fitted))
    package = {'market_model': market_model, 'models': models, 'rounds': rounds, 'horizon': ctx.h,
               'assets': ctx.assets, 'market_inputs': MARKET_INPUTS, 'residual_numeric_inputs': asset.NUMERIC,
               'residual_categorical_inputs': asset.CATEGORIES}
    q = raw_quantiles(package, ctx.cal)
    y = ctx.y['cal'] / ctx.scale(ctx.cal)
    tails = {level: (conformal_quantile(q[:, TAUS.index(lo)] - y, (1+level)/2),
                     conformal_quantile(y - q[:, TAUS.index(hi)], (1+level)/2))
             for level, (lo, hi) in C.LEVEL_Q.items()}
    if not np.isfinite(list(tails.values())).all():
        raise ValueError('Insufficient calibration rows.')
    package['tail_corrections'] = tails
    return package, len(train), len(market_rows)


def raw_quantiles(package, frame):
    market_return = package['market_model'].predict(market_design(frame)) * C._floor(frame.scale_kospi)
    normalized_market = exposure(frame) * market_return / C._floor(frame.asset_scale)
    return asset.quantiles(package['models'], frame) + normalized_market[:, None]


def predict(package, frame):
    q = raw_quantiles(package, frame)
    scale = C._floor(frame.asset_scale)
    center = q[:, TAUS.index(.5)]
    out = pd.DataFrame({'center': center*scale}, index=frame.index)
    previous_lo, previous_hi = center, center
    for level, (lo, hi) in C.LEVEL_Q.items():
        left, right = package['tail_corrections'][level]
        previous_lo = np.minimum(previous_lo, q[:, TAUS.index(lo)] - left)
        previous_hi = np.maximum(previous_hi, q[:, TAUS.index(hi)] + right)
        out[f'lo_{C.lv(level)}'], out[f'hi_{C.lv(level)}'] = previous_lo*scale, previous_hi*scale
    return out


def reference(slug, horizon):
    path = ANALYTICS / 'outputs' / slug
    pred = pd.read_parquet(path / f'predictions_{horizon}d.parquet')
    return pred.rename(columns={f'{side}_{C.lv(level)}': f'{side}_stored_{C.lv(level)}'
                                for level in C.LEVELS for side in ('lo', 'hi')})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=OUT)
    parser.add_argument('--horizons', nargs='+', type=int, choices=C.HORIZONS, default=C.HORIZONS)
    args = parser.parse_args()
    tune = json.loads((C.OUT / 'tuning/best_params.json').read_text(encoding='utf-8'))
    if E.backend() != tune['backend']:
        raise RuntimeError('Tuned Model E backend does not match.')
    clean, fs, market = C.load_inputs(load_gold(DEFAULT_SOURCE))
    extra = asset.feature_table(clean, fs, market)
    args.out.mkdir(parents=True)
    metrics, comparisons, info = [], [], {}
    for h in dict.fromkeys(args.horizons):
        print(f'Market-factor CatBoost: training {h}d', flush=True)
        ctx = C.Context(clean, fs, market, h)
        for name in ('train', 'cal', 'test'):
            setattr(ctx, name, getattr(ctx, name).merge(extra, on=KEYS, how='left', validate='one_to_one'))
        with C.Timer() as timer:
            package, residual_rows, market_rows = fit(ctx, market)
        joblib.dump(package, args.out / f'model_{h}d.joblib', compress=3)
        columns = [*KEYS, 'target_date', 'overlap_block', *C.SHOCK_ORDER, ctx.ycol]
        pred = ctx.test[columns].rename(columns={ctx.ycol: 'y_actual'}).assign(horizon=h).join(predict(package, ctx.test))
        C.write_table(pred, args.out / f'predictions_{h}d.parquet')
        metrics.extend(asset.summarize(h, 'Market-factor CatBoost', pred, ctx.train))
        print(f'{h}d training done; comparing same evaluation rows', flush=True)
        with joblib.parallel_backend('threading'):
            e_pred = E.run(ctx, params=tune['best'][str(h)])['pred']
        refs = [('Model E tuned', e_pred, 'cqr'), ('Model E tuned rolling', e_pred, 'cqr_roll')]
        for name, slug in [('Asset-state CatBoost', 'model_catboost_asset_state'),
                           ('Huber interactions', 'model_huber_interactions'),
                           ('Adaptive ensemble', 'model_adaptive_quantile_ensemble')]:
            refs.append((name, reference(slug, h), 'stored'))
        for name, baseline, variant in refs:
            comparisons.extend(paired(pred, baseline, name, variant, h))
            metrics.extend(asset.summarize(h, name, baseline, ctx.train, variant))
        info[h] = {**ctx.summary(), 'fit_seconds': timer.seconds, 'market_train_dates': market_rows,
                   'residual_train_rows': residual_rows, 'selected_rounds': dict(zip(map(str, TAUS), package['rounds'])),
                   'evaluation_keys_sha256': keys_sha256(pred.sort_values(KEYS))}
        print(f'{h}d benchmark completed', flush=True)
    pd.DataFrame(metrics).to_csv(args.out / 'metrics.csv', index=False, encoding='utf-8-sig')
    pd.DataFrame(comparisons).to_csv(args.out / 'paired_differences.csv', index=False, encoding='utf-8-sig')
    run = {'model': SLUG, 'dataset_version': str(clean.dataset_version.iloc[0]),
           'catboost': catboost_version, 'market_inputs': MARKET_INPUTS,
           'residual_numeric_inputs': asset.NUMERIC, 'residual_categorical_inputs': asset.CATEGORIES,
           'early_stop_from': str(asset.VALIDATION_START.date()),
           'evaluation': 'previously exposed conditional reconstruction', 'horizons': info}
    (args.out / 'run_info.json').write_text(json.dumps(run, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
