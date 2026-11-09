"""Independent sample, feature and metric checks for the matched Gold experiment."""
import json,hashlib
import numpy as np
import pandas as pd
from gold_quantile_benchmark import ROOT,FEATURES,build
from compare_gold20_locked_20261104 import OUT,METHODS,metrics

def main():
    source=ROOT/'exports/seongjin_gold_v1_1/gold_stress_daily.parquet'
    g=pd.read_parquet(source);a=build(g);a=a[a.asset!='portfolio'].sort_values(['asset','date']).reset_index(drop=True)
    b=pd.read_parquet(OUT/'learning_table.parquet').sort_values(['asset','date']).reset_index(drop=True)
    assert a[['asset','date']].equals(b[['asset','date']])
    assert np.array_equal(a[FEATURES+['target','scale']].to_numpy(),b[FEATURES+['target','scale']].to_numpy())
    assert len(b)==100871 and b.asset.nunique()==20 and not b.duplicated(['asset','date']).any()
    r=pd.read_parquet(OUT/'predictions.parquet');lock=pd.read_parquet(OUT/'locked_baseline.parquet').sort_values(['asset','date'])
    checks=[]
    for method in METHODS+['prior_selected','stock_selected','fixed_blend']:
        z=r[r.method==method].sort_values(['asset','date'])
        assert len(z)==2928 and z.asset.nunique()==20
        assert list(zip(z.asset,z.date))==list(zip(lock.asset,lock.date))
        assert np.array_equal(z.actual.to_numpy(),lock.actual.to_numpy()) and np.isfinite(z.center).all()
        if method=='baseline':assert np.max(abs(z.center.to_numpy()-lock['median'].to_numpy()))<1e-7
        # Independent direct metric formulas, compared with serialized outputs.
        saved=pd.read_csv(OUT/'metrics.csv').set_index('method').loc[method]
        assert abs(saved.mae-np.mean(abs(z.actual-z.center)))<1e-10
        nz=z.actual!=0;assert abs(saved.direction-np.mean(np.sign(z.loc[nz,'actual'])==np.sign(z.loc[nz,'center'])))<1e-10
        checks.append(method)
    fit=pd.read_csv(OUT/'fit_audit.csv');assert (pd.to_datetime(fit.train_end)<pd.to_datetime(fit.test_start)).all()
    selection=json.loads((OUT/'frozen_selection.json').read_text())
    chosen=selection['chosen'];x=r[r.method==chosen].sort_values(['asset','date']);y=r[r.method=='prior_selected'].sort_values(['asset','date']);assert np.array_equal(x.center,y.center)
    choices=json.loads((OUT/'stock_frozen_selection.json').read_text())['choices']
    for asset,method in choices.items():
        x=r[(r.asset==asset)&(r.method==method)].sort_values('date');y=r[(r.asset==asset)&(r.method=='stock_selected')].sort_values('date');assert np.array_equal(x.center,y.center)
    from blend_gold20_locked_20261104 import blend
    x=blend(r).sort_values(['asset','date']);y=r[r.method=='fixed_blend'].sort_values(['asset','date']);assert np.allclose(x.center,y.center,rtol=0,atol=1e-10)
    result=dict(status='passed',original_training_rows=len(a),expanded_training_rows=len(b),stocks=20,evaluation_stock_dates=2928,methods_checked=checks,original_features_targets_scales_exact=True,baseline_reproduced=True,paired_stock_dates_exact=True,metrics_recomputed=True,original_gold_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),production_approval=False)
    (OUT/'verification.json').write_text(json.dumps(result,indent=2),encoding='utf8');print(json.dumps(result))

if __name__=='__main__':main()
