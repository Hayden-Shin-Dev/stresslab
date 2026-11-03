"""Asset-first metrics, paired date-block comparisons and joint residual portfolio extension."""
import json
import numpy as np
import pandas as pd
from asset_feature_research import OUT,ROOT,FEATURES,STATE,NEW,EXPANDED,SHOCKS,make_data
from adaptive_residual_benchmark import weighted_q

def score(x):
    return dict(n=len(x),dates=x.date.nunique(),center_mae=x.center_mae.mean(),center_rmse=np.sqrt(x.center_sq_error.mean()),coverage=x.coverage.mean(),width=x.width.mean(),interval_score=x.interval_score.mean(),lower_breach=x.lower_breach.mean(),missed_loss_pp=x.missed_loss_pp.mean())

def main():
    r=pd.read_parquet(OUT/'predictions.parquet');summ=[];per=[]
    pd.DataFrame([dict(method=k,fixed_width5_diagnostic_coverage=(abs(x.actual-x.center)<=2.5).mean()) for k,x in r.groupby('method')]).to_csv(OUT/'fixed_width5_diagnostic.csv',index=False)
    for method,x in r.groupby('method'):
        for regime in ['all','high_vol','market_crash','asset_crash','ordinary','elevated','extreme']:
            z=x if regime=='all' else x[x[regime]] if regime in ['high_vol','market_crash','asset_crash'] else x[x.shock_group==regime]
            if len(z):summ.append(dict(method=method,regime=regime,**score(z)))
        for asset,z in x.groupby('asset'):
            for regime in ['all','high_vol','asset_crash','market_crash']:
                v=z if regime=='all' else z[z[regime]]
                if len(v):per.append(dict(asset=asset,method=method,regime=regime,**score(v)))
    pd.DataFrame(summ).to_csv(OUT/'metrics.csv',index=False);p=pd.DataFrame(per);p.to_csv(OUT/'per_asset.csv',index=False)
    p[p.regime=='all'].groupby('method')[['center_mae','center_rmse','coverage','width','lower_breach']].mean().to_csv(OUT/'equal_asset_average.csv')
    decisions=p[p.regime=='all'].copy();decisions['passes_width_coverage']=(decisions.width<=5)&(decisions.coverage>=.8);decisions['production_approved']=False;decisions.to_csv(OUT/'asset_gates.csv',index=False)
    # Ablations distinguish raw point model improvements from residual recalibration.
    a=pd.read_csv(OUT/'center_ablations.csv',dtype={'asset':str},parse_dates=['date'])
    points=r[r.method.isin(['ridge_vol80','ridge_interactions_residual','lgb_expanded_residual','lgb_recent8_residual'])][['asset','date','method','actual','center','center_mae','high_vol','asset_crash']]
    legacy=pd.read_parquet(ROOT/'reports/adaptive_residual_20261103/predictions.parquet')
    legacy=legacy[(legacy.asset!='portfolio')&(legacy.model=='lightgbm')&(legacy.method=='frozen5_scaled')].copy()
    legacy['method']='lgb_legacy_features';legacy['center_mae']=abs(legacy.actual-legacy.center)
    a=pd.concat([a,points,legacy[['asset','date','method','actual','center','center_mae','high_vol','asset_crash']]],ignore_index=True);a['sq_error']=(a.actual-a.center)**2
    ar=[]
    for method,z in a.groupby('method'):
        ar.append(dict(method=method,n=len(z),mae=z.center_mae.mean(),rmse=np.sqrt(z.sq_error.mean()),zero_center_mae=abs(z.actual).mean(),r2_against_zero=1-z.sq_error.sum()/(z.actual**2).sum(),actual_prediction_correlation=z.actual.corr(z.center)))
    pd.DataFrame(ar).to_csv(OUT/'center_diagnosis.csv',index=False)
    # Paired circular blocks resample whole dates, preserving same-date dependence.
    pairs=[]
    for method in r.method.unique():
        baseline='lgb_expanded_residual' if method=='lgb_search_residual' else 'ridge_vol80'
        if method==baseline:continue
        z=r[r.method==method].merge(r[r.method==baseline],on=['asset','date'],suffixes=('_a','_b'),validate='one_to_one');dates=sorted(z.date.unique());n=len(dates);rng=np.random.default_rng(20261103)
        ids=np.array([np.concatenate([(s+np.arange(10))%n for s in rng.integers(n,size=int(np.ceil(n/10)))])[:n] for _ in range(1000)])
        for regime in ['all','high_vol','asset_crash','market_crash']:
            mask=np.ones(len(z),bool) if regime=='all' else z[regime+'_a'].to_numpy()
            for metric in ['center_mae','coverage','width','interval_score','lower_breach','missed_loss_pp']:
                d=z.assign(delta=(z[metric+'_a']-z[metric+'_b']).where(mask)).groupby('date').delta.agg(['sum','count']).reindex(dates);den=d['count'].to_numpy()[ids].sum(1);bs=d['sum'].to_numpy()[ids].sum(1)[den>0]/den[den>0]
                pairs.append(dict(method=method,baseline=baseline,regime=regime,metric=metric,delta=(z.loc[mask,metric+'_a']-z.loc[mask,metric+'_b']).mean(),ci_low=np.quantile(bs,.025),ci_high=np.quantile(bs,.975)))
    pd.DataFrame(pairs).to_csv(OUT/'paired_blocks.csv',index=False)
    # No sum of marginal quantiles: align each asset's historical error by date first.
    j=pd.read_parquet(OUT/'joint_scenarios.parquet');out=[];support=[]
    for (day,method),x in j.groupby(['date','method']):
        one=x[x.asset=='005930'];two=x[x.asset=='005380'];z=one.merge(two,on=['date','method','residual_date','residual_end'],suffixes=('_a','_b'),validate='one_to_one')
        if len(z)<30:continue
        w=np.sqrt(z.weight_a.to_numpy()*z.weight_b.to_numpy());w/=w.sum();v=(z.scenario_return_a.to_numpy()+z.scenario_return_b.to_numpy())/2;lo,med,hi=weighted_q(v,w)
        point=(z.center_a.iloc[0]+z.center_b.iloc[0])/2;actual=(z.actual_a.iloc[0]+z.actual_b.iloc[0])/2
        out.append(dict(date=day,method=method,center=point,median=med,q10=lo,q90=hi,actual=actual,center_mae=abs(actual-point),center_sq_error=(actual-point)**2,coverage=float(lo<=actual<=hi),width=hi-lo,interval_score=hi-lo+10*(max(lo-actual,0)+max(actual-hi,0)),lower_breach=float(actual<lo),missed_loss_pp=max(lo-actual,0),joint_n=len(z),ess=1/(w@w),scenario_pnl_100m=point*1e6))
        support.append(dict(date=day,method=method,shared_errors=len(z),samsung_errors=len(one),hyundai_errors=len(two)))
    # Volatility comparator uses daily covariance, not a sum of marginal bounds.
    gold=pd.read_parquet(ROOT/'exports/seongjin_gold_v1_1/gold_stress_daily.parquet')
    prices=gold.pivot(index='trading_date',columns='asset_id',values='close').sort_index()[['005930','005380']]
    daily=(prices.pct_change(fill_method=None)*100).mean(axis=1,skipna=False);daily.index=pd.to_datetime(daily.index)
    sigma=np.sqrt(5*(daily.rolling(20).var()+daily.rolling(60).var())/2)
    from scipy.stats import norm
    v=r[(r.method=='ridge_vol80')&r.asset.isin(['005930','005380'])]
    for day,x in v.groupby('date'):
        if x.asset.nunique()!=2:continue
        point=x.center.mean();actual=x.actual.mean();lo=point-norm.ppf(.9)*sigma.loc[day];hi=point+norm.ppf(.9)*sigma.loc[day]
        out.append(dict(date=day,method='ridge_vol80_asset_sum_covariance',center=point,median=point,q10=lo,q90=hi,actual=actual,center_mae=abs(actual-point),center_sq_error=(actual-point)**2,coverage=float(lo<=actual<=hi),width=hi-lo,interval_score=hi-lo+10*(max(lo-actual,0)+max(actual-hi,0)),lower_breach=float(actual<lo),missed_loss_pp=max(lo-actual,0),scenario_pnl_100m=point*1e6))
    portfolio=pd.DataFrame(out);portfolio.to_csv(OUT/'portfolio_secondary_predictions.csv',index=False);pd.DataFrame(support).to_csv(OUT/'joint_support.csv',index=False)
    pd.DataFrame([dict(method=k,**score(x)) for k,x in portfolio.groupby('method')]).to_csv(OUT/'portfolio_secondary_metrics.csv',index=False)
    r.sort_values('missed_loss_pp',ascending=False).head(100).to_csv(OUT/'failure_cases.csv',index=False)
    r[r.asset.isin(['005930','005380'])].to_csv(OUT/'samsung_hyundai_predictions.csv',index=False)
    d=pd.read_parquet(OUT/'learning_table.parquet');keys=r[['asset','date']].drop_duplicates();d.merge(keys,on=['asset','date'],validate='one_to_one').to_parquet(OUT/'evaluation_inputs.parquet',index=False)
    iv=pd.read_csv(OUT/'isolations.csv');iv.groupby(['asset','scenario']).agg(mean_center_change=('center_change','mean'),mean_abs_change=('center_change',lambda x:abs(x).mean()),max_search_change=('search_weight_change','max')).to_csv(OUT/'isolation_summary.csv')
    # Price changes after a cutoff must not change state features at/before cutoff.
    g=pd.read_parquet(ROOT/'exports/seongjin_gold_v1_1/gold_stress_daily.parquet');alter=g.copy();cut=pd.Timestamp('2024-01-02');alter.loc[pd.to_datetime(alter.trading_date)>cut,'close']*=1.1
    changed,_=make_data(alter);state=[c for c in EXPANDED if c not in SHOCKS];left=d[d.date<=cut];right=changed[changed.date<=cut];z=left.merge(right,on=['asset','date'],suffixes=('_a','_b'),validate='one_to_one');assert len(z)==len(left)
    assert max(float(abs(z[c+'_a']-z[c+'_b']).max()) for c in state)<1e-9
    verification=json.loads((OUT/'verification.json').read_text());verification['future_price_perturbation_leaves_state_unchanged']=True;verification['portfolio_uses_joint_asset_errors_not_marginal_quantile_sum']=True;(OUT/'verification.json').write_text(json.dumps(verification,indent=2))
    print(pd.DataFrame(summ).query('regime=="all"').round(3).to_string(index=False));print('asset_gate_passes',decisions.passes_width_coverage.sum())
if __name__=='__main__':main()
