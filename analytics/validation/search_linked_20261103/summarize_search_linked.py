import pandas as pd,numpy as np
from search_linked_benchmark import OUT
r=pd.read_parquet(OUT/'predictions.parquet');results=[]
for scope,z in [('portfolio',r[r.asset.eq('portfolio')]),('stocks',r[~r.asset.eq('portfolio')])]:
    baseline=z[z.method.eq('frozen5_scaled')]
    for method in ['global_center_linked_residual_5year','linked_center_global_residual_5year','linked_center_linked_residual_5year']:
        p=z[z.method.eq(method)].merge(baseline,on=['date','asset'],suffixes=('_a','_b'),validate='one_to_one')
        dates=sorted(p.date.unique());n=len(dates);rng=np.random.default_rng(20261103)
        ids=np.array([np.concatenate([(s+np.arange(10))%n for s in rng.integers(n,size=int(np.ceil(n/10)))])[:n] for _ in range(1000)])
        for regime in ['all','high_vol','market_crash']:
            mask=np.ones(len(p),bool) if regime=='all' else p[regime+'_a'].to_numpy()
            for metric in ['coverage','width','interval_score','breach','miss_size','mae']:
                d=p.assign(delta=(p[metric+'_a']-p[metric+'_b']).where(mask)).groupby('date').delta.agg(['sum','count']).reindex(dates)
                den=d['count'].to_numpy()[ids].sum(1);bs=d['sum'].to_numpy()[ids].sum(1)[den>0]/den[den>0]
                results.append(dict(scope=scope,method=method,regime=regime,metric=metric,delta=(p.loc[mask,metric+'_a']-p.loc[mask,metric+'_b']).mean(),ci_low=np.quantile(bs,.025),ci_high=np.quantile(bs,.975)))
pd.DataFrame(results).to_csv(OUT/'paired_five_year.csv',index=False)
i=pd.read_csv(OUT/'isolation.csv');i['center_change']=i.center-i.base_center;i.groupby('scenario').agg(mean_center_change=('center_change','mean'),mean_abs_center_change=('center_change',lambda x:abs(x).mean()),max_search_change=('search_weight_change','max')).to_csv(OUT/'isolation_summary.csv')
p=r[(r.asset=='portfolio')&r.market_crash&r.method.isin(['frozen5_scaled','global_center_linked_residual_5year','linked_center_linked_residual_5year'])].copy()
p['median_pnl_100m']=p['median']*1e6;p['lower_pnl_100m']=p.q10*1e6;p['upper_pnl_100m']=p.q90*1e6;p['actual_pnl_100m']=p.actual*1e6
p.to_csv(OUT/'portfolio_crash_money.csv',index=False)
print(pd.DataFrame(results).query('scope=="portfolio" and regime=="all" and method=="global_center_linked_residual_5year"').round(4).to_string(index=False))
print(p[p.date.eq('2026-10-08')][['method','actual','median','q10','q90']].round(3).to_string(index=False))
print(pd.read_csv(OUT/'isolation_summary.csv').round(4).to_string(index=False))
# Inputs corresponding to each evaluated portfolio query, for reproducibility.
from gold_quantile_benchmark import ROOT,build,FEATURES
source=build(pd.read_parquet(ROOT/'exports/seongjin_gold_v1_1/gold_stress_daily.parquet'))
queries=source[source.asset.eq('portfolio')][['date','end_date']+FEATURES]
queries=queries[queries.date.isin(r[r.asset.eq('portfolio')].date)]
queries.to_csv(OUT/'portfolio_query_inputs.csv',index=False)
