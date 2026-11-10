"""Paired date-block uncertainty and evidence checks; no model tuning."""
import argparse,json
from pathlib import Path
import numpy as np
import pandas as pd

def run(folder):
    folder=Path(folder);p=pd.read_parquet(folder/'predictions.parquet');d=pd.read_parquet(folder/'diagnostics.parquet');e=pd.read_parquet(folder/'matched_pairs.parquet')
    p['error']=abs(p.actual-p.center)
    daily=p.groupby(['date','model']).error.mean().unstack();blocks=[x for _,x in daily.groupby(daily.index.to_period('M'))]
    rng=np.random.default_rng(20261104);draws={k:[] for k in daily if k!='global_factor'}
    for _ in range(1000):
        z=pd.concat([blocks[i] for i in rng.integers(0,len(blocks),len(blocks))])
        for k in draws:draws[k].append(100*(1-z[k].mean()/z.global_factor.mean()))
    ci={k:dict(mae_improvement_pct=100*(1-daily[k].mean()/daily.global_factor.mean()),date_block_95pct=np.quantile(v,[.025,.975]).tolist()) for k,v in draws.items()}
    (folder/'comparison_ci.json').write_text(json.dumps(ci,indent=2),encoding='utf8')
    # Each query uses an identical A set across all four shock comparisons.
    assert d.groupby(['stage','date','asset']).candidate_id_hash.nunique().max()==1
    assert e.control_distance.le(.5+1e-12).all() and e.other_shock_max_iqr.le(.5+1e-12).all()
    for _,z in e.groupby(['fold','query_date','asset','shock']):
        dates=pd.concat([z.date_i,z.date_j]);assert not dates.duplicated().any()
    train_end={x['year']:pd.Timestamp(x['train_label_end']) for x in json.loads((folder/'audit.json').read_text())['splits']}
    assert all(e[e.fold==yr].date_i.max()<=end and e[e.fold==yr].date_j.max()<=end for yr,end in train_end.items())
    p[p.actual<=-5].sort_values('error',ascending=False).head(100).to_csv(folder/'crash_failures.csv',index=False)
    p.groupby(['model',p.date.dt.year]).agg(n=('actual','size'),mae=('error','mean')).to_csv(folder/'year_metrics.csv')
    support=d[d.stage=='evaluation'].groupby('shock').agg(queries=('used','size'),used_fraction=('used','mean'),median_pairs=('matched_pairs','median'),remaining_variance=('remaining_shock_variance_ratio','median'),range_supported=('range_supported','mean'))
    support.to_csv(folder/'shock_support.csv')
    asset_ci=[];rng=np.random.default_rng(7)
    for asset,z in p.groupby('asset'):
        t=z.pivot(index='date',columns='model',values='error');groups=t.groupby(t.index.to_period('M'))
        sums=groups.sum();count=groups.size().to_numpy();draw=rng.integers(0,len(sums),size=(1000,len(sums)))
        base=sums.global_factor.to_numpy()[draw].sum(1)/count[draw].sum(1)
        for model in ['local','matched','supported_blend']:
            candidate=sums[model].to_numpy()[draw].sum(1)/count[draw].sum(1);gains=100*(1-candidate/base)
            asset_ci.append(dict(asset=asset,model=model,mae_gain_pct=100*(1-t[model].mean()/t.global_factor.mean()),ci_low=np.quantile(gains,.025),ci_high=np.quantile(gains,.975)))
    pd.DataFrame(asset_ci).to_csv(folder/'per_asset_uncertainty.csv',index=False)
    (folder/'verification.json').write_text(json.dumps(dict(A_identical_across_shocks=True,control_calipers_pass=True,disjoint_pairs=True,pairs_training_only=True,raw_pair_rows=len(e),distinct_historical_dates=len(set(e.date_i)|set(e.date_j)),caution='Repeated query pairs are not independent events; pooled dates are not causal identification.'),indent=2),encoding='utf8')
    print(support.to_string());print(json.dumps(ci))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('folder');run(p.parse_args().folder)
