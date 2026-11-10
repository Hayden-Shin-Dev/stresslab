"""Complete independent model risk bands and inspect identity effects, using saved design."""
import json,sys
import numpy as np
import pandas as pd
from model_redesign_research import ROOT,OUT,FEATURES,EXPANDED,SCENARIOS,pooled_x,learner,date_weights,model
from asset_feature_research import make_data
from adaptive_residual_benchmark import weighted_q

def main():
    d=pd.read_parquet(OUT/'learning_table.parquet');g=pd.read_parquet(ROOT/'exports/seongjin_gold_v1_1/gold_stress_daily.parquet');infer,_=make_data(g,require_outcome=False);q=infer[infer.date==infer.date.max()];s=pd.read_csv(OUT/'asset_shock_sensitivity.csv',dtype={'asset':str})
    for asset,f in d.groupby('asset'):
        f=f.sort_values('date');t=q[q.asset==asset].iloc[0]
        for name,features in [('ridge',FEATURES),('lgb_independent',EXPANDED)]:
            errors=[]
            for year in range(2022,2027):
                cc=pd.Timestamp(year-1,1,1);cut=pd.Timestamp(year,1,1);tr=f[f.end_date<cc-pd.Timedelta(days=20)];ca=f[(f.date>=cc)&(f.end_date<cut-pd.Timedelta(days=20))].iloc[::6]
                if len(tr)<250 or len(ca)<30:continue
                m=model('ridge' if name=='ridge' else 'lgb').fit(tr[features],tr.target/tr.scale);cp=m.predict(ca[features])*ca.scale.to_numpy();errors.extend(((ca.target.to_numpy()-cp)/ca.scale.to_numpy()).tolist())
            v=np.asarray(errors);adj=weighted_q(v,np.ones(len(v))/len(v))*t.scale
            mask=(s.asset==asset)&(s.model==name)&(s.version=='full');s.loc[mask,'q10']=s.loc[mask,'center']+adj[0];s.loc[mask,'q90']=s.loc[mask,'center']+adj[2];s.loc[mask,'cal_n']=len(v)
        print(asset,flush=True)
    s.to_csv(OUT/'asset_shock_sensitivity.csv',index=False)
    cats=sorted(d.asset.unique());tr=d[d.end_date<pd.Timestamp('2025-01-01')-pd.Timedelta(days=20)];pm=learner().fit(pooled_x(tr,cats),tr.target/tr.scale,sample_weight=date_weights(tr))
    pd.DataFrame({'feature':EXPANDED+['asset_id'],'split_count':pm.feature_importances_}).to_csv(OUT/'pooled_feature_usage.csv',index=False)
    # Artificial ID swap holds all numeric inputs and scale fixed. Architecture check only.
    ref=q[q.asset=='005930'].copy();ref.loc[:,['shock_fx','shock_rate','shock_oil','shock_vix']]=[5,100,0,0];check=pd.concat([ref.assign(asset=a) for a in cats],ignore_index=True)
    pred=pm.predict(pooled_x(check,cats))*ref.scale.iloc[0];pd.DataFrame({'asset_identity':cats,'fixed_numeric_state_return':pred}).to_csv(OUT/'identity_isolation.csv',index=False)
    # A simple holdings example, not a portfolio model or joint interval.
    from asset_stress_results import apply_asset_returns
    chosen=s[(s.asset.isin(['005930','005380']))&(s.model=='pooled')&(s.version=='full')&(s.scenario=='fx5_rate100')]
    inp={x.asset:dict(point_return_pct=x.center,market_state_id=str(x.state_date),scenario_id='fx5_rate100',horizon_days=5) for x in chosen.itertuples()}
    result=apply_asset_returns({'005930':1000000,'005380':1000000},inp);result['approved_model']=False;(OUT/'holdings_example.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    v=json.loads((OUT/'verification.json').read_text());v['identity_swap_changes_output']=bool(np.ptp(pred)>1e-9);v['asset_id_split_count']=int(pm.feature_importances_[-1]);(OUT/'verification.json').write_text(json.dumps(v,indent=2))
if __name__=='__main__':main()
