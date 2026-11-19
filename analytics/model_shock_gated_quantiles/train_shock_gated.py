"""Blend direct and factor quantiles with separately validated shock regimes."""
import argparse
import json
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

ANALYTICS = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ANALYTICS / f'model_{name}') for name in
                ('adaptive_quantile_ensemble', 'market_factor_catboost')]
import train_adaptive_ensemble as ens
import train_market_factor as factor
from experiment import C, DEFAULT_SOURCE, KEYS, keys_sha256, load_gold, paired
from conformal import conformal_quantile

SLUG = 'model_shock_gated_quantiles'
OUT = ANALYTICS / 'outputs' / SLUG
TAUS = ens.TAUS
CAL_START = pd.Timestamp('2022-01-01')


def shock_bounds(train):
    keys = train[C.SHOCK_ORDER]
    return keys.quantile(.01).to_dict(), keys.quantile(.99).to_dict()


def extreme(frame, bounds):
    lows, highs = bounds
    return np.logical_or.reduce([(frame[c].to_numpy() < lows[c]) | (frame[c].to_numpy() > highs[c])
                                 for c in C.SHOCK_ORDER])


def components(package, frame):
    qa = ens.asset.quantiles(package['direct']['models'], frame)
    qb = factor.raw_quantiles(package['factor'], frame)
    hc = package['huber']['model'].predict(ens.huber.design(frame))
    return qa, qb, hc


def choose_weights(frame, y, parts, bounds):
    scale = C._floor(frame.asset_scale)
    cw, tw, _, _ = ens.tune_blend(parts, y, scale)
    weights = {'pooled': {'center_weights': cw, 'factor_tail_weight': tw}}
    regime = extreme(frame, bounds)
    for name, selected in [('typical', ~regime), ('extreme', regime)]:
        # Use a fixed support rule, selected without 2023+ labels.
        if selected.sum() < 350 or frame.loc[selected, 'trading_date'].nunique() < 25:
            weights[name] = weights['pooled']
            continue
        cw, tw, _, _ = ens.tune_blend(tuple(x[selected] for x in parts), y[selected], scale[selected])
        weights[name] = {'center_weights': cw, 'factor_tail_weight': tw}
    return weights


def blended(package, frame, parts=None):
    is_extreme = extreme(frame, package['bounds'])
    if parts is None:
        parts = components(package, frame)
    center = np.empty(len(frame))
    q = np.empty((len(frame), len(TAUS)))
    qa, qb, huber = parts
    centers = np.column_stack((qa[:, ens.MIDDLE], qb[:, ens.MIDDLE], huber))
    for name, mask in [('typical', ~is_extreme), ('extreme', is_extreme)]:
        weights = package['weights'][name]
        center[mask] = centers[mask] @ weights['center_weights']
        weight = weights['factor_tail_weight']
        q[mask] = (1 - weight) * qa[mask] + weight * qb[mask]
    return center, q, is_extreme


def fit_corrections(frame, target, q, is_extreme):
    y = target / C._floor(frame.asset_scale)

    def fit(mask):
        return {lev: (conformal_quantile(q[mask, TAUS.index(lt)]-y[mask], (1+lev)/2),
                      conformal_quantile(y[mask]-q[mask, TAUS.index(ut)], (1+lev)/2))
                for lev, (lt, ut) in C.LEVEL_Q.items()}

    base = fit(np.ones(len(frame), dtype=bool))
    if not np.isfinite(list(base.values())).all():
        raise ValueError('Insufficient calibration observations.')
    result = {}
    for name, mask in [('typical', ~is_extreme), ('extreme', is_extreme)]:
        result[name] = fit(mask) if mask.sum() >= 350 and frame.loc[mask, 'trading_date'].nunique() >= 25 else base
    return result


def predict(package, frame):
    center, q, is_extreme = blended(package, frame)
    scale = C._floor(frame.asset_scale)
    out = pd.DataFrame({'center': center*scale, 'extreme_gate': is_extreme}, index=frame.index)
    prev_lo, prev_hi = center, center
    for level, (lt, ut) in C.LEVEL_Q.items():
        cl, ch = np.asarray(package['corrections']['typical'][level])
        el, eh = np.asarray(package['corrections']['extreme'][level])
        prev_lo = np.minimum(prev_lo, q[:, TAUS.index(lt)]-np.where(is_extreme, el, cl))
        prev_hi = np.maximum(prev_hi, q[:, TAUS.index(ut)]+np.where(is_extreme, eh, ch))
        out[f'lo_{C.lv(level)}'], out[f'hi_{C.lv(level)}'] = prev_lo*scale, prev_hi*scale
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=OUT)
    args = parser.parse_args()
    clean, fs, market = C.load_inputs(load_gold(DEFAULT_SOURCE))
    extra = ens.asset.feature_table(clean, fs, market)
    dataset = str(clean.dataset_version.iloc[0])
    args.out.mkdir(parents=True)
    rows, differences, info = [], [], {}
    for h in C.HORIZONS:
        print(f'Shock-gated quantiles: learning {h}d regime weights', flush=True)
        ctx = C.Context(clean, fs, market, h)
        for split in ('train', 'cal', 'test'):
            setattr(ctx, split, getattr(ctx, split).merge(extra, on=KEYS, how='left', validate='one_to_one'))
        direct, huber = ens.checked_members(ctx, dataset)
        saved = json.loads((factor.OUT/'run_info.json').read_text(encoding='utf-8'))
        if (saved['dataset_version'] != dataset or saved['horizons'][str(h)]['evaluation_keys_sha256']
                != keys_sha256(ctx.test.sort_values(KEYS))):
            raise ValueError('Market-factor dataset or evaluation rows differ.')
        component = joblib.load(factor.OUT/f'model_{h}d.joblib')
        package = {'direct': direct, 'factor': component, 'huber': huber,
                   'bounds': shock_bounds(ctx.train), 'horizon': h, 'assets': ctx.assets}
        dev = (ctx.cal.target_date < CAL_START).to_numpy()
        cal = (ctx.cal.trading_date >= CAL_START).to_numpy()
        parts = components(package, ctx.cal)
        package['weights'] = choose_weights(ctx.cal.loc[dev], ctx.y['cal'][dev],
                                             tuple(x[dev] for x in parts), package['bounds'])
        _, q, shock = blended(package, ctx.cal.loc[cal], tuple(x[cal] for x in parts))
        package['corrections'] = fit_corrections(ctx.cal.loc[cal], ctx.y['cal'][cal], q, shock)
        joblib.dump(package, args.out/f'model_{h}d.joblib', compress=3)
        keys = [*KEYS, 'target_date', 'overlap_block', *C.SHOCK_ORDER, ctx.ycol]
        pred = ctx.test[keys].rename(columns={ctx.ycol: 'y_actual'}).join(predict(package, ctx.test)).assign(horizon=h)
        C.write_table(pred, args.out/f'predictions_{h}d.parquet')
        rows.extend(ens.asset.summarize(h, 'Shock-gated quantiles', pred, ctx.train))
        for name, slug in [('Direct CatBoost', 'model_catboost_asset_state'),
                           ('Market-factor CatBoost', 'model_market_factor_catboost'),
                           ('Huber interactions', 'model_huber_interactions')]:
            ref = factor.reference(slug, h)
            rows.extend(ens.asset.summarize(h, name, ref, ctx.train, 'stored'))
            comparisons = paired(pred, ref, name, 'stored', h)
            differences.extend({**row, 'group': 'all'} for row in comparisons)
            subgroup = pred[pred.extreme_gate].reset_index(drop=True)
            subgroup_ref = ref.merge(subgroup[KEYS], on=KEYS, validate='one_to_one')
            extreme_rows = paired(subgroup, subgroup_ref, name, 'stored', h)
            differences.extend({**row, 'group': 'extreme_any_shock'} for row in extreme_rows)
        info[h] = {**ctx.summary(), 'evaluation_keys_sha256': keys_sha256(pred.sort_values(KEYS)),
                   'weight_rows_2020_2021': int(dev.sum()), 'calibration_rows_2022': int(cal.sum()),
                   'extreme_calibration_rows': int(shock.sum()), 'weights': package['weights']}
        print(f'{h}d complete: {package["weights"]}', flush=True)
    pd.DataFrame(rows).to_csv(args.out/'metrics.csv', index=False, encoding='utf-8-sig')
    pd.DataFrame(differences).to_csv(args.out/'paired_differences.csv', index=False, encoding='utf-8-sig')
    run = {'model': SLUG, 'dataset_version': dataset, 'evaluation': 'previously exposed conditional reconstruction',
           'horizons': info}
    (args.out/'run_info.json').write_text(json.dumps(run, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
