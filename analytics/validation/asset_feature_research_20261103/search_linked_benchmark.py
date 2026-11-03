"""State retrieval changes training weights and calibration weights; local research only."""
import json
import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler
from gold_quantile_benchmark import ROOT,build,FEATURES,STATE,SHOCKS
from adaptive_residual_benchmark import weighted_q,rec,summarize
import adaptive_residual_benchmark as base
OUT=ROOT/'reports/search_linked_20261103'

def weights(history,query):
    d=np.mean((history-query)**2,axis=1)
    bandwidth=max(float(np.quantile(d,.2)),1e-6)
    k=np.exp(-np.minimum(d/bandwidth,700));k/=k.sum()
    return .2/len(d)+.8*k,d

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    protocol={'state_search':STATE,'shock_inputs':SHOCKS,'rule':'training-standardized squared state distance; bandwidth20th percentile; 80% kernel plus20% uniform weights; Ridge alpha30; no test tuning','paths':['global center/global residual','global center/state-weighted residual','state-weighted center/global residual','state-weighted center/state-weighted residual'],'target':'80% nominal interval; width<=5pp; preserve crash capture','blind':False,'publication_limit':'Gold lacks original release vintages;20calendar-day label embargo does not certify PIT','cloud_changes':False}
    (OUT/'protocol.json').write_text(json.dumps(protocol,ensure_ascii=False,indent=2),encoding='utf8')
    g=pd.read_parquet(ROOT/'exports/seongjin_gold_v1_1/gold_stress_daily.parquet');data=build(g)
    market=g.groupby('trading_date').kospi_close.first().sort_index();cr=(market.shift(-5)/market-1)*100;cr.index=pd.to_datetime(cr.index)
    rows=[];evidence=[];isolations=[]
    for asset,f in data.groupby('asset'):
        f=f.sort_values('date')
        for year in [2023,2024,2025,2026]:
            cut=pd.Timestamp(year,1,1);cc=pd.Timestamp(year-1,1,1)
            tr=f[f.end_date<cc-pd.Timedelta(days=20)]
            ca=f[(f.date>=cc)&(f.end_date<cut-pd.Timedelta(days=20))].iloc[::6]
            te=f[(f.date>=cut)&(f.date<pd.Timestamp(year+1,1,1))].iloc[::6];te=te[te.end_date<pd.Timestamp(year+1,1,1)]
            if len(tr)<250 or len(ca)<30 or not len(te):continue
            assert tr.end_date.max()<ca.date.min() and ca.end_date.max()<te.date.min()
            ss=StandardScaler().fit(tr[STATE]);hs=ss.transform(tr[STATE]);cs=ss.transform(ca[STATE])
            fs=StandardScaler().fit(tr[FEATURES]);X=np.column_stack([np.ones(len(tr)),fs.transform(tr[FEATURES])]);y=(tr.target/tr.scale).to_numpy()
            penalty=np.diag([0]+[30]*len(FEATURES));beta=np.linalg.solve(X.T@X+penalty,X.T@y)
            def predict(t,local):
                x=np.r_[1,fs.transform(t[FEATURES].to_frame().T)[0]]
                w,d=weights(hs,ss.transform(t[STATE].to_frame().T)[0])
                b=np.linalg.solve(X.T@(X*(w*len(tr))[:,None])+penalty,X.T@(y*w*len(tr))) if local else beta
                return float(x@b*t.scale),w,d
            pools={}
            for local in [False,True]:
                cp=np.array([predict(t,local)[0] for _,t in ca.iterrows()])
                pool=ca[['date','end_date','scale']].copy();pool['ready']=pool.end_date+pd.Timedelta(days=20);pool['scaled']=(ca.target.to_numpy()-cp)/ca.scale.to_numpy();pools[local]=pool
            for _,t in te.iterrows():
                state=ss.transform(t[STATE].to_frame().T)[0];cw,cd=weights(cs,state)
                for local in [False,True]:
                    center,tw,td=predict(t,local)
                    for retrieve in [False,True]:
                        p=pools[local];w=cw if retrieve else np.ones(len(p))/len(p)
                        q=center+weighted_q(p.scaled,w)*t.scale
                        method=('linked_center' if local else 'global_center')+('_linked_residual' if retrieve else '_global_residual')
                        rows.append(rec(t,q,'ridge',method,p,w,False,tr.market_vol20.quantile(2/3),cr.get(t.date,np.nan),center))
                    if asset=='portfolio' and local:
                        ids=np.argsort(td)[:5]
                        for j in ids:evidence.append(dict(query=t.date,history=tr.date.iloc[j],end=tr.end_date.iloc[j],distance=td[j],weight=tw[j],actual_historical_return=tr.target.iloc[j],fx=tr.shock_fx.iloc[j],rate=tr.shock_rate.iloc[j]))
                        for label,change in [('base',{}),('fx_plus1',{'shock_fx':t.shock_fx+1}),('rate_plus25',{'shock_rate':t.shock_rate+25}),('market_down3',{'market_trend20':t.market_trend20-3})]:
                            alt=t.copy()
                            for k,v in change.items():alt[k]=v
                            ac,aw,ad=predict(alt,True)
                            if label in ['fx_plus1','rate_plus25']:assert np.array_equal(aw,tw)
                            isolations.append(dict(date=t.date,scenario=label,center=ac,base_center=center,search_weight_change=float(abs(aw-tw).sum())))
            print(asset,year,flush=True)
        pd.DataFrame(rows).to_parquet(OUT/'predictions.parquet',index=False)
    r=pd.DataFrame(rows);old=pd.read_parquet(ROOT/'reports/adaptive_residual_20261103/predictions.parquet')
    old=old[(old.model=='ridge')&old.method.isin(['vol80','vol90','frozen1_scaled','frozen5_scaled'])]
    a=r[r.method.eq('global_center_global_residual')].merge(old[old.method.eq('frozen1_scaled')],on=['date','asset'],suffixes=('_a','_b'),validate='one_to_one')
    assert len(a)==len(old[old.method.eq('frozen1_scaled')]) and np.max(abs(a.q10_a-a.q10_b))<1e-7 and np.max(abs(a.q90_a-a.q90_b))<1e-7
    r=pd.concat([r,old],ignore_index=True);r.to_parquet(OUT/'predictions.parquet',index=False)
    pd.DataFrame(evidence).to_csv(OUT/'retrieval_evidence.csv',index=False);pd.DataFrame(isolations).to_csv(OUT/'isolation.csv',index=False)
    r[r.asset.eq('portfolio')].to_csv(OUT/'portfolio_predictions.csv',index=False)
    (OUT/'verification.json').write_text(json.dumps({'baseline_reproduced':True,'same_evaluation_rows':True,'shock_change_does_not_change_first_stage_weights':True,'rows':len(r)},indent=2))
    base.OUT=OUT;summarize(r)
if __name__=='__main__':main()
