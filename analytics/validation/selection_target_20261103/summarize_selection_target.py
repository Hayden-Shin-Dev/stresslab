"""Matched universe and matched target comparisons, never select on test results."""
import json
import numpy as np
import pandas as pd
from selection_target_research import ROOT,OUT

def metrics(z):
    return dict(n=len(z),dates=z.date.nunique(),stocks=z.asset.nunique(),mae=z.center_mae.mean(),rmse=np.sqrt(z.center_sq_error.mean()),coverage=z.coverage.mean(),width=z.width.mean(),interval_score=z.interval_score.mean(),lower_breach=z.lower_breach.mean(),missed_loss_pp=z.missed_loss_pp.mean())

def main():
    r=pd.read_parquet(OUT/'predictions.parquet');selection=pd.read_csv(OUT/'selections.csv',dtype={'asset':str});u=json.loads((ROOT/'data/research/official20_20261102/universe.json').read_text(encoding='utf8'));names={a['asset_id']:a['name'] for a in u['assets']}
    summary=[];assets=[];annual=[];comparisons=[]
    for selected in [False,True]:
        scope='train_selected8' if selected else 'original20';z=r[r.selected] if selected else r
        for (kind,target),f in z.groupby(['model','target_type']):
            exp=(3 if selected else 1)+(target=='excess')
            for regime in ['all','high_vol','asset_crash','market_crash']:
                s=f if regime=='all' else f[f[regime]]
                summary.append(dict(experiment=exp,scope=scope,model=kind,target=target,regime=regime,**metrics(s)))
            for asset,s in f.groupby('asset'):
                for regime in ['all','asset_crash']:
                    q=s if regime=='all' else s[s.asset_crash]
                    assets.append(dict(scope=scope,model=kind,target=target,asset=asset,name=names[asset],regime=regime,**metrics(q)))
            for year,s in f.groupby('year'):annual.append(dict(scope=scope,model=kind,target=target,year=year,**metrics(s)))
        for kind in ['ridge','lgb']:
            a=z[(z.model==kind)&(z.target_type=='excess')];b=z[(z.model==kind)&(z.target_type=='total')]
            pairs=a.merge(b,on=['asset','date'],suffixes=('_a','_b'),validate='one_to_one');assert len(pairs)==len(a)==len(b)
            for regime in ['all','asset_crash','high_vol']:
                q=pairs if regime=='all' else pairs[pairs[regime+'_a']]
                for metric in ['center_mae','coverage','width','interval_score','lower_breach','missed_loss_pp']:
                    v=q.assign(delta=q[metric+'_a']-q[metric+'_b']).groupby('date').delta.agg(['sum','count']);n=len(v)
                    rng=np.random.default_rng(20261103);ids=np.array([np.concatenate([(start+np.arange(10))%n for start in rng.integers(n,size=int(np.ceil(n/10)))])[:n] for _ in range(1000)])
                    boot=v['sum'].to_numpy()[ids].sum(1)/v['count'].to_numpy()[ids].sum(1)
                    comparisons.append(dict(scope=scope,model=kind,regime=regime,metric=metric,n=len(q),delta=q[metric+'_a'].mean()-q[metric+'_b'].mean(),ci_low=np.quantile(boot,.025),ci_high=np.quantile(boot,.975)))
    pd.DataFrame(summary).to_csv(OUT/'metrics.csv',index=False);p=pd.DataFrame(assets);p['target_pass']=(p.coverage>=.8)&(p.width<=5);p.to_csv(OUT/'per_asset.csv',index=False);pd.DataFrame(annual).to_csv(OUT/'annual.csv',index=False);pd.DataFrame(comparisons).to_csv(OUT/'paired_target_comparisons.csv',index=False)
    de=pd.read_csv(OUT/'error_decomposition.csv',dtype={'asset':str});dr=[]
    for (asset,kind),s in de.groupby(['asset','model']):
        dr.append(dict(asset=asset,model=kind,excess_component_mae=s.excess_error.abs().mean(),market_component_mae=s.market_error.abs().mean(),restored_mae=s.restored_error.abs().mean(),error_correlation=s.excess_error.corr(s.market_error),excess_mse=(s.excess_error**2).mean(),market_mse=(s.market_error**2).mean(),cross_term=2*(s.market_error*s.excess_error).mean(),restored_mse=(s.restored_error**2).mean()))
    pd.DataFrame(dr).to_csv(OUT/'error_decomposition_summary.csv',index=False)
    # Hold absolute shock magnitudes fixed across folds for counts; do not tune selection.
    data=pd.read_parquet(ROOT/'reports/model_redesign_20261103/learning_table.parquet');counts=[]
    for year in [2023,2024,2025,2026]:
        h=data[data.end_date<pd.Timestamp(year-1,1,1)-pd.Timedelta(days=20)].sort_values('date').drop_duplicates('date').iloc[::6]
        for factor,threshold in [('shock_fx',3),('shock_fx',5),('shock_rate',50),('shock_rate',100),('shock_oil',10),('shock_vix',5)]:
            counts.append(dict(year=year,shock=factor,positive_threshold=threshold,disjoint_n=len(h),positive_n=int((h[factor]>=threshold).sum()),negative_n=int((h[factor]<=-threshold).sum()),minimum=h[factor].min(),maximum=h[factor].max()))
    pd.DataFrame(counts).to_csv(OUT/'shock_support.csv',index=False)
    sensitivity=pd.read_csv(OUT/'sensitivity.csv',dtype={'asset':str});sensitivity['name']=sensitivity.asset.map(names);sensitivity.to_csv(OUT/'sensitivity.csv',index=False);selection['name']=selection.asset.map(names);selection.to_csv(OUT/'selections.csv',index=False)
    # Eligibility same20 candidates; selected independent fits are exact subsets.
    persistent=set.intersection(*[set(z[z.selected].asset) for _,z in selection.groupby('year')]);stable=r[r.asset.isin(persistent)]
    pd.DataFrame([dict(method=k,scope='selected_in_every_fold_descriptive_only',**metrics(z)) for k,z in stable.groupby('method')]).to_csv(OUT/'persistent_subset.csv',index=False)
    r[r.asset_crash].sort_values('missed_loss_pp',ascending=False).head(100).to_csv(OUT/'failure_cases.csv',index=False)
    print(pd.DataFrame(summary).query("regime=='all'").round(3).to_string(index=False))
    print('targets passed',int(p[(p.regime=='all')].target_pass.sum()))

if __name__=='__main__':main()
