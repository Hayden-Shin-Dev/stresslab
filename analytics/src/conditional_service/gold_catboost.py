"""Restore the user's per-stock CatBoost choice on exactly the Gold20 rows."""
import argparse
import json
import math
import shutil
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from catboost import CatBoostRegressor

from .core import STATE, ASSET, SHOCKS, anchors
from .gold_ready import read_gold, save, sha, metrics
from .gold_ready_intervals import interval_metrics
from .rebuild_fixed_model import training

FEATURES = STATE+ASSET+SHOCKS
PARAMS = dict(iterations=150, depth=3, learning_rate=.04,
    loss_function='Quantile:alpha=0.5', random_seed=20261104, thread_count=2,
    verbose=False, allow_writing_files=False)


class StockCatBoost:
    def fit(self, data):
        self.assets = sorted(data.asset.unique())
        self.models = {}
        for asset,z in data.groupby('asset'):
            self.models[asset] = CatBoostRegressor(**PARAMS).fit(z[FEATURES].to_numpy(),z.target/z.scale)
        return self

    def predict(self, data):
        result = np.empty(len(data))
        for asset in data.asset.unique():
            mask = data.asset.eq(asset).to_numpy()
            result[mask] = self.models[asset].predict(data.loc[mask,FEATURES].to_numpy())*data.loc[mask,'scale'].to_numpy()
        return result

    def contributions(self, row, shocks):
        """Exact four-factor Shapley allocation relative to zero changes.

        Keep the observed state/asset features fixed. Interactions are allocated
        once across all 24 orderings. This is model arithmetic, not causal SHAP.
        """
        values = pd.concat([row.copy() for _ in range(16)],ignore_index=True)
        for i,s in enumerate(SHOCKS):
            values[s] = [shocks[s] if mask & (1<<i) else 0. for mask in range(16)]
        predictions = self.predict(values)
        parts = {}
        for i,s in enumerate(SHOCKS):
            part = 0.
            for mask in range(16):
                if mask & (1<<i): continue
                size = mask.bit_count()
                weight = math.factorial(size)*math.factorial(3-size)/math.factorial(4)
                part += weight*(predictions[mask|(1<<i)]-predictions[mask])
            parts[s] = float(part)
        np.testing.assert_allclose(sum(parts.values()),predictions[15]-predictions[0],atol=1e-8)
        return parts


def run(source, destination):
    source, out = Path(source), Path(destination)
    out.mkdir(parents=True,exist_ok=True)
    protected = {str(source/name):sha(source/name) for name in ['gold.parquet','provenance.parquet','model.joblib','predictions.parquet','interval_predictions.parquet']}
    cfg = json.loads((source/'protocol.json').read_text(encoding='utf8'))
    _,f,_ = read_gold(source/'gold.parquet',source/'provenance.parquet',source/'certificate.json')
    data = f.dropna(subset=SHOCKS+['target','end_date','label_known_by'])
    previous = pd.read_parquet(source/'predictions.parquet')
    old_intervals = pd.read_parquet(source/'interval_predictions.parquet')
    save(out/'protocol.json',dict(model='per_stock_catboost',params=PARAMS,features=FEATURES,
        source_model='three_model_intervals.py frozen CatBoost settings',tuning=False,
        target='target/scale; prediction multiplied by ex-ante scale',
        evaluation='Exact saved Gold20 1600 keys; reused development evaluation, not independent blind',
        intervals='Same per-stock previous-year OOS normalized residual quantiles as Ridge; no evaluation tuning',
        user_choice='CatBoost service model; comparative metrics do not constitute guaranteed effect direction',
        protected_sha256=protected))
    pieces, calibration, intervals, splits, folds = [], [], [], [], {}
    for year in cfg['years']:
        train = training(data,pd.Timestamp(year-1,1,1))
        counts = train.groupby('asset').size()
        eligible = counts[counts>=cfg['minimum_training_rows_per_stock']].index
        train = train[train.asset.isin(eligible)]
        keys = previous[previous.year.eq(year)]
        test = keys[['date','asset']].merge(data,on=['date','asset'],validate='one_to_one')
        cal = anchors(training(data[data.date>=pd.Timestamp(year-1,1,1)],pd.Timestamp(year,1,1)))
        cal = cal[cal.asset.isin(eligible)].copy()
        assert train.end_date.max()<cal.date.min() and cal.end_date.max()<test.date.min()
        model = StockCatBoost().fit(train);folds[year]=model
        for label,d in [('test',test),('calibration',cal)]:
            z=d[['date','end_date','asset','target','scale']].rename(columns={'target':'actual'}).copy()
            z['center']=model.predict(d);z['year']=year
            (pieces if label=='test' else calibration).append(z)
        z=pieces[-1];c=calibration[-1]
        c['normalized_residual']=(c.actual-c.center)/c.scale
        for asset,t in z.groupby('asset'):
            cr=c[c.asset.eq(asset)]
            for level in [.8,.9]:
                tail=(1-level)/2;qlo,qhi=np.quantile(cr.normalized_residual,[tail,1-tail],method='linear')
                v=t.copy();v['nominal']=level;v['lower']=v.center+v.scale*qlo;v['upper']=v.center+v.scale*qhi;v['calibration_n']=len(cr)
                intervals.append(v)
        splits.append(dict(year=year,train_rows=len(train),train_label_end=str(train.end_date.max()),
            calibration_rows=len(cal),calibration_start=str(cal.date.min()),calibration_label_end=str(cal.end_date.max()),test_rows=len(test)))
        print('CatBoost same-key fold',year,len(test),flush=True)
    predictions=pd.concat(pieces,ignore_index=True)
    check=predictions.merge(previous,on=['date','asset'],validate='one_to_one',suffixes=('','_ridge'))
    assert len(check)==len(previous)==1600
    np.testing.assert_allclose(check.actual,check.actual_ridge,atol=1e-10,rtol=0)
    bands=pd.concat(intervals,ignore_index=True)
    for level,z in bands.groupby('nominal'):
        baseline=old_intervals[old_intervals.nominal.eq(level)]
        match=z.merge(baseline,on=['date','asset'],validate='one_to_one',suffixes=('','_ridge'))
        assert len(match)==1600
        np.testing.assert_array_equal(match.calibration_n,match.calibration_n_ridge)
        np.testing.assert_allclose(match.scale,match.scale_ridge,atol=1e-12,rtol=0)
    summary=dict(point={name:metrics(check,col) for name,col in [('catboost','center'),('sector_ridge','center_ridge'),('zero','zero')]},
        intervals={name:{str(round(k*100)):interval_metrics(z) for k,z in band.groupby('nominal')}
                   for name,band in [('catboost',bands),('sector_ridge',old_intervals)]},
        per_stock={a:{name:metrics(z,col) for name,col in [('catboost','center'),('sector_ridge','center_ridge'),('zero','zero')]} for a,z in check.groupby('asset')},
        by_year={str(y):{name:metrics(z,col) for name,col in [('catboost','center'),('sector_ridge','center_ridge'),('zero','zero')]} for y,z in check.groupby('year')},
        same_keys=True,same_targets=True,same_calibration_counts=True,same_scale=True,splits=splits,independent_blind=False)
    # Date-block uncertainty for CatBoost versus Ridge, without selecting parameters.
    d=check.assign(delta=abs(check.actual-check.center_ridge)-abs(check.actual-check.center)).groupby('date').delta.mean().to_numpy()
    rng=np.random.default_rng(20261109);boot=[]
    for _ in range(2000):
        starts=rng.integers(0,len(d),int(np.ceil(len(d)/4)));ix=np.concatenate([(s+np.arange(4))%len(d) for s in starts])[:len(d)]
        boot.append(float(d[ix].mean()))
    summary['date_block_mae_gain_vs_ridge_pp']=dict(mean=float(d.mean()),ci95=np.quantile(boot,[.025,.975]).tolist(),block=4)
    predictions.to_parquet(out/'predictions.parquet',index=False)
    pd.concat(calibration).to_parquet(out/'calibration.parquet',index=False)
    bands.to_parquet(out/'interval_predictions.parquet',index=False)
    # Latest fixed refit uses exactly the same matured training rows as Gold20 Ridge.
    b=joblib.load(source/'model.joblib')
    # Stable import path for joblib, including invocation via python -m.
    from .gold_catboost import StockCatBoost as PersistedCatBoost
    b['model']=PersistedCatBoost().fit(b['training_reference'])
    b['model_kind']='catboost';b['version']='gold20-catboost-20261109';b['config']=PARAMS
    b['validation']=summary['per_stock'];b['report']=summary
    b['selected_by']='User-selected per-stock CatBoost; comparison recorded without tuning'
    b['features']=FEATURES
    # Do not copy unapproved predictive intervals into runtime service output.
    joblib.dump(b,out/'model.joblib')
    for name in ['gold.parquet','provenance.parquet','certificate.json','request.json']:
        shutil.copyfile(source/name,out/name)
    diagnostics=[]
    grid=dict(fx_pct=[0,2.5,5,10],us_rate_bp=[0,25,100,200],wti_pct=[0,5,10,20],vix_points=[0,5,10,20])
    for a in b['assets']:
        row=b['snapshot'][b['snapshot'].asset.eq(a)].copy()
        for s,levels in grid.items():
            x=pd.concat([row.copy() for _ in levels],ignore_index=True);x[SHOCKS]=0.;x[s]=levels
            p=b['model'].predict(x)
            diagnostics.append(dict(asset=a,shock=s,levels=levels,outputs_pct=p.tolist(),changes_pp=(p-p[0]).tolist(),
                last_two_outputs_equal=bool(np.isclose(p[-1],p[-2],atol=1e-10,rtol=0))))
    save(out/'scenario_sweeps.json',diagnostics)
    summary['saturation_diagnostic']={s:dict(stocks=20,last_two_outputs_equal=sum(r['last_two_outputs_equal'] for r in diagnostics if r['shock']==s)) for s in SHOCKS}
    summary['selection']=dict(model='catboost',reason='Honor user choice, preserve stock-specific nonlinear state/shock responses; assess tradeoffs with exact same-key results',
        interval_in_primary_result=False,primary_result='Model change from zero-shock reference, per-shock model contribution and hypothetical money change',
        direction_meaning='Sign of model scenario change, not demonstrated future or causal effect direction',cloud_promoted=False)
    summary['original_artifacts_preserved']=all(sha(k)==v for k,v in protected.items())
    assert summary['original_artifacts_preserved']
    save(out/'comparison.json',summary)
    save(out/'artifact.json',dict(model_sha256=sha(out/'model.joblib'),model_kind='catboost',assets=b['assets'],market_basis_date=b['model_basis_date']))
    print(json.dumps({'point':summary['point'],'intervals':summary['intervals'],'saturation':summary['saturation_diagnostic']},indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source',required=True);p.add_argument('--out',required=True)
    a=p.parse_args();run(a.source,a.out)
