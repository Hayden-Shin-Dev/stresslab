"""80/90% empirical residual intervals on the frozen Gold20 evaluation rows."""
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from .core import SHOCKS, anchors
from .finalize_model import BoundedFactor
from .gold_ready import read_gold, save, sha
from .rebuild_fixed_model import training


def interval_metrics(z):
    y, lo, hi = z.actual.to_numpy(), z.lower.to_numpy(), z.upper.to_numpy()
    alpha = 1-float(z.nominal.iloc[0])
    covered = (y>=lo)&(y<=hi)
    crash = y<=-5
    return dict(n=len(z),dates=int(z.date.nunique()),stocks=int(z.asset.nunique()),
        coverage=float(covered.mean()),mean_full_width_pp=float((hi-lo).mean()),
        median_full_width_pp=float(np.median(hi-lo)),lower_breach=float((y<lo).mean()),
        upper_breach=float((y>hi).mean()),
        interval_score=float(np.mean(hi-lo+2/alpha*np.maximum(lo-y,0)+2/alpha*np.maximum(y-hi,0))),
        crash_n=int(crash.sum()),
        crash_lower_breach=float((y[crash]<lo[crash]).mean()) if crash.any() else None,
        crash_coverage=float(covered[crash].mean()) if crash.any() else None,
        crash_missed_loss_pp=float(np.maximum(lo[crash]-y[crash],0).mean()) if crash.any() else None)


def run(directory):
    out = Path(directory)
    preserved = {name:sha(out/name) for name in ['model.joblib','predictions.parquet','gold.parquet','provenance.parquet']}
    cfg = json.loads((out/'protocol.json').read_text(encoding='utf8'))
    _, f, _ = read_gold(out/'gold.parquet',out/'provenance.parquet',out/'certificate.json')
    data = f.dropna(subset=SHOCKS+['target','end_date','label_known_by'])
    previous = pd.read_parquet(out/'predictions.parquet')
    policy = dict(method='Per-stock quantiles of previous-year out-of-sample residuals divided by ex-ante 20/60-day mixed volatility scale',
        formula='lower=center+scale*q(alpha/2); upper=center+scale*q(1-alpha/2)',
        quantile_method='numpy linear empirical quantiles; no guaranteed conformal coverage',
        scale='sqrt(5*(daily_vol20^2+daily_vol60^2)/2), computed at state date',
        calibration='Previous calendar year, labels matured before test year minus 20 calendar days; every sixth eligible date',
        levels=[.8,.9],center_changed=False,model_selection=False,independent_blind=False,
        scope='Historical conditional reconstruction with observed shocks supplied retrospectively; not validation of arbitrary hypothetical scenarios',
        preserved_sha256=preserved)
    save(out/'interval_protocol.json',policy)
    frames, calibration_details, calibration_rows, splits = [], [], [], []
    for year in cfg['years']:
        train = training(data,pd.Timestamp(year-1,1,1))
        counts = train.groupby('asset').size()
        eligible = counts[counts>=cfg['minimum_training_rows_per_stock']].index
        train = train[train.asset.isin(eligible)]
        model = BoundedFactor(cfg['config'],cfg['sectors']).fit(train)
        cal = anchors(training(data[data.date>=pd.Timestamp(year-1,1,1)],pd.Timestamp(year,1,1)))
        cal = cal[cal.asset.isin(eligible)].copy()
        test = previous[previous.year.eq(year)].merge(f[['date','asset','scale']],on=['date','asset'],validate='one_to_one')
        same = previous[previous.year.eq(year)].merge(data,on=['date','asset'],suffixes=('','_feature'),validate='one_to_one')
        np.testing.assert_allclose(model.predict(same),same.center,rtol=0,atol=1e-10)
        assert train.end_date.max()<cal.date.min() and cal.end_date.max()<test.date.min()
        assert (pd.to_datetime(cal.label_known_by,utc=True)<pd.Timestamp(year,1,1,tz='UTC')).all()
        cal['prediction'] = model.predict(cal)
        cal['normalized_residual'] = (cal.target-cal.prediction)/cal.scale
        assert np.isfinite(cal.normalized_residual).all()
        calibration_rows.append(cal.assign(evaluation_year=year))
        for asset,z in test.groupby('asset'):
            c = cal[cal.asset.eq(asset)]
            if len(c)<2:
                raise ValueError(f'Cannot estimate intervals without calibration: {year}/{asset}')
            for level in policy['levels']:
                tail = (1-level)/2
                qlo,qhi = np.quantile(c.normalized_residual,[tail,1-tail],method='linear')
                r = z.copy();r['nominal']=level;r['calibration_n']=len(c)
                r['lower']=r.center+r.scale*qlo;r['upper']=r.center+r.scale*qhi
                assert np.isfinite(r[['lower','upper']]).all().all() and r.upper.ge(r.lower).all()
                frames.append(r)
                calibration_details.append(dict(year=year,asset=asset,nominal=level,n=len(c),qlo=float(qlo),qhi=float(qhi)))
        splits.append(dict(year=year,train_label_end=str(train.end_date.max().date()),
            calibration_start=str(cal.date.min().date()),calibration_label_end=str(cal.end_date.max().date()),
            test_start=str(test.date.min().date()),test_rows=len(test)))
        print('interval fold',year,'test',len(test),'calibration per stock',cal.groupby('asset').size().min(),cal.groupby('asset').size().max(),flush=True)
    result = pd.concat(frames,ignore_index=True)
    for level,z in result.groupby('nominal'):
        assert len(z)==len(previous)
        keys=z.merge(previous,on=['date','asset'],validate='one_to_one',suffixes=('','_old'))
        np.testing.assert_allclose(keys.center,keys.center_old,rtol=0,atol=0)
        np.testing.assert_allclose(keys.actual,keys.actual_old,rtol=0,atol=0)
    result.to_parquet(out/'interval_predictions.parquet',index=False)
    pd.concat(calibration_rows).to_parquet(out/'interval_calibration.parquet',index=False)
    summary=dict(method=policy,overall={str(int(k*100)):interval_metrics(z) for k,z in result.groupby('nominal')},
        by_year={str(y):{str(int(k*100)):interval_metrics(z) for k,z in g.groupby('nominal')} for y,g in result.groupby('year')},
        by_stock={a:{str(int(k*100)):interval_metrics(z) for k,z in g.groupby('nominal')} for a,g in result.groupby('asset')},
        calibration_counts=dict(min=int(result.calibration_n.min()),max=int(result.calibration_n.max())),
        verification=dict(same_1600_rows=len(previous)==1600,centers_identical=True,time_boundaries_passed=True,
            original_artifacts_unchanged=all(sha(out/k)==v for k,v in preserved.items())),
        splits=splits,calibration_quantiles=calibration_details,api_intervals_enabled=False)
    assert all(summary['verification'].values())
    save(out/'interval_metrics.json',summary)
    print(json.dumps(summary['overall'],indent=2))
    return summary


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--out',required=True)
    run(parser.parse_args().out)
