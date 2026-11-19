"""Local StressLab models for the conditional probability of 5% and 10% losses."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from catboost import CatBoostClassifier, __version__ as catboost_version
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import log_loss, roc_auc_score

ANALYTICS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ANALYTICS / 'model_ngboost'))
import train as reference

C = reference.C
LOSSES = (5, 10)
OUT = ANALYTICS / 'outputs/model_catboost_loss_classifier'


def event(y, loss):
    return y <= 100 * np.log1p(-loss / 100)


def fit(ctx):
    x_train, x_cal = C.design(ctx.train), C.design(ctx.cal)
    classifiers, calibrators = {}, {}
    with C.Timer() as timer:
        for loss in LOSSES:
            model = CatBoostClassifier(
                iterations=300, depth=4, learning_rate=.03, thread_count=4,
                random_seed=C.SEED, verbose=False, allow_writing_files=False,
            )
            model.fit(x_train, event(ctx.y['train'], loss))
            margin = model.predict(x_cal, prediction_type='RawFormulaVal').reshape(-1, 1)
            calibrator = LogisticRegression().fit(margin, event(ctx.y['cal'], loss))
            classifiers[loss], calibrators[loss] = model, calibrator
    return {'models': classifiers, 'calibrators': calibrators, 'inputs': C.INPUT_ORDER,
            'horizon': ctx.h, 'assets': ctx.assets, 'train_seconds': timer.seconds}


def predict(package, frame):
    x = C.design(frame)
    columns = {}
    for loss, model in package['models'].items():
        margin = model.predict(x, prediction_type='RawFormulaVal').reshape(-1, 1)
        columns[loss] = package['calibrators'][loss].predict_proba(margin)[:, 1]
    # Project inversions to the same midpoint for nested loss events.
    lower, higher = (columns[loss] for loss in LOSSES)
    crossed = higher > lower
    midpoint = (lower + higher) / 2
    return {5: np.where(crossed, midpoint, lower), 10: np.where(crossed, midpoint, higher)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=OUT)
    args = parser.parse_args()
    clean, fs, market = C.load_inputs(reference.load_gold(reference.DEFAULT_SOURCE))
    args.out.mkdir(parents=True)
    metrics, reliability, paired, info = [], [], [], {}
    for h in C.HORIZONS:
        print(f'CatBoost loss classifier: fitting {h}d', flush=True)
        ctx = C.Context(clean, fs, market, h)
        package = fit(ctx)
        joblib.dump(package, args.out / f'catboost_loss_classifier_{h}d.joblib', compress=3)
        baseline = pd.read_parquet(ANALYTICS / f'outputs/model_ngboost/predictions_{h}d.parquet')
        keys = [*reference.KEYS, 'target_date', 'overlap_block', 'asset_scale', *C.SHOCK_ORDER, ctx.ycol]
        pred = ctx.test[keys].rename(columns={ctx.ycol: 'y_actual'}).assign(horizon=h)
        aligned = baseline.set_index(reference.KEYS).reindex(pd.MultiIndex.from_frame(pred[reference.KEYS]))
        match = pred[['y_actual', 'asset_scale', *C.SHOCK_ORDER]].to_numpy()
        if (len(aligned) != len(baseline) or
                not np.array_equal(aligned['target_date'].to_numpy(), pred['target_date'].to_numpy()) or
                not np.allclose(aligned[['y_actual', 'asset_scale', *C.SHOCK_ORDER]].to_numpy(), match)):
            raise ValueError(f'{h}d evaluation rows differ from NGBoost')
        for loss, probability in predict(package, ctx.test).items():
            col = f'prob_loss_{loss}pct'
            pred[col] = probability
            y = event(ctx.y['test'], loss)
            briers = {}
            for label, p in [
                ('CatBoost classifier', probability), ('NGBoost', aligned[col].to_numpy()),
                ('Training event rate', np.full(len(y), event(ctx.y['train'], loss).mean())),
            ]:
                briers[label] = (p - y) ** 2
                metrics.append({'horizon': h, 'loss_pct': loss, 'model': label, 'rows': len(y),
                                'event_rate': y.mean(), 'mean_probability': p.mean(),
                                'brier': briers[label].mean(), 'log_loss': log_loss(y, p),
                                'roc_auc': roc_auc_score(y, p)})
            for label in ('NGBoost', 'Training event rate'):
                delta = briers['CatBoost classifier'] - briers[label]
                blocks = pd.DataFrame({'delta': delta, 'n': 1}).groupby(pred['overlap_block']).sum()
                ci = reference.block_bootstrap(blocks).loc['delta']
                paired.append({'horizon': h, 'loss_pct': loss, 'baseline': label,
                               'brier_difference': delta.mean(), 'ci_lo': ci['lo'], 'ci_hi': ci['hi']})
        reliability.extend(reference.loss_metrics(pred))
        C.write_table(pred, args.out / f'predictions_{h}d.parquet')
        info[h] = {**ctx.summary(), 'train_seconds': package['train_seconds'],
                   'evaluation_keys_sha256': reference.keys_sha256(pred.sort_values(reference.KEYS))}
        print(f'CatBoost loss classifier: completed {h}d', flush=True)
    for name, rows in [('metrics', metrics), ('loss_calibration', reliability), ('paired_differences', paired)]:
        pd.DataFrame(rows).to_csv(args.out / f'{name}.csv', index=False, encoding='utf-8-sig')
    run = {'model': 'CatBoost loss classifier', 'catboost': catboost_version, 'horizons': info,
           'dataset_version': str(clean['dataset_version'].iloc[0]),
           'evaluation': 'previously exposed conditional shock reconstruction'}
    (args.out / 'run_info.json').write_text(json.dumps(run, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
