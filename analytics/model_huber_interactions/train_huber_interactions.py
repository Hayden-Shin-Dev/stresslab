"""Robust linear stress response with state–shock interactions."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import HuberRegressor
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'model_lightgbm_quantile'))
from experiment import C, benchmark
from conformal import asym_halfwidths


def design(frame):
    x = C.design(frame)
    n_shocks = len(C.SHOCK_ORDER)
    effects = x[:, :n_shocks, None] * x[:, None, n_shocks:]
    return np.column_stack((x, effects.reshape(len(x), -1)))


def fit(ctx):
    model = make_pipeline(StandardScaler(), HuberRegressor(alpha=20., epsilon=1.35, max_iter=800))
    model.fit(design(ctx.train), ctx.y['train'] / ctx.scale(ctx.train))
    residuals = ctx.y['cal'] / ctx.scale(ctx.cal) - model.predict(design(ctx.cal))
    bands = {level: asym_halfwidths(residuals, level) for level in C.LEVELS}
    if not np.isfinite(list(bands.values())).all():
        raise ValueError('Insufficient calibration rows')
    return {'model': model, 'bands': bands, 'assets': ctx.assets, 'horizon': ctx.h}


def predict(package, frame):
    center = package['model'].predict(design(frame))
    scale = C._floor(frame.asset_scale)
    out = pd.DataFrame({'center': center * scale}, index=frame.index)
    for level, (lower, upper) in package['bands'].items():
        out[f'lo_{C.lv(level)}'] = (center - lower) * scale
        out[f'hi_{C.lv(level)}'] = (center + upper) * scale
    return out


if __name__ == '__main__':
    benchmark('model_huber_interactions', fit, predict)
