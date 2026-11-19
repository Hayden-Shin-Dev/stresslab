"""Shared local evaluation for the LightGBM and ExtraTrees research models."""
import argparse
import json
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

ANALYTICS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ANALYTICS / 'model_de'))
import common as C
from compare_models import block_bootstrap
from load_gold import DEFAULT_SOURCE, load_gold
from splits import keys_sha256

KEYS = ['trading_date', 'asset_id']


def paired(candidate, baseline, name, variant, horizon):
    ref = baseline.set_index(KEYS).reindex(pd.MultiIndex.from_frame(candidate[KEYS]))
    if (len(candidate) != len(baseline)
            or not np.array_equal(candidate.target_date.to_numpy(), ref.target_date.to_numpy())
            or not np.allclose(candidate[['y_actual', *C.SHOCK_ORDER]], ref[['y_actual', *C.SHOCK_ORDER]])):
        raise ValueError(f'{name}: different evaluation rows at {horizon}d')
    y = candidate.y_actual.to_numpy()
    lo, hi = (candidate[f'{side}_90'].to_numpy() for side in ('lo', 'hi'))
    ref_lo, ref_hi = (ref[f'{side}_{variant}_90'].to_numpy() for side in ('lo', 'hi'))

    def score(lower, upper):
        return upper - lower + 20 * (np.maximum(lower - y, 0) + np.maximum(y - upper, 0))

    deltas = pd.DataFrame({
        'mae': np.abs(y - candidate.center.to_numpy()) - np.abs(y - ref.center.to_numpy()),
        'interval_score_90': score(lo, hi) - score(ref_lo, ref_hi),
        'pinball_05': (np.maximum(.05 * (y - lo), -.95 * (y - lo))
                       - np.maximum(.05 * (y - ref_lo), -.95 * (y - ref_lo))),
    })
    ci = block_bootstrap(deltas.assign(n=1).groupby(candidate.overlap_block).sum())
    return [{'horizon': horizon, 'baseline': name, 'metric': metric,
             'candidate_minus_baseline': deltas[metric].mean(), **ci.loc[metric].to_dict()}
            for metric in deltas]


def benchmark(slug, fit, predict):
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, default=ANALYTICS / 'outputs' / slug)
    args = parser.parse_args()
    clean, features, market = C.load_inputs(load_gold(DEFAULT_SOURCE))
    args.out.mkdir(parents=True)
    model_e = pd.read_parquet(C.OUT / 'model_e_predictions.parquet')
    tuned = pd.read_csv(C.OUT / 'tuning/tuning_effect.csv')
    rows, differences, info = [], [], {}
    for h in C.HORIZONS:
        print(f'{slug}: training {h}d', flush=True)
        ctx = C.Context(clean, features, market, h)
        with C.Timer() as timer:
            package = fit(ctx)
        cols = [*KEYS, 'target_date', 'overlap_block', *C.SHOCK_ORDER, ctx.ycol]
        pred = ctx.test[cols].rename(columns={ctx.ycol: 'y_actual'}).join(predict(package, ctx.test)).assign(horizon=h)
        joblib.dump(package, args.out / f'model_{h}d.joblib', compress=3)
        C.write_table(pred, args.out / f'predictions_{h}d.parquet')
        for group, mask in C.regime_masks(ctx.train, pred).items():
            if not mask.any():
                continue
            frame = pred[mask]
            y = frame.y_actual.to_numpy()
            points = C.point_metrics(y, frame.center.to_numpy())
            for level in C.LEVELS:
                tag = C.lv(level)
                lo, hi = (frame[f'{side}_{tag}'].to_numpy() for side in ('lo', 'hi'))
                rows.append({'horizon': h, 'group': group, 'level': level, 'rows': len(y),
                             'blocks': frame.overlap_block.nunique(), **points,
                             **C.interval_metrics(y, lo, hi, level), 'pinball_lower': C.pinball(y, lo, (1-level)/2)})
        differences.extend(paired(pred, model_e[model_e.horizon == h], 'Model E', 'cqr', h))
        ng = pd.read_parquet(ANALYTICS / f'outputs/model_ngboost/predictions_{h}d.parquet')
        differences.extend(paired(pred, ng, 'NGBoost', 'cqr', h))
        reference = tuned[(tuned.horizon == h) & (tuned.setting == 'tuned')].iloc[0]
        info[h] = {**ctx.summary(), 'fit_seconds': timer.seconds,
                   'evaluation_keys_sha256': keys_sha256(pred.sort_values(KEYS)),
                   'tuned_e_aggregate_reference': {
                       'mae': float(reference.mae), 'coverage_90': float(reference.cqr_coverage_90),
                       'interval_score_90': float(reference.cqr_interval_score_90)}}
        print(f'{slug}: {h}d complete · {len(pred)} evaluation rows', flush=True)
    pd.DataFrame(rows).to_csv(args.out / 'metrics.csv', index=False, encoding='utf-8-sig')
    pd.DataFrame(differences).to_csv(args.out / 'paired_differences.csv', index=False, encoding='utf-8-sig')
    metadata = {'model': slug, 'dataset_version': str(clean.dataset_version.iloc[0]),
                'inputs': C.INPUT_ORDER, 'evaluation': 'previously exposed conditional reconstruction',
                'horizons': info}
    (args.out / 'run_info.json').write_text(json.dumps(metadata, indent=2), encoding='utf-8')
