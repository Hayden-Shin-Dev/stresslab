"""Paired summaries; resample dates rather than treating stocks as independent."""
from pathlib import Path
import json, os
import numpy as np
import pandas as pd

ROOT=Path(os.environ.get('STRESSLAB_AUDIT_ROOT', Path(__file__).resolve().parents[1]))
OUT=ROOT/'reports/search_stress_validation_20261103'

def main():
    r=pd.read_parquet(OUT/'predictions.parquet')
    comparisons=[]
    for scope,part in [('portfolio',r[r.asset.eq('portfolio')]),('stocks',r[~r.asset.eq('portfolio')])]:
        for period,z in [('all',part),('recent3m',part[part.date>='2026-07-16'])]:
            for candidate,baseline in [('state_ridge','shock_only'),('state_ecos_ridge','state_ridge'),('state_ecos_ridge','volatility'),('state_ridge','volatility'),('state_shock_replay','shock_replay')]:
                a=z[z.model.eq(candidate)];b=z[z.model.eq(baseline)]
                pair=a.merge(b,on=['date','asset'],suffixes=('_a','_b'))
                if pair.empty:continue
                for metric in ['mae','interval_score','pinball05']:
                    daily=pair.assign(delta=pair[metric+'_a']-pair[metric+'_b']).groupby('date').delta.mean().sort_index().to_numpy()
                    rng=np.random.default_rng(20261103);n=len(daily);block=min(10,n)
                    samples=[]
                    for _ in range(1000):
                        starts=rng.integers(0,n,size=int(np.ceil(n/block)))
                        idx=np.concatenate([(s+np.arange(block))%n for s in starts])[:n]
                        samples.append(daily[idx].mean())
                    comparisons.append(dict(scope=scope,period=period,candidate=candidate,baseline=baseline,metric=metric,
                        rows=len(pair),dates=n,candidate_mean=float(pair[metric+'_a'].mean()),baseline_mean=float(pair[metric+'_b'].mean()),
                        delta=float(daily.mean()),ci_low=float(np.quantile(samples,.025)),ci_high=float(np.quantile(samples,.975))))
    pd.DataFrame(comparisons).to_csv(OUT/'paired_comparisons.csv',index=False)
    checks=pd.read_csv(OUT/'search_checks.csv')
    checks.loc[checks.method.str.startswith('random_'),'method']='random'
    # First average random repetitions per date; ten seeds are not ten independent samples.
    checks=checks.groupby(['date','method']).mean(numeric_only=True).reset_index()
    s=checks.groupby('method').mean(numeric_only=True).to_dict('index')
    stability=pd.read_csv(OUT/'search_stability.csv').groupby('change').mean(numeric_only=True).to_dict('index')
    dependence=pd.read_csv(OUT/'event_dependence.csv').groupby('method').agg(n=('date','size'),median_change=('max_leave_one_change_pct','median'),max_change=('max_leave_one_change_pct','max'),flip_rate=('direction_flip','mean')).to_dict('index')
    result={'search_checks':s,'synthetic_state_sensitivity':stability,'single_window_dependence':dependence,
            'test_start':str(r.date.min()),'test_end':str(r.date.max()),'assets':sorted(set(r.asset)-{'portfolio'}),
            'note':'Previously examined dates, release schedule proxies, current universe survivorship bias. Not blind or certified point-in-time. Bootstrap interval is descriptive, not model approval.'}
    (OUT/'summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(result,ensure_ascii=False,indent=2))
    m=pd.read_csv(OUT/'metrics.csv')
    print(m[(m.asset=='portfolio') & (m.period.isin(['all','recent3m']))].to_string(index=False))

if __name__=='__main__':main()
