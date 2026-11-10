"""Data and saved out-of-sample prediction audit. No model fitting or cloud writes."""
import json,hashlib
from pathlib import Path
import numpy as np
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'reports/shock_evidence_20261103'
THRESHOLDS={'shock_fx':[1,3,5],'shock_rate':[25,50,100],'shock_oil':[5,10,20],'shock_vix':[3,5,10]}

def episodes(z):
    end=None;n=0
    for r in z.sort_values('date').itertuples():
        if end is None or r.date>end:n+=1
        end=r.end_date if end is None else max(end,r.end_date)
    return n

def episode_starts(z):
    end=None;ids=[]
    for idx,r in z.sort_values('date').iterrows():
        if end is None or r.date>end:ids.append(idx)
        end=r.end_date if end is None else max(end,r.end_date)
    return z.loc[ids]

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    goldpath=ROOT/'exports/seongjin_gold_v1_1/gold_stress_daily.parquet';g=pd.read_parquet(goldpath)
    d=pd.read_parquet(ROOT/'reports/model_redesign_20261103/learning_table.parquet');h=d.sort_values('date').drop_duplicates('date')
    names={a['asset_id']:a['name'] for a in json.loads((ROOT/'data/research/official20_20261102/universe.json').read_text(encoding='utf8'))['assets']}
    quantiles=[];counts=[];response=[]
    for shock,thresholds in THRESHOLDS.items():
        v=h[shock];quantiles.append(dict(shock=shock,n=len(v),start=str(h.date.min()),end=str(h.date.max()),minimum=v.min(),q01=v.quantile(.01),q05=v.quantile(.05),median=v.median(),q95=v.quantile(.95),q99=v.quantile(.99),maximum=v.max()))
        for threshold in thresholds:
            for sign in [1,-1]:
                mask=sign*h[shock]>=threshold;z=h[mask]
                counts.append(dict(shock=shock,threshold=threshold,direction='up' if sign==1 else 'down',overlap_windows=len(z),total_windows=len(h),frequency=len(z)/len(h),merged_episodes=episodes(z),spaced_windows=int((sign*h.iloc[::6][shock]>=threshold).sum()),spaced_denominator=len(h.iloc[::6])))
                for asset,f in d.groupby('asset'):
                    s=f[sign*f[shock]>=threshold]
                    es=episode_starts(s)
                    response.append(dict(asset=asset,name=names[asset],shock=shock,threshold=threshold,direction='up' if sign==1 else 'down',n=len(s),merged_episodes=episodes(s),negative_fraction=(s.target<0).mean(),positive_fraction=(s.target>0).mean(),mean_return=s.target.mean(),median_return=s.target.median(),q10=s.target.quantile(.1),q90=s.target.quantile(.9),eligible_windows=len(f),episode_first_negative_fraction=(es.target<0).mean(),episode_first_median=es.target.median()))
    pd.DataFrame(quantiles).to_csv(OUT/'shock_distribution.csv',index=False);pd.DataFrame(counts).to_csv(OUT/'shock_counts.csv',index=False);pd.DataFrame(response).to_csv(OUT/'asset_observed_responses.csv',index=False)
    # Joint support and correlations are counted once per date, never once per stock.
    h[list(THRESHOLDS)].corr().to_csv(OUT/'shock_correlations.csv')
    joint=h[(h.shock_fx>=5)&(h.shock_rate>=100)]
    sens=pd.read_csv(ROOT/'reports/selection_target_20261103/sensitivity.csv',dtype={'asset':str});sens.to_csv(OUT/'historical_sensitivity.csv',index=False)
    # Reuse the already trained, identically configured LightGBM ablation.
    a=pd.read_csv(ROOT/'reports/asset_feature_research_20261103/center_ablations.csv',dtype={'asset':str},parse_dates=['date']);a=a[a.method=='lgb_no_shock']
    b=pd.read_parquet(ROOT/'reports/asset_feature_research_20261103/predictions.parquet');b=b[b.method=='lgb_expanded_residual']
    p=a.merge(b,on=['asset','date'],suffixes=('_state','_shock'),validate='one_to_one');assert len(p)==len(a)==len(b);assert np.max(abs(p.actual_state-p.actual_shock))<1e-9
    p['delta']=p.center_mae_shock-p.center_mae_state;p['se_state']=(p.center_state-p.actual_state)**2;p['se_shock']=(p.center_shock-p.actual_shock)**2
    metrics=[];annual=[]
    for asset,z in [('ALL',p)]+list(p.groupby('asset')):
        z=z.sort_values('date');v=z.groupby('date').delta.agg(['sum','count']);n=len(v);rng=np.random.default_rng(20261103)
        ids=np.array([np.concatenate([(s+np.arange(10))%n for s in rng.integers(n,size=int(np.ceil(n/10)))])[:n] for _ in range(1000)])
        boot=v['sum'].to_numpy()[ids].sum(1)/v['count'].to_numpy()[ids].sum(1);mean=z.delta.mean();null=boot-mean;pv=(1+int((abs(null)>=abs(mean)).sum()))/1001
        metrics.append(dict(asset=asset,name=names.get(asset,'전체 표본'),n=len(z),dates=z.date.nunique(),state_mae=z.center_mae_state.mean(),shock_mae=z.center_mae_shock.mean(),mae_improvement_pct=-mean/z.center_mae_state.mean()*100,delta=mean,ci_low=np.quantile(boot,.025),ci_high=np.quantile(boot,.975),bootstrap_p=pv,state_rmse=np.sqrt(z.se_state.mean()),shock_rmse=np.sqrt(z.se_shock.mean()),relative_mse_gain=1-z.se_shock.sum()/z.se_state.sum(),crash_state_mae=z[z.asset_crash_state].center_mae_state.mean(),crash_shock_mae=z[z.asset_crash_state].center_mae_shock.mean()))
        for year,s in z.groupby(z.date.dt.year):annual.append(dict(asset=asset,year=year,n=len(s),state_mae=s.center_mae_state.mean(),shock_mae=s.center_mae_shock.mean(),delta=s.delta.mean()))
    met=pd.DataFrame(metrics);ix=met.index[met.asset!='ALL'];pv=met.loc[ix,'bootstrap_p'].to_numpy();order=np.argsort(pv);q=np.empty(len(pv));q[order]=np.minimum.accumulate((pv[order]*len(pv)/np.arange(1,len(pv)+1))[::-1])[::-1];met.loc[ix,'bh_q']=np.minimum(q,1)
    met.to_csv(OUT/'shock_increment_by_asset.csv',index=False);pd.DataFrame(annual).to_csv(OUT/'shock_increment_by_year.csv',index=False)
    p[['asset','date','actual_state','center_state','center_shock','delta']].to_parquet(OUT/'matched_prediction_evidence.parquet',index=False)
    # Descriptive present-day business groups; not a historical sector feature.
    groups={'반도체':['005930','005935','000660'],'전자부품':['009150'],'배터리':['006400','373220'],'자동차 및 부품':['005380','000270','012330'],'금융 및 보험':['105560','055550','086790','032830'],'바이오':['207940','068270'],'지주 및 복합사업':['402340','028260','034730'],'방산 및 발전설비':['012450','034020']}
    pd.DataFrame([dict(asset=a,name=names[a],descriptive_group=k,historical_classification=False) for k,ids in groups.items() for a in ids]).to_csv(OUT/'universe_composition.csv',index=False)
    protocol={'new_models_trained':False,'gold_sha256':hashlib.sha256(goldpath.read_bytes()).hexdigest(),'diagnosis_scope':'eligible existing Gold-derived learning windows; not all global shock history','shock_horizon':'five Korean trading-row intervals, FX and WTI percent, US10Y bp, VIX points','counts':'unique dates; overlapping windows vs merged overlapping episodes vs fixed6row spaced sample; episodes are not proven independent events','reaction':'observed total stock returns; other shocks simultaneous, not causal effects','ablation':'saved perasset LightGBM same settings, expanded pre-shock market AND asset state vs same plus all4realized shocks; not pure market-index-only model; no new training','evaluation':'2023-2026 reused research period, retrospective realized-shock reconstruction, not blind','marginal_factor_effect':'no per-factor saved ablation, cannot attribute joint gain to each individual shock','publication':'available_at absent, not certified point-in-time','joint_fx5_rate100_windows':len(joint),'industry':'current descriptive business grouping only; not PIT sector membership','no_cloud_or_contract_changes':True}
    (OUT/'protocol.json').write_text(json.dumps(protocol,ensure_ascii=False,indent=2),encoding='utf8')
    print(met[['asset','state_mae','shock_mae','mae_improvement_pct','ci_low','ci_high','bh_q']].round(3).to_string(index=False))

if __name__=='__main__':main()
