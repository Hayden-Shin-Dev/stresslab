"""Matched ablation summaries with date-block uncertainty and factor multiplicity."""
import json
import numpy as np
import pandas as pd
from evaluate_sector6_factors import ROOT,OUT,SRC,SHOCKS
from selection_target_research import sensitivity

def met(s):return dict(n=len(s),dates=s.date.nunique(),mae=s.center_mae.mean(),coverage=s.coverage.mean(),width=s.width.mean(),interval_score=s.interval_score.mean(),lower_breach=s.lower_breach.mean(),missed_loss_pp=s.missed_loss_pp.mean())

def main():
    r=pd.read_parquet(OUT/'predictions.parquet');names={x['asset_id']:x['name'] for p in [SRC/'universe.json',ROOT/'data/research/official20_20261102/universe.json'] for x in json.loads(p.read_text(encoding='utf8'))['assets']};metrics=[];comparisons=[];annual=[]
    for (asset,kind,spec),s in r.groupby(['asset','model','spec']):
        for regime in ['all','asset_crash','high_vol']:
            z=s if regime=='all' else s[s[regime]];metrics.append(dict(asset=asset,name=names[asset],model=kind,spec=spec,new_asset=bool(s.new_asset.iloc[0]),regime=regime,**met(z)))
    for (asset,kind),s in r.groupby(['asset','model']):
        for factor in SHOCKS:
            for mode,first,second in [('single','only_'+factor,'state_only'),('drop','all4','without_'+factor)]:
                a=s[s.spec==first];b=s[s.spec==second];z=a.merge(b,on=['asset','date'],suffixes=('_a','_b'),validate='one_to_one');assert len(z)==len(a)==len(b)
                delta=z.center_mae_a-z.center_mae_b;n=len(z);rng=np.random.default_rng(20261103);starts=rng.integers(n,size=(1000,int(np.ceil(n/10))));ids=((starts[:,:,None]+np.arange(10))%n).reshape(1000,-1)[:,:n];boot=delta.to_numpy()[ids].mean(1);avg=delta.mean();null=boot-avg;pv=(1+int((abs(null)>=abs(avg)).sum()))/1001
                comparisons.append(dict(asset=asset,name=names[asset],model=kind,factor=factor,mode=mode,n=n,new_asset=bool(s.new_asset.iloc[0]),mae_with=z.center_mae_a.mean(),mae_without=z.center_mae_b.mean(),mae_delta=avg,improvement_pct=-100*avg/z.center_mae_b.mean(),ci_low=np.quantile(boot,.025),ci_high=np.quantile(boot,.975),bootstrap_p=pv,coverage_delta=(z.coverage_a-z.coverage_b).mean(),width_delta=(z.width_a-z.width_b).mean()))
                for year,ss in z.groupby(z.date.dt.year):annual.append(dict(asset=asset,model=kind,factor=factor,mode=mode,year=year,n=len(ss),mae_delta=(ss.center_mae_a-ss.center_mae_b).mean()))
    c=pd.DataFrame(comparisons)
    # Global correction across all asset/model/factor/mode questions, not selected positives.
    pv=c.bootstrap_p.to_numpy();order=np.argsort(pv);q=np.empty(len(pv));q[order]=np.minimum.accumulate((pv[order]*len(pv)/np.arange(1,len(pv)+1))[::-1])[::-1];c['bh_q_global']=np.minimum(q,1);c.to_csv(OUT/'factor_comparisons.csv',index=False)
    pd.DataFrame(metrics).to_csv(OUT/'per_asset_metrics.csv',index=False);pd.DataFrame(annual).to_csv(OUT/'factor_by_year.csv',index=False)
    agg=[]
    for new in [False,True]:
        for (kind,spec),s in r[r.new_asset==new].groupby(['model','spec']):agg.append(dict(scope='new6' if new else 'original20',model=kind,spec=spec,**met(s)))
    pd.DataFrame(agg).to_csv(OUT/'scope_metrics.csv',index=False)
    # Same training-only sensitivity procedure for new assets, never evaluation-driven selection.
    d=pd.read_parquet(OUT/'learning_table.parquet');g=pd.read_parquet(OUT/'research_daily_input.parquet');p=g.groupby('trading_date').kospi_close.first().sort_index();mt=(p.shift(-5)/p-1)*100;mt.index=pd.to_datetime(mt.index);d['market_target']=d.date.map(mt);sens=[];observed=[]
    for asset,f in d[d.asset.isin(r[r.new_asset].asset.unique())].groupby('asset'):
        for year in [2023,2024,2025,2026]:sens.extend(sensitivity(f[f.end_date<pd.Timestamp(year-1,1,1)-pd.Timedelta(days=20)],asset,year))
        for shock,threshold in [('shock_fx',3),('shock_rate',25),('shock_oil',10),('shock_vix',5)]:
            for sign in [-1,1]:
                z=f[sign*f[shock]>=threshold];observed.append(dict(asset=asset,name=names[asset],shock=shock,threshold=threshold,sign=sign,n=len(z),negative_fraction=(z.target<0).mean(),median_return=z.target.median()))
    pd.DataFrame(sens).to_csv(OUT/'new6_sensitivity.csv',index=False);pd.DataFrame(observed).to_csv(OUT/'new6_observed_responses.csv',index=False)
    n6=d[d.asset.isin(r[r.new_asset].asset.unique())];counts=n6.groupby('date').asset.nunique();common=n6[n6.date.isin(counts[counts==6].index)];obs=[]
    for (asset),f in common.groupby('asset'):
        for shock,threshold in [('shock_fx',3),('shock_rate',25),('shock_oil',10),('shock_vix',5)]:
            z=f[f[shock]>=threshold];obs.append(dict(asset=asset,name=names[asset],shock=shock,threshold=threshold,n=len(z),negative_fraction=(z.target<0).mean(),median_return=z.target.median(),common_start=str(common.date.min()),common_end=str(common.date.max())))
    pd.DataFrame(obs).to_csv(OUT/'new6_common_date_reactions.csv',index=False)
    print(pd.DataFrame(agg).query("spec in ['all4','state_only']").round(3).to_string(index=False))
    print(c[(c.new_asset)&(c['mode']=='drop')][['asset','model','factor','improvement_pct','ci_low','ci_high','bh_q_global']].round(3).to_string(index=False))

if __name__=='__main__':main()
