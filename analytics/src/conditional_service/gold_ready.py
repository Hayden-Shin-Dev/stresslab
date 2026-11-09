"""Local Gold -> fixed sector Ridge -> evidence and scenario API.

No Fabric/Azure writes. No hyperparameter search or invented release clocks.
Run from the research workspace; artifacts are outside the source checkout.
"""
import argparse
import hashlib
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from .core import MACRO, SHOCKS, STATE, ASSET, features, anchors, market_search, validate
from .finalize_model import BoundedFactor
from .rebuild_fixed_model import training

CONFIG = dict(alpha=300, dev=10, years=None, sector=True)
# Explicit research taxonomy for the seven stocks absent from the old bundle.
# This does not modify Gold sector_id or assert historical official classifications.
ADDITIONAL_SECTORS = {
    '005935': 'semi', '012450': 'aerospace', '028260': 'diversified',
    '034020': 'power_equipment', '034730': 'holding',
    '373220': 'battery', '402340': 'investment_holding',
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, obj):
    Path(path).write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str,
                                   allow_nan=False), encoding='utf8')


def prepare(root, out):
    """Build an isolated corrected local input, not a rewrite of Fabric Gold."""
    root, out = Path(root), Path(out)
    out.mkdir(parents=True, exist_ok=True)
    cloud = root/'reports/fabric_gold_review_20261109/gold_stock_market_daily_v11.parquet'
    reference = root/'exports/seongjin_gold_v1_1/gold_stress_daily.parquet'
    metadata = json.loads(reference.with_name('metadata.json').read_text(encoding='utf8'))
    if sha(reference) != metadata['data_sha256']:
        raise ValueError('Archived verified-price export hash changed')
    bridge = json.loads((root/'reports/price_bridge_20261102/cloud_bridge_verification.json').read_text())
    if bridge['status'] != 'passed' or bridge['assets'] != 20:
        raise ValueError('Price bridge audit missing')
    g, ref = pd.read_parquet(cloud), pd.read_parquet(reference)
    g['trading_date'] = pd.to_datetime(g.trading_date)
    ref['trading_date'] = pd.to_datetime(ref.trading_date)
    if g.duplicated(['asset_id', 'trading_date']).any():
        raise ValueError('Duplicate Gold keys')
    assets = sorted(g.asset_id.unique())
    if assets != sorted(ref.asset_id.unique()):
        raise ValueError('Gold universe differs from verified price export')
    z = g.merge(ref, on=['trading_date', 'asset_id'], suffixes=('', '_ref'), validate='one_to_one')
    for col in ['close', 'volume', 'kospi_close']:
        np.testing.assert_allclose(z[col], z[col+'_ref'], equal_nan=True, atol=1e-8, rtol=0)
    # Reuse only the identical price rows covered by the historical price verification.
    local = z[list(g)].copy()
    local['price_basis'] = z.price_basis_ref
    local['adjustment_version'] = z.adjustment_version_ref
    # Preserve suspensions/corporate-action quarantine. Macro missingness is re-evaluated.
    blocked = z.quality_status.eq('quarantined') | z.quality_status_ref.eq('quarantined')
    local['quality_status'] = np.where(blocked, 'quarantined', 'valid')
    provenance_path = root/'reports/service_scope_20261105/observation_provenance.parquet'
    provenance = pd.read_parquet(provenance_path)
    provenance['date'] = pd.to_datetime(provenance.date)
    for name in MACRO:
        q = provenance[provenance.source.eq(name)].set_index('date')
        if not q.index.is_unique:
            raise ValueError('Duplicate publication evidence')
        local[name] = local.trading_date.map(q.value.where(q.verified))
        local[name+'_observation_date'] = local.trading_date.map(q.observation_date.where(q.verified))
        local[name+'_available_at'] = None
        local[name+'_observed_at'] = None
    local['dataset_version'] = 'local-fabric20-pit-20261109'
    validate(local, research=True)  # Evidence is validated separately; no fake timestamps.
    local.to_parquet(out/'gold.parquet', index=False)
    provenance.to_parquet(out/'provenance.parquet', index=False)
    certificate = dict(
        gold_sha256=sha(out/'gold.parquet'), provenance_sha256=sha(out/'provenance.parquet'),
        price_reference_sha256=sha(reference), source_gold_sha256=sha(cloud),
        source_provenance_sha256=sha(provenance_path),
        price_basis='Reuse of identical archived KRX adjusted price rows and verified bridge; not a new full corporate-event ledger',
        exact_publication_clocks=False, availability_policy='Official conservative date upper bounds; maximum observation age 10 calendar days',
        source_gold_rows=len(g), local_rows=len(local), excluded_unverified_new_rows=len(g)-len(local),
        assets=assets, quarantine_rows=int(blocked.sum()), cloud_changed=False)
    save(out/'certificate.json', certificate)
    return certificate


def read_gold(gold_path, provenance_path=None, certificate_path=None):
    """Strict runtime adapter; uncertified nulls cannot silently become model inputs."""
    g = pd.read_parquet(gold_path)
    g['trading_date'] = pd.to_datetime(g.trading_date)
    if provenance_path is not None:
        cert = json.loads(Path(certificate_path).read_text(encoding='utf8'))
        if sha(gold_path) != cert['gold_sha256'] or sha(provenance_path) != cert['provenance_sha256']:
            raise ValueError('Gold/publication certificate hash mismatch')
        validate(g, research=True)
        p = pd.read_parquet(provenance_path)
    else:
        # Finished Gold can supply exact availability fields directly.
        validate(g, research=False)
        rows = []
        for name in MACRO:
            q = g.drop_duplicates('trading_date')
            rows.append(pd.DataFrame(dict(date=q.trading_date, source=name, value=q[name],
                observation_date=q[name+'_observation_date'], known_by=q[name+'_available_at'],
                source_ref=q.source_ref, verified=q[name].notna())))
        p = pd.concat(rows, ignore_index=True)
    p['date'] = pd.to_datetime(p.date)
    p['observation_date'] = pd.to_datetime(p.observation_date)
    p['known_by'] = pd.to_datetime(p.known_by, utc=True)
    if p.duplicated(['date','source']).any():
        raise ValueError('Duplicate publication provenance keys')
    for name in MACRO:
        q = p[p.source.eq(name)].set_index('date')
        value = g.trading_date.map(q.value)
        known = g.trading_date.map(q.known_by)
        observed = g.trading_date.map(q.observation_date)
        verified = g.trading_date.map(q.verified).fillna(False)
        present = g[name].notna()
        cutoff = pd.to_datetime(g.trading_date, utc=True)+pd.Timedelta(hours=6, minutes=30)
        age = (g.trading_date-observed).dt.days
        good = verified & known.notna() & known.le(cutoff) & age.between(0,10)
        if (present & ~good).any() or not np.allclose(g.loc[present,name],value[present],equal_nan=False):
            raise ValueError('Unverified or inconsistent macro input: '+name)
        recorded = pd.to_datetime(g[name+'_observation_date'])
        if (present & recorded.ne(observed)).any():
            raise ValueError('Observation date mismatch: '+name)
    f = features(g)
    days = pd.DatetimeIndex(sorted(g.trading_date.unique()))
    cutoffs = []
    for name in MACRO[:4]:
        k = p[p.source.eq(name)].set_index('date').known_by.reindex(days)
        cutoffs.extend([k, k.shift(-5)])
    label_times = pd.concat(cutoffs, axis=1).max(axis=1)
    f['label_known_by'] = f.date.map(label_times)
    return g, f, p


def metrics(z, column='center'):
    y, pred = z.actual.to_numpy(), z[column].to_numpy()
    crash, nz = y <= -5, y != 0
    return dict(n=len(z), dates=int(z.date.nunique()), stocks=int(z.asset.nunique()),
        mae_pp=float(np.abs(y-pred).mean()), rmse_pp=float(np.sqrt(np.mean((y-pred)**2))),
        direction=float(np.mean(np.sign(y[nz])==np.sign(pred[nz]))) if nz.any() else None,
        crash_n=int(crash.sum()),
        crash_direction=float(np.mean(pred[crash]<0)) if crash.any() else None,
        crash_magnitude_caught=float(np.mean(pred[crash]<=-5)) if crash.any() else None,
        crash_underestimate_pp=float(np.maximum(pred[crash]-y[crash],0).mean()) if crash.any() else None)


def refit(root, out):
    root, out = Path(root), Path(out)
    g, f, p = read_gold(out/'gold.parquet',out/'provenance.parquet',out/'certificate.json')
    old_path = root/'reports/web_model_selection_20261105/selected_service_bundle.joblib'
    old = joblib.load(old_path)
    assets = sorted(g.asset_id.unique())
    sectors = {a: old['sectors'].get(a,ADDITIONAL_SECTORS.get(a)) for a in assets}
    if not all(sectors.values()):
        raise ValueError('Sector assignment missing')
    protocol = dict(config=CONFIG, assets=assets, sectors=sectors, years=[2023,2024,2025,2026],
        source_model_sha256=sha(old_path), tuning=False, independent_blind=False,
        minimum_training_rows_per_stock=100, fit_policy='Prior-year reserved calibration; train labels before prior January minus 20 days',
        sectors_policy='Frozen old bundle taxonomy plus explicit seven-stock research mapping; not official historical industry labels',
        target='Five KRX sessions; actual observed changes of PIT macro curves supplied retrospectively; not causal or ex-ante prediction',
        market_state_in_B=False, universe_pooling='One current-Gold cohort; old model used two cohorts')
    save(out/'protocol.json', protocol)  # Write before examining evaluation results.
    data = f.dropna(subset=SHOCKS+['target','end_date','label_known_by'])
    rows, splits = [], []
    for year in protocol['years']:
        train = training(data,pd.Timestamp(year-1,1,1))
        counts = train.groupby('asset').size()
        supported = counts[counts>=100].index
        train = train[train.asset.isin(supported)]
        test = anchors(data[(data.date>=pd.Timestamp(year,1,1)) & (data.date<pd.Timestamp(year+1,1,1))])
        excluded = sorted(set(test.asset)-set(supported))
        test = test[test.asset.isin(supported)].copy()
        assert train.end_date.max() < test.date.min()
        model = BoundedFactor(CONFIG.copy(),sectors).fit(train)
        z = test[['date','end_date','asset','target',*SHOCKS]].rename(columns={'target':'actual'}).copy()
        z['center'] = model.predict(test)
        z['zero'] = 0.
        means = train.groupby(train.asset.map(sectors)).target.mean()
        z['sector_mean'] = z.asset.map(sectors).map(means)
        z['year'] = year
        rows.append(z)
        splits.append(dict(year=year, training_rows=len(train), training_dates=train.date.nunique(),
            label_end=train.end_date.max(), latest_label_known=train.label_known_by.max(),
            evaluation_rows=len(test), evaluation_dates=test.date.nunique(), excluded_stocks=excluded,
            training_counts={a:int(n) for a,n in counts.items()}))
        print('fixed Gold20 fold',year,len(test),'excluded',excluded,flush=True)
    result = pd.concat(rows,ignore_index=True)
    result.to_parquet(out/'predictions.parquet',index=False)
    report = {c:metrics(result,c) for c in ['center','zero','sector_mean']}
    report['mae_improvement_vs_zero_pct'] = 100*(1-report['center']['mae_pp']/report['zero']['mae_pp'])
    report['by_year'] = {str(y):{c:metrics(z,c) for c in ['center','zero','sector_mean']} for y,z in result.groupby('year')}
    previous = pd.read_parquet(root/'reports/web_model_selection_20261105/reproduced_sector_predictions.parquet')
    common = result.merge(previous[['date','asset','actual','reproduced_sector']],on=['date','asset'],suffixes=('','_old'),validate='one_to_one')
    np.testing.assert_allclose(common.actual,common.actual_old,rtol=0,atol=1e-8)
    report['same_dates_old_overlap'] = {c:metrics(common,c) for c in ['center','reproduced_sector','zero']}
    # Dependence across stocks: bootstrap date blocks, not individual rows.
    deltas = result.assign(delta=abs(result.actual)-abs(result.actual-result.center)).groupby('date').delta.mean().to_numpy()
    rng = np.random.default_rng(20261109)
    boot = []
    for _ in range(2000):
        starts = rng.integers(0,len(deltas),int(np.ceil(len(deltas)/4)))
        idx = np.concatenate([(s+np.arange(4))%len(deltas) for s in starts])[:len(deltas)]
        boot.append(float(deltas[idx].mean()))
    report['date_block_mae_gain_pp'] = dict(mean=float(deltas.mean()),ci95=np.quantile(boot,[.025,.975]).tolist(),block=4)
    stock_metrics = {a:{c:metrics(z,c) for c in ['center','zero','sector_mean']} for a,z in result.groupby('asset')}
    save(out/'stock_metrics.json',stock_metrics)
    save(out/'metrics.json',report)
    save(out/'splits.json',splits)
    common_dates = f.groupby('date').asset.nunique()
    day = common_dates[common_dates.eq(len(assets))].index.max()
    if pd.isna(day):
        raise ValueError('No complete common snapshot for current Gold universe')
    train = training(data,day)
    assert set(train.asset)==set(assets)
    final = BoundedFactor(CONFIG.copy(),sectors).fit(train)
    snapshot = f[f.date.eq(day)].copy()
    snapshot[SHOCKS] = 0.
    evidence = data[(data.end_date<day)&(pd.to_datetime(data.label_known_by,utc=True)<=day.tz_localize('Asia/Seoul')+pd.Timedelta(hours=15,minutes=30))]
    bundle = dict(version='gold20-fixed-sector-ridge-20261109', model=final, sectors=sectors,
        names={a:old['names'].get(a,a) for a in assets}, assets=assets, snapshot=snapshot,
        history=evidence, training_reference=train, validation=stock_metrics,
        config=CONFIG.copy(), model_basis_date=str(day.date()), training_label_end=str(train.end_date.max().date()),
        gold_sha256=sha(out/'gold.parquet'), provenance=p, report=report, protocol=protocol)
    joblib.dump(bundle,out/'model.joblib')
    save(out/'artifact.json',dict(model_sha256=sha(out/'model.joblib'),gold_sha256=bundle['gold_sha256'],
        basis_date=bundle['model_basis_date'],training_label_end=bundle['training_label_end'],assets=assets,
        production_promoted=False,config=CONFIG))
    return report


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--root',required=True)
    parser.add_argument('--out',required=True)
    args=parser.parse_args()
    prepare(args.root,args.out)
    report=refit(args.root,args.out)
    print(json.dumps({k:report[k] for k in ['center','zero','mae_improvement_vs_zero_pct']},indent=2))


if __name__=='__main__':
    main()
