"""Summarize fixed quarterly experiments without selecting parameters on test data."""
import json
import numpy as np
import pandas as pd
from .gold_quarterly_trial import OUT

def main():
    a=pd.read_csv(OUT/'splits.csv',dtype={'asset':str})
    summary=a.groupby('model').agg(fits=('train_n','size'),min_rows=('train_n','min'),max_rows=('train_n','max'),full2520=('train_n',lambda v:int((v>=2520).sum())),earliest=('train_start','min'))
    summary.to_csv(OUT/'training_summary.csv')
    a[(a.train_n<2520)&a.model.eq('legacy_long2520')].to_csv(OUT/'insufficient_history.csv',index=False)
    p=pd.read_parquet(OUT/'predictions.parquet');p=p[p.level.eq(.9)]
    pairs=[('legacy_common_rows','corrected_quarterly'),('legacy_long2520','legacy_common_rows'),('legacy_all_history','legacy_long2520'),('legacy_plus_us','legacy_long2520'),('legacy_plus_us_ewy','legacy_plus_us'),('catboost_long2520','legacy_long2520')]
    rows=[];rng=np.random.default_rng(20261105)
    for new,ref in pairs:
        z=p[p.model.eq(new)].merge(p[p.model.eq(ref)],on=['date','asset'],suffixes=('_new','_ref'),validate='one_to_one')
        np.testing.assert_allclose(z.actual_new,z.actual_ref)
        diff=(abs(z.actual_new-z.center_ref)-abs(z.actual_new-z.center_new)).groupby(z.date).mean().sort_index().to_numpy()
        n=len(diff);idx=(rng.integers(0,n,size=(2000,int(np.ceil(n/4)),1))+np.arange(4)[None,None,:])%n
        draws=diff[idx.reshape(2000,-1)[:,:n]].mean(axis=1)
        rows.append(dict(candidate=new,reference=ref,rows=len(z),dates=n,date_equal_mae_improvement_pp=float(diff.mean()),ci95_low=float(np.quantile(draws,.025)),ci95_high=float(np.quantile(draws,.975))))
    pd.DataFrame(rows).to_csv(OUT/'paired_date_block_ci.csv',index=False)
    print(summary.to_string());print(pd.DataFrame(rows).to_string(index=False))
    (OUT/'report_checks.json').write_text(json.dumps(dict(paired_actuals_equal=True,bootstrap_unit='date blocks length4; 2000 repeats',no_promotion=True),indent=2))

if __name__=='__main__':main()
