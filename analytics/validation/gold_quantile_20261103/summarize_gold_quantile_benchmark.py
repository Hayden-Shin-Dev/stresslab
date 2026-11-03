"""Paired uncertainty and scenario-level reliability, without promoting models."""
import os,json
from pathlib import Path
import numpy as np
import pandas as pd
ROOT=Path(os.environ.get('STRESSLAB_AUDIT_ROOT',Path(__file__).resolve().parents[1]))
OUT=ROOT/'reports/gold_quantile_benchmark_20261103'

def main():
    r=pd.read_parquet(OUT/'predictions.parquet');comparisons=[]
    for scope,x in [('portfolio',r[r.asset.eq('portfolio')]),('stocks',r[~r.asset.eq('portfolio')])]:
        for candidate in ['ridge','catboost_quantile','catboost_calibrated']:
            z=x[x.model.eq(candidate)].merge(x[x.model.eq('volatility')],on=['date','asset'],suffixes=('_a','_b'))
            for metric in ['mae','interval_score','pinball05']:
                d=z.assign(delta=z[metric+'_a']-z[metric+'_b']).groupby('date').delta.mean().sort_index().to_numpy();n=len(d);block=min(10,n);rng=np.random.default_rng(20261103)
                boot=[d[np.concatenate([(s+np.arange(block))%n for s in rng.integers(n,size=int(np.ceil(n/block)))])[:n]].mean() for _ in range(1000)]
                comparisons.append(dict(scope=scope,candidate=candidate,metric=metric,n=len(z),dates=n,delta=d.mean(),ci_low=np.quantile(boot,.025),ci_high=np.quantile(boot,.975)))
    pd.DataFrame(comparisons).to_csv(OUT/'paired_comparisons.csv',index=False)
    narrow=[]
    for (asset,model),z in r.groupby(['asset','model']):
        p=z[z.width<=5];n=len(p);hits=p.coverage.sum();rate=hits/n if n else np.nan
        if n:
            center=(rate+1.96**2/(2*n))/(1+1.96**2/n);half=1.96*np.sqrt(rate*(1-rate)/n+1.96**2/(4*n*n))/(1+1.96**2/n)
        else:center=half=np.nan
        narrow.append(dict(asset=asset,model=model,n=n,total=len(z),coverage=rate,descriptive_ci_low=center-half,descriptive_ci_high=center+half,width=p.width.mean(),interval_score=p.interval_score.mean()))
    pd.DataFrame(narrow).to_csv(OUT/'width5_subsets.csv',index=False)
    pivot=r.pivot(index=['date','asset'],columns='model',values='median');spread=(pivot.max(axis=1)-pivot.min(axis=1)).rename('model_median_spread').reset_index()
    joined=r.merge(spread,on=['date','asset'],validate='many_to_one')
    table=[]
    for (asset,model,regime,shock),z in joined.groupby(['asset','model','regime','shock_group']):
        n=len(z);table.append(dict(asset=asset,model=model,market_state=regime,shock_group=shock,n=n,
            data_support_median=float(z.support_windows.median()),data_support_min=int(z.support_windows.min()),
            mae=z.mae.mean(),coverage=z.coverage.mean(),width=z.width.mean(),interval_score=z.interval_score.mean(),
            var_breach=z.breach.mean(),miss_size=z.miss_size.mean(),model_median_spread=z.model_median_spread.mean(),
            training_window_stability='see training_stability.csv' if asset=='portfolio' else 'not_evaluated',
            portfolio_integrity='actual same-date 50/50 weighted return; direct portfolio model; arbitrary weights not verified' if asset=='portfolio' else 'marginal interval only; not joint draws',
            evidence='small_sample' if n<30 else 'research_only',publication='unverified',production_approved=False))
    pd.DataFrame(table).to_csv(OUT/'scenario_reliability.csv',index=False)
    reference=r.groupby(['date','asset']).actual.agg(['min','max']);assert (reference['max']-reference['min']).abs().max()<1e-10
    assert np.all(r.q05<=r['median']) and np.all(r['median']<=r.q95)
    counts=r.groupby(['date','asset']).model.nunique();assert counts.min()==4
    summary={'assets':int(r[~r.asset.eq('portfolio')].asset.nunique()),'first':str(r.date.min()),'last':str(r.date.max()),
        'same_model_samples':True,'ordered_quantiles':True,'cloud_changes':False,'test_reused':True,
        'goal':'width <=5 pp and about90% coverage; descriptive subgroup success is not independent approval'}
    (OUT/'verification.json').write_text(json.dumps(summary,indent=2),encoding='utf8')
    loss=r[(r.asset=='portfolio')&(r.actual < -5)]
    loss.groupby('model').agg(n=('date','size'),breaches=('breach','sum'),coverage=('coverage','mean'),miss_size=('miss_size','mean')).to_csv(OUT/'portfolio_loss_cases.csv')
    import sys,catboost,sklearn
    (OUT/'environment.json').write_text(json.dumps({'python':sys.version,'catboost':catboost.__version__,'sklearn':sklearn.__version__,'numpy':np.__version__,'pandas':pd.__version__},indent=2),encoding='utf8')
    print(pd.DataFrame(comparisons).round(4).to_string(index=False));print('WIDTH5 PORTFOLIO');print(pd.DataFrame(narrow).query("asset=='portfolio'").to_string(index=False))

if __name__=='__main__':main()
