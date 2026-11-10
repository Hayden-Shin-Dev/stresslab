"""Summaries and Gold suitability audit for redesign, no service changes."""
import json
import numpy as np
import pandas as pd
from model_redesign_research import ROOT,OUT

def metric(x):
    return dict(n=len(x),dates=x.date.nunique(),center_mae=x.center_mae.mean(),rmse=np.sqrt(x.center_sq_error.mean()),coverage=x.coverage.mean(),width=x.width.mean(),interval_score=x.interval_score.mean(),lower_breach=x.lower_breach.mean(),missed_loss_pp=x.missed_loss_pp.mean())

def main():
    r=pd.read_parquet(OUT/'predictions.parquet');allrows=[];per=[]
    for method,x in r.groupby('method'):
        for group in ['all','high_vol','asset_crash','market_crash']:
            z=x if group=='all' else x[x[group]]
            allrows.append(dict(method=method,regime=group,**metric(z)))
        for asset,z in x.groupby('asset'):
            for group in ['all','asset_crash']:
                s=z if group=='all' else z[z[group]]
                if len(s):per.append(dict(asset=asset,method=method,regime=group,**metric(s)))
    p=pd.DataFrame(per);pd.DataFrame(allrows).to_csv(OUT/'metrics.csv',index=False);p.to_csv(OUT/'per_asset.csv',index=False)
    p[p.regime=='all'].groupby('method')[['center_mae','coverage','width','lower_breach']].mean().to_csv(OUT/'equal_asset_average.csv')
    gate=p[p.regime=='all'].copy();gate['target_pass']=(gate.coverage>=.8)&(gate.width<=5);gate['approved']=False;gate.to_csv(OUT/'asset_gates.csv',index=False)
    comparisons=[]
    for method in ['pooled_residual','partial_residual','pooled_direct80','pooled_search_residual','pooled_cluster_residual','pooled_asset_search_residual']:
        baseline='pooled_residual' if 'search' in method or 'cluster' in method else 'lgb_expanded_residual'
        z=r[r.method==method].merge(r[r.method==baseline],on=['asset','date'],suffixes=('_a','_b'),validate='one_to_one');dates=sorted(z.date.unique());n=len(dates);rng=np.random.default_rng(20261103);ids=np.array([np.concatenate([(s+np.arange(10))%n for s in rng.integers(n,size=int(np.ceil(n/10)))])[:n] for _ in range(1000)])
        for regime in ['all','high_vol','asset_crash']:
            mask=np.ones(len(z),bool) if regime=='all' else z[regime+'_a'].to_numpy()
            for m in ['center_mae','coverage','width','interval_score','lower_breach','missed_loss_pp']:
                d=z.assign(delta=(z[m+'_a']-z[m+'_b']).where(mask)).groupby('date').delta.agg(['sum','count']).reindex(dates);den=d['count'].to_numpy()[ids].sum(1);bs=d['sum'].to_numpy()[ids].sum(1)[den>0]/den[den>0]
                comparisons.append(dict(method=method,baseline=baseline,regime=regime,metric=m,delta=(z.loc[mask,m+'_a']-z.loc[mask,m+'_b']).mean(),ci_low=np.quantile(bs,.025),ci_high=np.quantile(bs,.975)))
    pd.DataFrame(comparisons).to_csv(OUT/'paired_comparisons.csv',index=False)
    r[r.asset_crash].sort_values('missed_loss_pp',ascending=False).head(100).to_csv(OUT/'failure_cases.csv',index=False)
    r[r.asset.isin(['005930','005380'])].to_csv(OUT/'example_predictions.csv',index=False)
    # Gold compatibility, missingness and what the existing quality checks actually cover.
    g=pd.read_parquet(ROOT/'exports/seongjin_gold_v1_1/gold_stress_daily.parquet')
    contract=ROOT.parent/'stresslab-team/contracts/daily/schema.json';schema=json.loads(contract.read_text(encoding='utf8'));required=schema['items']['required']
    audit={'rows':len(g),'stocks':g.asset_id.nunique(),'duplicate_keys':int(g.duplicated(['dataset_version','trading_date','asset_id']).sum()),'missing_contract_columns':sorted(set(required)-set(g.columns)),'extra_columns':sorted(set(g.columns)-set(required)),
      'null_counts':{c:int(g[c].isna().sum()) for c in ['sector_id','price_available_at']+[c for c in g if c.endswith('_available_at') and c!='price_available_at']},
      'quality_status':g.quality_status.value_counts().to_dict(),'zero_volume_rows':int(g.volume.eq(0).sum()),'mock_rows':int(g.is_mock.eq(True).sum()),'price_basis':g.price_basis.value_counts().to_dict(),
      'sample_limit':'current selected20 securities, Samsung ordinary/preferred are same issuer; no historical delisted universe or PIT sector membership',
      'reuse':'price bridge local validation passed200 new rows; not proof of all corporate events since2000',
      'dart_prior_experiment':'reports/ecos_dart_features_20261102; 1-4 independent annual financial snapshots per stock, performance deteriorated; no repeat or backfill of corrected filings',
      'changes':'no Gold changes. Fill existing sector_id and available_at from actual sources before certification; derived price features remain ML layer'}
    obs={}
    for c in [c for c in g if c.endswith('_observation_date')]:
        delta=(pd.to_datetime(g.trading_date)-pd.to_datetime(g[c])).dt.days;obs[c]={'future_observation_rows':int((delta<0).sum()),'max_calendar_lag':None if delta.isna().all() else float(delta.max())}
    audit['observation_dates']=obs;(OUT/'gold_suitability.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf8')
    # Current DART metadata only for descriptive grouping, never historical training features.
    meta=json.loads((ROOT/'data/v4/official/dart_industry_codes.json').read_text(encoding='utf8'))
    mapping={x['stock_code']:x.get('industry_code') for x in meta['records']};s=p[(p.regime=='all')].copy();s['current_dart_industry']=s.asset.map(mapping);s['classification_asof']=meta['retrieved_at'];s.to_csv(OUT/'descriptive_current_industry.csv',index=False)
    x=pd.read_csv(OUT/'asset_shock_sensitivity.csv',dtype={'asset':str});summ=[]
    for (method,scenario),z in x.groupby(['model','scenario']):
        a=z[z.version=='full'].set_index('asset');b=z[z.version=='recent8'].set_index('asset');common=a.index.intersection(b.index)
        summ.append(dict(model=method,scenario=scenario,stocks=len(common),cross_stock_delta_std=a.delta_from_zero.std(),rank_correlation=a.loc[common,'delta_from_zero'].corr(b.loc[common,'delta_from_zero'],method='spearman'),direction_agreement=float((np.sign(a.loc[common,'delta_from_zero'])==np.sign(b.loc[common,'delta_from_zero'])).mean())))
    pd.DataFrame(summ).to_csv(OUT/'sensitivity_stability.csv',index=False)
    # Observed-shock strata: observational OOS evidence, not a causal sensitivity test.
    data=pd.read_parquet(OUT/'learning_table.parquet');merged=r.merge(data[['asset','date','shock_oil','shock_vix']],on=['asset','date'],validate='many_to_one');strata=[]
    for name,mask in [('oil_up10',merged.shock_oil>=10),('oil_down10',merged.shock_oil<=-10),('fx_up3',merged.shock_fx>=3),('rate_up25',merged.shock_rate>=25),('rate_up50',merged.shock_rate>=50),('vix_up5',merged.shock_vix>=5)]:
        for (asset,method),z in merged[mask].groupby(['asset','method']):strata.append(dict(asset=asset,method=method,observed_condition=name,**metric(z)))
    pd.DataFrame(strata).to_csv(OUT/'observed_shock_strata.csv',index=False)
    print(pd.DataFrame(allrows).query('regime=="all"').round(3).to_string(index=False));print('target passes',gate.target_pass.sum())
if __name__=='__main__':main()
