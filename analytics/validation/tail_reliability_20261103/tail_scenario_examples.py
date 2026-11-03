"""Local scenario calculator: distinguish model estimates, a tail guard and observed evidence."""
import json,math,hashlib
import joblib
import numpy as np
import pandas as pd
from asset_feature_research import make_data,SHOCKS,A_STATE
from tail_reliability_research import SRC,OUT

def main():
    selected=json.loads((SRC/'selected_assets.json').read_text());g=pd.read_parquet(SRC/'research_daily_input.parquet')
    current,_=make_data(g,require_outcome=False);d=pd.read_parquet(SRC/'learning_table.parquet');base=pd.read_parquet(SRC/'predictions.parquet')
    pairs=pd.read_csv(SRC/'selected_asset_shock_pairs.csv',dtype={'asset':str});names=dict(zip(pairs.asset,pairs['name']))
    scenarios={'fx_plus1':dict(shock_fx=1),'rate_plus10bp':dict(shock_rate=10),'oil_plus5':dict(shock_oil=5),'vix_plus2':dict(shock_vix=2),'fx_plus5_rate_plus100bp':dict(shock_fx=5,shock_rate=100)}
    rows=[]
    for asset in selected:
        t=current[current.asset==asset].sort_values('date').iloc[-1]
        valid=g[(g.asset_id==asset)&(pd.to_datetime(g.trading_date)==t.date)]
        assert len(valid)==1 and valid.iloc[0].quality_status=='valid'
        model_path=SRC/'models'/asset/'lgb_all4.joblib'
        package=joblib.load(model_path);model=package['model'];features=package['features']
        train=d[(d.asset==asset)&(d.end_date<=pd.Timestamp(package['train_end']))].sort_values('date');sparse=train.iloc[::6]
        # A uses market state only. Its candidate IDs do not change with shocks.
        sd=train[A_STATE].std().clip(lower=1e-8)
        state_dist=(((sparse[A_STATE]-t[A_STATE].to_numpy(dtype=float))/sd)**2).mean(axis=1)
        a=sparse.loc[state_dist.nsmallest(min(100,len(sparse))).index].copy()
        shock_sd=train[SHOCKS].std().clip(lower=1e-8)
        old=base[(base.asset==asset)&(base.model=='lgb')&(base.date.dt.year==2026)]
        offsets={}
        for spec in ['all4','state_only']:
            b=old[old.spec==spec].merge(d[['asset','date','scale']],on=['asset','date'],validate='one_to_one')
            lo=(b.q10-b.center)/b.scale;hi=(b.q90-b.center)/b.scale
            assert lo.max()-lo.min()<1e-8 and hi.max()-hi.min()<1e-8
            offsets[spec]=(lo.iloc[0],hi.iloc[0])
        def predict(shock):
            x=t[features].copy()
            for k in SHOCKS:x[k]=shock.get(k,0)
            return float(model.predict(pd.DataFrame([x],columns=features))[0]*t.scale)
        zero=predict({})
        for name,shock in scenarios.items():
            values={k:float(shock.get(k,0)) for k in SHOCKS};point=predict(values);coalitions={}
            for mask in range(16):coalitions[mask]=predict({k:values[k] if mask&(1<<i) else 0 for i,k in enumerate(SHOCKS)})
            contributions={}
            for i,k in enumerate(SHOCKS):
                contribution=0
                for mask in range(16):
                    if mask&(1<<i):continue
                    n=mask.bit_count();weight=math.factorial(n)*math.factorial(3-n)/math.factorial(4)
                    contribution+=weight*(coalitions[mask|(1<<i)]-coalitions[mask])
                contributions[k]=contribution
            assert abs(sum(contributions.values())-(point-zero))<1e-8
            lo=point+offsets['all4'][0]*t.scale;hi=point+offsets['all4'][1]*t.scale
            guard=point+min(offsets['all4'][0],offsets['state_only'][0])*t.scale
            outside=[k for k,v in values.items() if v<train[k].min() or v>train[k].max()]
            dist=(((a[SHOCKS]-np.array([values[k] for k in SHOCKS]))/shock_sd)**2).mean(axis=1)
            evidence=a.loc[dist.nsmallest(5).index]
            rows.append({'asset':asset,'name':names[asset],'scenario':name,'state_date':str(t.date.date()),'train_label_end':package['train_end'],'holding_krw_example':1000000,
                'shocks':values,'conditional_center_return_pct':point,'zero_shock_center_pct':zero,'scenario_difference_pp':point-zero,'center_pnl_krw':point*10000,
                'model_q10_pct':lo,'model_q90_pct':hi,'conservative_lower_reference_pct':guard,'conservative_lower_pnl_krw':guard*10000,
                'model_contributions_pp':contributions,'contributions_are_causal':False,'outside_training_marginal_range':outside,
                'joint_support_certified':False,'nominal_probability_approved':False,'service_mode':'research_exploration',
                'model_sha256':hashlib.sha256(model_path.read_bytes()).hexdigest(),'return_scale_pct':float(t.scale),
                'input_features':{k:values[k] if k in SHOCKS else float(t[k]) for k in features},
                'historical_examples':[{'start':str(x.date.date()),'end':str(x.end_date.date()),'actual_return_pct':float(x.target),'actual_shocks':{k:float(x[k]) for k in SHOCKS}} for _,x in evidence.iterrows()],
                'interpretation':'Scenario-dependent model estimate and conservative reference, not a verified causal loss or a guaranteed probability interval. Historical examples have their own observed shocks.'})
    (OUT/'scenario_examples.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf8')
    pd.DataFrame([{k:v for k,v in x.items() if not isinstance(v,(list,dict))} for x in rows]).to_csv(OUT/'scenario_examples.csv',index=False)
    print('Created 30 labelled local examples; model contribution and currency identities verified.')

if __name__=='__main__':main()
