"""Same-state shock isolation and failure review. No trading or cloud changes."""
import json,joblib
import numpy as np
import pandas as pd
from build_rich_context import OUT,SRC
from research_shock_context import CONTEXT
from asset_feature_research import SHOCKS

def derive(z):
    z=z.copy()
    for s in SHOCKS:
        for c in CONTEXT:z[s+'__'+c]=z[s]*z[c]
    z['foreign_fx']=z.foreign_flow_20*z.shock_fx
    z['institution_vix']=z.institution_flow_20*z.shock_vix
    z['debt_rate']=z.debt_assets*z.shock_rate
    z['operating_fx']=z.operating_assets*z.shock_fx
    return z

def main():
    d=pd.read_parquet(OUT/'learning_table.parquet');r=pd.read_parquet(OUT/'predictions.parquet')
    cases={'zero':[0,0,0,0],'fx_plus1':[1,0,0,0],'fx_plus5':[5,0,0,0],
           'rate_plus25':[0,25,0,0],'rate_plus100':[0,100,0,0],
           'oil_plus10':[0,0,10,0],'vix_plus10':[0,0,0,10],'fx5_rate100':[5,100,0,0]}
    assert SHOCKS==['shock_fx','shock_rate','shock_oil','shock_vix'],SHOCKS
    rows=[];fit_gap=[]
    for asset,z in d.groupby('asset'):
        path=OUT/'models'/asset/'all.joblib'
        if not path.exists():continue
        bundle=joblib.load(path);m=bundle['model'];cols=bundle['features']
        latest=z.sort_values('date').tail(1).copy();tr=z[z.end_date<=pd.Timestamp(bundle['train_label_end'])]
        for method in ['baseline','all','all_no_shocks']:
            saved=joblib.load(OUT/'models'/asset/(method+'.joblib'))
            fitted=saved['model'].predict(derive(tr)[saved['features']])
            holdout=r[(r.asset==asset)&(r.method==method)&(r.date>=pd.Timestamp('2026-10-01'))]
            fit_gap.append(dict(asset=asset,method=method,train_n=len(tr),train_mae_pp=float(np.abs(fitted-tr.target).mean()),
                recent_test_n=len(holdout),recent_test_mae_pp=float((holdout.center-holdout.actual).abs().mean()),
                diagnostic_only=True))
        med=tr[SHOCKS].median();scale=(tr[SHOCKS].quantile(.75)-tr[SHOCKS].quantile(.25)).replace(0,np.nan)
        for name,values in cases.items():
            x=latest.copy();x.loc[:,SHOCKS]=values;x=derive(x);pred=float(m.predict(x[cols])[0])
            distance=np.sqrt(((tr[SHOCKS]-values)/scale).pow(2).mean(axis=1))
            nearest=tr.loc[distance.idxmin()]
            rows.append(dict(asset=asset,state_date=str(latest.date.iloc[0]),scenario=name,**dict(zip(SHOCKS,values)),center_pp=pred,
                train_label_end=bundle['train_label_end'],nearest_joint_scaled_distance=float(distance.min()),
                nearest_shock_date=str(nearest.date),nearest_actual_return_pp=float(nearest.target),
                marginal_range_exceeded=bool(((np.array(values)<tr[SHOCKS].min())|(np.array(values)>tr[SHOCKS].max())).any()),
                observation_not_exact_match=True,approved=False))
    table=pd.DataFrame(rows);zero=table[table.scenario.eq('zero')].set_index('asset').center_pp
    table['change_from_zero_pp']=table.center_pp-table.asset.map(zero)
    table.to_csv(OUT/'same_state_scenarios.csv',index=False)
    pd.DataFrame(fit_gap).to_csv(OUT/'training_generalization_gap.csv',index=False)
    base=r[r.method.eq('baseline')];full=r[r.method.eq('all')]
    failure=full.merge(base[['asset','date','center']],on=['asset','date'],suffixes=('_all','_base'),validate='one_to_one')
    failure['error_all_pp']=(failure.center_all-failure.actual).abs();failure['error_base_pp']=(failure.center_base-failure.actual).abs()
    failure['error_change_pp']=failure.error_all_pp-failure.error_base_pp
    cols=['asset','date','actual','center_base','center_all','error_base_pp','error_all_pp','error_change_pp']
    failure.sort_values('error_all_pp',ascending=False).head(100)[cols].to_csv(OUT/'largest_failures.csv',index=False)
    (OUT/'scenario_definition.json').write_text(json.dumps(dict(order=SHOCKS,units=['percent_change','basis_points','percent_change','index_points'],unspecified_factors='Explicit zero change, not unknown',state='Latest fully labelled historical row; NOT live current state',model='2026Q4 frozen training',interpretation='Model association and support diagnostic, not causal effect, not validated extreme loss',scenario_values=cases),indent=2),encoding='utf8')

if __name__=='__main__':main()
