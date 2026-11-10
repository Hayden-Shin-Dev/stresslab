"""Summarize fixed sensitivity experiment, without selecting test winners."""
import argparse,json
from pathlib import Path
import numpy as np
import pandas as pd
from .core import metrics

def run(folder):
    folder=Path(folder);p=pd.read_parquet(folder/'predictions.parquet')
    if (folder/'raw_control_predictions.parquet').exists():p=pd.concat([p,pd.read_parquet(folder/'raw_control_predictions.parquet')])
    p['error']=abs(p.actual-p.center)
    extra={'003490','020560','010950','096770','051910','011170'}
    pd.DataFrame([dict(scope=scope,model=k,**metrics(z)) for scope,subset in [('existing20',p[~p.asset.isin(extra)]),('additional6',p[p.asset.isin(extra)])] for k,z in subset.groupby('model')]).to_csv(folder/'cohort_metrics.csv',index=False)
    p.groupby(['fold','model']).error.agg(['size','mean']).to_csv(folder/'year_errors.csv')
    p[p.actual<=-5].sort_values('error',ascending=False).head(100).to_csv(folder/'crash_failures.csv',index=False)
    daily=p.groupby(['date','model']).error.mean().unstack();blocks=[z for _,z in daily.groupby(daily.index.to_period('M'))];rng=np.random.default_rng(41);result=[]
    for candidate in ['partial_global','partial_state_gated']:
        for base in ['ridge','lightgbm','catboost','partial_global']+(['individual_ridge_raw'] if 'individual_ridge_raw' in daily else []):
            if base==candidate:continue
            gains=[]
            for _ in range(1000):
                z=pd.concat([blocks[i] for i in rng.integers(0,len(blocks),len(blocks))]);gains.append(100*(1-z[candidate].mean()/z[base].mean()))
            result.append(dict(model=candidate,baseline=base,gain_pct=100*(1-daily[candidate].mean()/daily[base].mean()),ci_low=np.quantile(gains,.025),ci_high=np.quantile(gains,.975)))
    pd.DataFrame(result).to_csv(folder/'comparison_ci.csv',index=False)
    s=pd.read_csv(folder/'extrapolation.csv',dtype={'asset':str});pivot=s.pivot(index=['asset','model'],columns='multiplier',values='center')
    pivot['saturated_1_to_4']=(pivot[1]-pivot[4]).abs()<1e-10
    pivot.reset_index().to_csv(folder/'extrapolation_audit.csv',index=False)
    s=pd.read_csv(folder/'sensitivity_stability.csv',dtype={'asset':str})
    s.groupby(['asset','shock']).agg(folds=('coefficient','size'),positive_folds=('coefficient',lambda x:int((x>0).sum())),negative_folds=('coefficient',lambda x:int((x<0).sum())),coefficient_min=('coefficient','min'),coefficient_max=('coefficient','max'),training_rule_pass_fraction=('stable','mean')).to_csv(folder/'across_year_stability.csv')
    print(pd.DataFrame(result).to_string(index=False))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('folder');run(p.parse_args().folder)
