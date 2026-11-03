"""Fixed official-context ablations plus OOS residual market-state retrieval."""
import json,hashlib,joblib
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,as_completed
import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler
from asset_feature_research import model,SHOCKS
from research_shock_context import ROOT,SRC,COLS,INTER
from build_rich_context import OUT,FLOW_FEATURES,FLOW_RATIOS,MARKET_FLOW,PRICE_FEATURES,PEER_FEATURES,COMPANY_FEATURES
from report_long_universe import metric
FLOW=FLOW_FEATURES+FLOW_RATIOS+MARKET_FLOW
CROSS=['foreign_fx','institution_vix','debt_rate','operating_fx']
ALL=COLS+FLOW+PRICE_FEATURES+PEER_FEATURES+COMPANY_FEATURES+CROSS
SEARCH=['market_trend20','market_vol20','asset_trend20','relative_market20','beta60','vix_level']+FLOW_FEATURES+MARKET_FLOW+PEER_FEATURES
SPECS={'baseline':COLS,'flow':COLS+FLOW,'liquidity':COLS+PRICE_FEATURES,'peers':COLS+PEER_FEATURES,'company':COLS+COMPANY_FEATURES,'all':ALL,'all_no_shocks':[c for c in ALL if c not in SHOCKS+INTER+CROSS]}
ATTRIBUTION_GROUPS={'shock_and_interactions':SHOCKS+INTER+CROSS,'prior_flows':FLOW,'price_liquidity':PRICE_FEATURES,'peer_state':PEER_FEATURES,'company_accounts':COMPANY_FEATURES,'other_pre_shock_state':[c for c in COLS if c not in SHOCKS+INTER]}

def weighted_median(v,w):
    ix=np.argsort(v);return float(v[ix][np.searchsorted(np.cumsum(w[ix]),.5*np.sum(w))])

def main():
    d=pd.read_parquet(OUT/'learning_table.parquet');assets=json.loads((SRC/'selected_assets.json').read_text())
    d['foreign_fx']=d.foreign_flow_20*d.shock_fx;d['institution_vix']=d.institution_flow_20*d.shock_vix;d['debt_rate']=d.debt_assets*d.shock_rate;d['operating_fx']=d.operating_assets*d.shock_fx
    reference=pd.read_parquet(ROOT/'reports/center_audit_20261103/predictions.parquet');reference=reference[reference.method.eq('clean_raw')]
    gold=ROOT/'exports/seongjin_gold_v1_1/gold_stress_daily.parquet';digest=hashlib.sha256(gold.read_bytes()).hexdigest()
    protocol=dict(cohort='Previous101 fixed; no reselection using current scores',specifications=SPECS,search_features=SEARCH,search_excludes_shocks=True,search_correction='Median of chronological OOS residuals from prior3years, ready label end<cut-20days; >=30 otherwise zero; local inverse-distance kernel vs same-pool global median',training='quarterly with label end<quarterstart-20days; fixed existing LGBM250 depth4; raw returns',calibration='Quarterly OOS residual bank begins2020, calibration/evaluation point sampling every6valid rows. Never use fitted residuals.',evaluation='Original2023-2026 dates intersected with prior-flow-supported rows; all methods identical keys; reused research period not blind',missing='Native NaN for absent financial/peer/liquidity data; no future imputation; no zero-fill cash flows',approved=False,gold_sha256=digest)
    (OUT/'protocol.json').write_text(json.dumps(protocol,indent=2),encoding='utf8');(OUT/'checkpoints').mkdir(exist_ok=True)
    fingerprint=hashlib.sha256(Path(__file__).read_bytes()+json.dumps(protocol,sort_keys=True).encode()+(OUT/'learning_table.parquet').read_bytes()).hexdigest()
    rows=[];folds=[];search_rows=[];fail=[];coverage=[];attributions=[]
    def run(a):
        checkpoint=OUT/'checkpoints'/f'{a}.joblib'
        if checkpoint.exists():
            cached=joblib.load(checkpoint)
            if cached['fingerprint']==fingerprint:return cached['result']
        f=d[d.asset.eq(a)].sort_values('date');ref=reference[reference.asset.eq(a)].sort_values('date');ref=ref[ref.date.isin(f.date)];bank=[];result=[];audit=[];retrieval=[];contributions=[]
        for quarter in pd.period_range('2020Q1','2026Q4',freq='Q'):
            cut=quarter.start_time;tr=f[f.end_date<cut-pd.Timedelta(days=20)]
            if len(tr)<500:continue
            if quarter.year<2023:
                te=f[(f.date>=cut)&(f.end_date<=quarter.end_time)].iloc[::6];old=None
            else:
                old=ref[ref.date.dt.to_period('Q').eq(quarter)]
                te=f.set_index('date').loc[old.date].reset_index()
            if te.empty:continue
            assert tr.end_date.max()<te.date.min()
            assert (te.end_date.to_numpy()[:-1]<te.date.to_numpy()[1:]).all()
            specs={'all':ALL} if quarter.year<2023 else SPECS
            all_center=None
            for kind,cols in specs.items():
                m=model('lgb').fit(tr[cols],tr.target);pred=m.predict(te[cols])
                if quarter==pd.Period('2026Q4') and kind in ['baseline','all','all_no_shocks']:
                    folder=OUT/'models'/a;folder.mkdir(parents=True,exist_ok=True)
                    joblib.dump(dict(model=m,features=cols,train_label_end=str(tr.end_date.max()),approved=False),folder/(kind+'.joblib'))
                if kind=='all':all_center=pred
                if old is not None:
                    assert np.allclose(te.target,old.actual)
                    z=old.copy();z['method']=kind;z['center']=pred;result.append(z)
                    if kind=='all':
                        shap=m.predict(te[cols],pred_contrib=True)
                        assert np.allclose(shap.sum(axis=1),pred,atol=1e-7)
                        for group,features in ATTRIBUTION_GROUPS.items():
                            contribution=shap[:,[cols.index(c) for c in features]].sum(axis=1)
                            for scope,mask in [('all',np.ones(len(te),dtype=bool)),('crash',te.target.to_numpy()<=-5),('rally',te.target.to_numpy()>=5)]:
                                if mask.any():contributions.append(dict(asset=a,quarter=str(quarter),scope=scope,group=group,n=int(mask.sum()),mean_signed_pp=float(contribution[mask].mean()),mean_absolute_pp=float(np.abs(contribution[mask]).mean()),causal_effect=False))
            if old is not None:
                pool=pd.concat(bank,ignore_index=True) if bank else pd.DataFrame()
                if len(pool):pool=pool[(pool.end_date<cut-pd.Timedelta(days=20))&(pool.date>=cut-pd.DateOffset(years=3))]
                global_center=all_center.copy();local_center=all_center.copy()
                if len(pool)>=30:
                    med=tr[SEARCH].median().fillna(0);ss=StandardScaler().fit(tr[SEARCH].fillna(med));hist=ss.transform(pool[SEARCH].fillna(med));current=ss.transform(te[SEARCH].fillna(med));res=pool.residual.to_numpy()
                    global_center+=np.median(res)
                    for i,point in enumerate(current):
                        dist=np.mean((hist-point)**2,axis=1);order=np.argsort(dist);selected=order[:min(50,len(order))];bw=max(float(np.median(dist[selected])),1e-8);w=np.exp(-np.minimum(dist[selected]/bw,60));local_center[i]+=weighted_median(res[selected],w)
                        retrieval.append(dict(asset=a,date=str(te.date.iloc[i]),pool_n=len(pool),effective_n=float(w.sum()**2/(w@w)),closest_date=str(pool.date.iloc[order[0]]),closest_label_end=str(pool.end_date.iloc[order[0]]),correction=float(local_center[i]-all_center[i]),shock_used_in_search=False))
                for name,pred in [('all_global_cal',global_center),('all_search',local_center)]:
                    z=old.copy();z['method']=name;z['center']=pred;result.append(z)
            # Appended after query; eligible only in a later quarter after label completion.
            p=te[['date','end_date']+SEARCH].copy();p['residual']=te.target.to_numpy()-all_center;bank.append(p)
            audit.append(dict(asset=a,quarter=str(quarter),train_n=len(tr),train_end=str(tr.end_date.max()),test_start=str(te.date.min()),test_n=len(te),financial_training_rows=int(tr.financial_missing.eq(0).sum())))
        out=pd.concat(result,ignore_index=True);out.to_parquet(OUT/'checkpoints'/f'{a}.parquet',index=False)
        value=(out,audit,retrieval,dict(asset=a,old_test_rows=len(reference[reference.asset.eq(a)]),matched_test_rows=len(ref)),contributions)
        joblib.dump(dict(fingerprint=fingerprint,result=value),checkpoint)
        return value
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures={pool.submit(run,a):a for a in assets}
        for i,fu in enumerate(as_completed(futures),1):
            try:
                r,a,s,c,ex=fu.result();rows.append(r);folds.extend(a);search_rows.extend(s);coverage.append(c);attributions.extend(ex)
            except Exception as e:fail.append(dict(asset=futures[fu],error=repr(e)))
            (OUT/'training_progress.json').write_text(json.dumps(dict(status='running',completed=i,total=len(assets),failed=fail),indent=2));print(i,len(assets),flush=True)
    assert not fail,fail
    r=pd.concat(rows,ignore_index=True).drop(columns='up_score',errors='ignore');assert r.groupby(['asset','date']).size().eq(9).all();r.to_parquet(OUT/'predictions.parquet',index=False)
    pd.DataFrame(folds).to_csv(OUT/'time_audit.csv',index=False);pd.DataFrame(search_rows).to_csv(OUT/'market_search_audit.csv',index=False);pd.DataFrame(coverage).to_csv(OUT/'matched_samples.csv',index=False)
    pd.DataFrame(attributions).to_csv(OUT/'model_attribution.csv',index=False)
    pairs=pd.read_csv(SRC/'eligible_pairs.csv',dtype={'asset':str});event=pd.Series(False,index=r.index)
    for _,p in pairs.iterrows():event|=r.asset.eq(p.asset)&r[p.shock+'_event']
    summaries=[]
    for scope,mask in [('all',pd.Series(True,index=r.index)),('selected_shock_events',event),('crash',r.actual<=-5),('rally',r.actual>=5)]:
        for method,z in r[mask].groupby('method'):summaries.append(dict(scope=scope,method=method,**metric(z)))
    pd.DataFrame(summaries).to_csv(OUT/'metrics.csv',index=False)
    pd.DataFrame([dict(asset=a,method=m,**metric(z)) for (a,m),z in r.groupby(['asset','method'])]).to_csv(OUT/'asset_metrics.csv',index=False)
    assert hashlib.sha256(gold.read_bytes()).hexdigest()==digest
    (OUT/'training_progress.json').write_text(json.dumps(dict(status='complete',completed=len(assets),failed=[],gold_unchanged=True),indent=2))

if __name__=='__main__':main()
