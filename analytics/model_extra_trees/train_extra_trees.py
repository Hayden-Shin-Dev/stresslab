"""Fit randomized trees and asymmetric split-conformal residual intervals."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import ExtraTreesRegressor

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'model_lightgbm_quantile'))
from experiment import C, benchmark
from conformal import asym_halfwidths


def fit(ctx):
    model = ExtraTreesRegressor(n_estimators=180, max_depth=10, min_samples_leaf=80,
                                max_features=.8, n_jobs=4, random_state=C.SEED)
    model.fit(C.design(ctx.train), ctx.y['train'] / ctx.scale(ctx.train))
    cal_residuals = ctx.y['cal'] / ctx.scale(ctx.cal) - model.predict(C.design(ctx.cal))
    bands = {level: asym_halfwidths(cal_residuals, level) for level in C.LEVELS}
    if not np.isfinite(list(bands.values())).all():
        raise ValueError('Insufficient calibration rows')
    return {'model': model, 'bands': bands, 'assets': ctx.assets, 'horizon': ctx.h}


def predict(package, frame):
    center = package['model'].predict(C.design(frame))
    scale = C._floor(frame.asset_scale)
    out = pd.DataFrame({'center': center * scale}, index=frame.index)
    for level, (lower, upper) in package['bands'].items():
        out[f'lo_{C.lv(level)}'] = (center - lower) * scale
        out[f'hi_{C.lv(level)}'] = (center + upper) * scale
    return out


if __name__ == '__main__':
    benchmark('model_extra_trees', fit, predict)
