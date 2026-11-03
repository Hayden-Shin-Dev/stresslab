"""Asset-first audit of saved OOS forecasts; excludes direct portfolio forecasts."""
import sys,json
from pathlib import Path
import pandas as pd,numpy as np
from gold_quantile_benchmark import ROOT,build,FEATURES
sys.path.insert(0,str(ROOT))
try:
    from stresslab.asset_stress_results import apply_asset_returns
except ModuleNotFoundError:
    from asset_stress_results import apply_asset_returns
OUT=ROOT/'reports/asset_first_20261103'

def metrics(x):
    return dict(n=len(x),dates=x.date.nunique(),center_mae=abs(x.actual-x.center).mean(),center_rmse=np.sqrt(((x.actual-x.center)**2).mean()),
                calibrated_median_mae=abs(x.actual-x['median']).mean(),coverage=x.coverage.mean(),width=x.width.mean(),lower_breach=x.breach.mean(),
                missed_loss_pp=x.miss_size.mean(),interval_score=x.interval_score.mean(),start=str(x.date.min().date()),end=str(x.date.max().date()))

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    a=pd.read_parquet(ROOT/'reports/adaptive_residual_20261103/predictions.parquet');a=a[(a.asset!='portfolio')&a.method.isin(['vol80','frozen1_scaled','frozen5_scaled','direct80'])]
    b=pd.read_parquet(ROOT/'reports/search_linked_20261103/predictions.parquet');b=b[(b.asset!='portfolio')&b.method.isin(['global_center_linked_residual_5year','linked_center_global_residual_5year','linked_center_linked_residual_5year'])]
    r=pd.concat([a,b],ignore_index=True);assert not (r.asset=='portfolio').any()
    reference=set(map(tuple,a[(a.model=='ridge')&(a.method=='vol80')][['asset','date']].to_numpy()))
    for _,x in r.groupby(['model','method']):assert set(map(tuple,x[['asset','date']].to_numpy()))==reference
    rows=[]
    for (asset,model,method),x in r.groupby(['asset','model','method']):
        for regime in ['all','high_vol','market_crash','asset_crash']:
            z=x if regime=='all' else x[x[regime]]
            if len(z):rows.append(dict(asset=asset,model=model,method=method,regime=regime,**metrics(z)))
    per=pd.DataFrame(rows);per.to_csv(OUT/'per_asset.csv',index=False)
    allrows=[]
    for (model,method),x in r.groupby(['model','method']):
        for regime in ['all','high_vol','market_crash','asset_crash']:
            z=x if regime=='all' else x[x[regime]]
            if len(z):allrows.append(dict(model=model,method=method,regime=regime,**metrics(z)))
    pd.DataFrame(allrows).to_csv(OUT/'pooled_assets.csv',index=False)
    per[per.regime=='all'].groupby(['model','method'])[['center_mae','center_rmse','coverage','width','lower_breach']].mean().to_csv(OUT/'equal_asset_average.csv')
    gates=per[per.regime=='all'].copy();gates['width_coverage_pass']=(gates.width<=5)&(gates.coverage>=.8)
    gates[['asset','model','method','n','coverage','width','width_coverage_pass']].to_csv(OUT/'asset_gates.csv',index=False)
    r.to_parquet(OUT/'asset_predictions.parquet',index=False)
    # A historical observed-shock example uses asset model outputs only.
    chosen=r[(r.model=='ridge')&(r.method=='global_center_linked_residual_5year')&r.asset.isin(['005930','005380'])]
    day=chosen.groupby('date').asset.nunique().loc[lambda s:s.eq(2)].index.max();z=chosen[chosen.date==day]
    data=build(pd.read_parquet(ROOT/'exports/seongjin_gold_v1_1/gold_stress_daily.parquet'))
    query=data[(data.date==day)&data.asset.isin(['005930','005380'])]
    outputs={t.asset:dict(point_return_pct=t.center,market_state_id=str(day.date()),scenario_id='observed-shock-'+str(day.date()),horizon_days=5) for t in z.itertuples()}
    result=apply_asset_returns({'005930':50_000_000,'005380':50_000_000},outputs)
    result['evaluation_date']=str(day.date());result['actual_pnl_krw']=float(z.actual.sum()*500_000)
    result['purpose']='종목별 결과 합산 확인용이며 최종 채택 모델은 아닙니다.'
    result['asset_intervals']=z[['asset','center','median','q10','q90','actual']].to_dict('records')
    result['shock_inputs']=query.iloc[0][['shock_fx','shock_rate','shock_oil','shock_vix']].to_dict()
    (OUT/'holdings_example.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    query[['asset','date','end_date']+FEATURES].to_csv(OUT/'example_inputs.csv',index=False)
    (OUT/'verification.json').write_text(json.dumps({'same_asset_date_pairs':True,'asset_date_samples':len(reference),'asset_count':len(r.asset.unique()),'direct_portfolio_forecasts_excluded':True,'retraining':False,'source':'saved time-ordered OOS forecasts; corrected asset-first evaluation, not new model improvement','blind':False},indent=2),encoding='utf8')
    print(pd.DataFrame(allrows).query('regime=="all"')[['model','method','n','center_mae','coverage','width']].round(3).to_string(index=False))
    print('passed_asset_method_pairs',gates.width_coverage_pass.sum())
if __name__=='__main__':main()
