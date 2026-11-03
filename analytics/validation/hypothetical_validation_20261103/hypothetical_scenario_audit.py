"""Separate historical reconstruction evidence from hypothetical scenario validation."""
import json,hashlib
import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler
from asset_feature_research import ROOT,make_data,model,FEATURES,EXPANDED,INTERACTIONS,CONTEXT,SHOCKS,A_STATE
OUT=ROOT/'reports/hypothetical_validation_20261103'
SCENARIOS={'zero':(0,0),'half':(2.5,50),'requested':(5,100),'one_and_half':(7.5,150),'fx_only':(5,0),'rate_only':(0,100),'fx_half_rate_full':(2.5,100),'fx_full_rate_half':(5,50),'reverse':(-5,-100)}

def query(t,fx,rate):
    t=t.copy();t['shock_fx']=fx;t['shock_rate']=rate;t['shock_oil']=0.;t['shock_vix']=0.
    for s in SHOCKS:
        for c in CONTEXT:t[s+'__'+c]=t[s]*t[c]
    return t

def run():
    OUT.mkdir(parents=True,exist_ok=True);path=ROOT/'exports/seongjin_gold_v1_1/gold_stress_daily.parquet';g=pd.read_parquet(path)
    history,_=make_data(g);inference,_=make_data(g,require_outcome=False);asof=inference.date.max();rows=[];support=[];cases=[];decomp=[];states=[];stability=[]
    old=pd.read_parquet(ROOT/'reports/asset_feature_research_20261103/learning_table.parquet')
    pd.testing.assert_frame_equal(history[old.columns].reset_index(drop=True),old.reset_index(drop=True))
    protocol={'as_of':str(asof.date()),'gold_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'horizon':'5trading days','scenario':'USDKRW+5%, US10Y+100bp, WTI0%, VIX0points','holding_example':'1000000KRW per asset; no portfolio ML',
       'model_status':'research only; full and recent8 refit on labels ending earlier than snapshot minus20calendar days; frozen2026 reproduces previous validation training boundary',
       'scenario_grid':SCENARIOS,'support':'state-only top20% of nonoverlapping 5day windows, minimum120; joint near shock tolerances FX1.25pp and rate25bp; optional oil2.5pp and VIX2points; descriptive not approval test',
       'attribution':'two-factor Shapley differences relative to zero-FX/zero-rate with oil/VIX fixed0; numerical input attribution not causal effect',
       'no_probability_claim':True,'cloud_changes':False,'publication_limit':'original release times/vintages unavailable'}
    (OUT/'protocol.json').write_text(json.dumps(protocol,ensure_ascii=False,indent=2),encoding='utf8')
    for asset,f in history.groupby('asset'):
        f=f.sort_values('date');q=inference[(inference.asset==asset)&(inference.date==asof)]
        if len(q)!=1:continue
        t=q.iloc[0];assert pd.isna(t.target) and pd.isna(t.end_date)
        mature=f[f.end_date<asof-pd.Timedelta(days=20)]
        ss=StandardScaler().fit(mature[A_STATE]);h=mature.iloc[::6].copy();distance=((ss.transform(h[A_STATE])-ss.transform(q[A_STATE])[0])**2).mean(axis=1)
        h['state_distance']=np.sqrt(distance);n=min(len(h),max(120,int(np.ceil(len(h)*.2))));candidates=h.nsmallest(n,'state_distance').copy()
        assert (h.end_date.to_numpy()[:-1]<h.date.to_numpy()[1:]).all()
        for label,(fx,rate) in SCENARIOS.items():
            tq=query(t,fx,rate);assert np.array_equal(tq[A_STATE].to_numpy(),t[A_STATE].to_numpy())
            for scope,bank in [('all_history',h),('similar_market',candidates)]:
                match=bank[(abs(bank.shock_fx-fx)<=1.25)&(abs(bank.shock_rate-rate)<=25)]
                all4=match[(abs(match.shock_oil)<=2.5)&(abs(match.shock_vix)<=2)]
                support.append(dict(asset=asset,scenario=label,scope=scope,candidates=len(bank),fx_rate_matches=len(match),four_factor_matches=len(all4),fx_min=bank.shock_fx.min(),fx_max=bank.shock_fx.max(),rate_min=bank.shock_rate.min(),rate_max=bank.shock_rate.max(),state_nearest=bank.state_distance.min()))
        candidates['shock_distance']=np.sqrt(((candidates.shock_fx-5)/1.25)**2+((candidates.shock_rate-100)/25)**2)
        nearest=candidates.nsmallest(5,'shock_distance')
        for _,hrow in nearest.iterrows():cases.append(dict(asset=asset,date=hrow.date,end_date=hrow.end_date,state_distance=hrow.state_distance,shock_distance=hrow.shock_distance,fx=hrow.shock_fx,rate=hrow.shock_rate,oil=hrow.shock_oil,vix=hrow.shock_vix,observed_return=hrow.target,historical_replay_pnl_1m=hrow.target*10000))
        states.append(t[['asset','date','scale']+A_STATE+['asset_trend5','asset_trend20','asset_trend60','relative_market20']].to_dict())
        frames={'current_mature':mature,'recent8':mature[mature.date>=asof-pd.DateOffset(years=8)],'frozen2026':f[f.end_date<pd.Timestamp('2025-01-01')-pd.Timedelta(days=20)]}
        for version,train in frames.items():
            for name,features in [('ridge',FEATURES),('lightgbm',EXPANDED),('ridge_interactions',EXPANDED+INTERACTIONS)]:
                m=model(name);m.fit(train[features],train.target/train.scale)
                points={label:float(m.predict(query(t,fx,rate)[features].astype(float).to_frame().T)[0]*t.scale) for label,(fx,rate) in SCENARIOS.items()}
                for label,value in points.items():rows.append(dict(asset=asset,model=name,version=version,scenario=label,return_pct=value,pnl_per_1m=value*10000,train_n=len(train),train_label_end=train.end_date.max(),state_date=asof))
                b=points['zero'];full=points['requested'];fx=.5*((points['fx_only']-b)+(full-points['rate_only']));rate=.5*((points['rate_only']-b)+(full-points['fx_only']))
                assert abs(b+fx+rate-full)<1e-9
                decomp.append(dict(asset=asset,model=name,version=version,zero_shock_return=b,fx_contribution_pp=fx,rate_contribution_pp=rate,full_return=full,pnl_per_1m=full*10000))
                if version=='current_mature' and asset in ['005930','005380'] and name in ['ridge','lightgbm']:
                    # Remove nearest selected episode as a sensitivity test, not a causal test.
                    event=nearest.iloc[0];reduced=train[(train.end_date<event.date-pd.Timedelta(days=20))|(train.date>event.end_date+pd.Timedelta(days=20))]
                    alt=model(name);alt.fit(reduced[features],reduced.target/reduced.scale);value=float(alt.predict(query(t,5,100)[features].astype(float).to_frame().T)[0]*t.scale)
                    stability.append(dict(asset=asset,model=name,excluded_episode=str(event.date.date()),removed_train_rows=len(train)-len(reduced),full_return=full,without_episode_return=value,delta=value-full))
        print(asset,flush=True)
    pd.DataFrame(rows).to_csv(OUT/'scenario_returns.csv',index=False);pd.DataFrame(support).to_csv(OUT/'historical_support.csv',index=False);pd.DataFrame(cases).to_csv(OUT/'historical_cases.csv',index=False);pd.DataFrame(decomp).to_csv(OUT/'factor_attribution.csv',index=False);pd.DataFrame(states).to_csv(OUT/'query_states.csv',index=False);pd.DataFrame(stability).to_csv(OUT/'event_sensitivity.csv',index=False)
    snapshot=g[pd.to_datetime(g.trading_date)==asof];snapshot.to_parquet(OUT/'gold_snapshot.parquet',index=False)
    (OUT/'verification.json').write_text(json.dumps({'training_table_unchanged':True,'latest_state_without_future_outcomes':True,'state_date':str(asof.date()),'shock_grid_preserves_A_state':True,'factor_contributions_sum_to_result':True,'no_portfolio_model':True,'no_scenario_probability_claim':True},indent=2))
if __name__=='__main__':run()

