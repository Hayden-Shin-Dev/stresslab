"""Fit seven LightGBM quantiles and calibrate with held-out CQR."""
import numpy as np
import pandas as pd
import lightgbm as lgb
from joblib import Parallel, delayed

from experiment import C, benchmark
from conformal import cqr_adjustment
from model_e_catboost_quantile_conformal import TAUS


def _fit_quantile(x, y, tau):
    params = {'objective': 'quantile', 'alpha': tau, 'learning_rate': .035,
              'num_leaves': 15, 'min_data_in_leaf': 200, 'verbosity': -1,
              'num_threads': 1, 'seed': C.SEED, 'deterministic': True, 'force_col_wise': True}
    return lgb.train(params, lgb.Dataset(x, label=y), num_boost_round=300)


def _quantiles(models, frame):
    x = C.design(frame)
    return np.sort(np.column_stack([m.predict(x, num_threads=1) for m in models]), axis=1)


def fit(ctx):
    x = C.design(ctx.train)
    y = ctx.y['train'] / ctx.scale(ctx.train)
    models = Parallel(n_jobs=4, prefer='threads')(delayed(_fit_quantile)(x, y, tau) for tau in TAUS)
    q = _quantiles(models, ctx.cal)
    y_cal = ctx.y['cal'] / ctx.scale(ctx.cal)
    adjustments = {level: cqr_adjustment(y_cal, q[:, TAUS.index(lo)], q[:, TAUS.index(hi)], level)
                   for level, (lo, hi) in C.LEVEL_Q.items()}
    if not np.isfinite(list(adjustments.values())).all():
        raise ValueError('Insufficient calibration rows')
    return {'models': models, 'adjustments': adjustments, 'assets': ctx.assets, 'horizon': ctx.h}


def predict(package, frame):
    q = _quantiles(package['models'], frame)
    scale = C._floor(frame.asset_scale)
    center = q[:, TAUS.index(.5)]
    out = pd.DataFrame({'center': center * scale}, index=frame.index)
    previous_lo, previous_hi = center, center
    for level, (qlo, qhi) in C.LEVEL_Q.items():
        k = package['adjustments'][level]
        lo = np.minimum(previous_lo, q[:, TAUS.index(qlo)] - k)
        hi = np.maximum(previous_hi, q[:, TAUS.index(qhi)] + k)
        out[f'lo_{C.lv(level)}'], out[f'hi_{C.lv(level)}'] = lo * scale, hi * scale
        previous_lo, previous_hi = lo, hi
    return out


if __name__ == '__main__':
    benchmark('model_lightgbm_quantile', fit, predict)
