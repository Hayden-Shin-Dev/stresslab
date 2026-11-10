"""Frozen-width centre diagnostics. Local research only; no production writes."""
import json, hashlib
import numpy as np
import pandas as pd
from lightgbm import LGBMRegressor
from asset_feature_research import ROOT, EXPANDED, A_STATE, SHOCKS

SRC=ROOT/'reports/exposure_universe_20261103'
OUT=ROOT/'reports/center_response_20261103'

def main():
    OUT.mkdir(exist_ok=True)
    assets=json.loads((SRC/'selected_assets.json').read_text())
    d=pd.read_parquet(SRC/'learning_table.parquet')
    b=pd.read_parquet(SRC/'predictions.parquet')
    b=b[b.asset.isin(assets)&b.model.eq('lgb')&b.spec.eq('all4')].copy()
    protocol=dict(assets=assets, primary='Per-stock centre error; no interval widening',
        evaluation='Reused 2023-2026 development sample, not blind; retrospective actual 5-day shocks, not causal',
        split='Same annual baseline train cutoff: prior-year Jan1 minus20days; same 918 evaluation rows',
        methods=['baseline_normalized_median','raw_median','raw_mean','raw_tail_weighted_mean','A_then_shock_median'],
        tail_weight='Training labels only: 2x weight when abs(return)>=training90thpercentile; otherwise1. Not a conditional mean or median.',
        search='Training-only standardization. A excludes shocks; nearest200 nonoverlapping6-row windows; then nearest40 by four shocks; uniform median. No outcome selection.',
        interval='Keep each baseline lower/upper offset and width, translate with new centre. Diagnostic, not calibrated probability interval.',
        fixed5='Centre +/-2.5pp feasibility diagnostic, not approved interval',
        no_azure_changes=True,no_gold_changes=True,no_automatic_promotion=True,
        baseline_sha256=hashlib.sha256((SRC/'predictions.parquet').read_bytes()).hexdigest())
    (OUT/'protocol.json').write_text(json.dumps(protocol,ensure_ascii=False,indent=2),encoding='utf8')
    rows=[];audits=[];neighbors=[];isolation=[]
    for asset in assets:
        f=d[d.asset.eq(asset)].sort_values('date')
        for year in [2023,2024,2025,2026]:
            old=b[b.asset.eq(asset)&b.year.eq(year)].sort_values('date')
            if old.empty:continue
            tr=f[f.end_date<pd.Timestamp(year-1,1,1)-pd.Timedelta(days=20)]
            te=f.set_index('date').loc[old.date].reset_index()
            assert tr.end_date.max()<te.date.min()
            predictions={'baseline_normalized_median':old.center.to_numpy()}
            for name,objective,tail in [('raw_median','quantile',False),('raw_mean','regression',False),('raw_tail_weighted_mean','regression',True)]:
                m=LGBMRegressor(objective=objective,alpha=.5,n_estimators=250,learning_rate=.04,max_depth=4,num_leaves=15,min_child_samples=40,random_state=20261103,n_jobs=2,verbosity=-1)
                w=np.where(tr.target.abs()>=tr.target.abs().quantile(.9),2.,1.) if tail else None
                m.fit(tr[EXPANDED],tr.target,sample_weight=w)
                predictions[name]=m.predict(te[EXPANDED])
                zero=te[EXPANDED].copy();zero[SHOCKS]=0
                p0=m.predict(zero)
                for shock in SHOCKS:
                    alt=zero.copy();alt[shock]=te[shock].to_numpy();p1=m.predict(alt)
                    isolation.extend(dict(asset=asset,date=str(t),method=name,shock=shock,zero_center=float(a),one_shock_center=float(c)) for t,a,c in zip(te.date,p0,p1))
            sparse=tr.iloc[::6].copy()
            sd=tr[A_STATE].std().clip(lower=1e-8).to_numpy();ss=tr[SHOCKS].std().clip(lower=1e-8).to_numpy()
            pred=[]
            for _,t in te.iterrows():
                ad=np.mean(((sparse[A_STATE].to_numpy()-t[A_STATE].to_numpy(float))/sd)**2,axis=1)
                ix=np.argsort(ad)[:200]
                sd2=np.mean(((sparse.iloc[ix][SHOCKS].to_numpy()-t[SHOCKS].to_numpy(float))/ss)**2,axis=1)
                chosen=ix[np.argsort(sd2)[:40]];z=sparse.iloc[chosen]
                pred.append(float(z.target.median()))
                neighbors.append(dict(asset=asset,date=str(t.date),A_candidates=len(ix),B_cases=len(chosen),case_dates=';'.join(z.date.astype(str)),case_median=float(z.target.median()),case_q10=float(z.target.quantile(.1)),case_q90=float(z.target.quantile(.9)),case_positive_fraction=float(z.target.gt(0).mean()),shock_distance_mean=float(np.mean(np.sort(sd2)[:40]))))
            predictions['A_then_shock_median']=np.array(pred)
            for method,p in predictions.items():
                z=old.copy();z['method']=method;z['center']=p
                z['q10']=p+old.q10.to_numpy()-old.center.to_numpy();z['q90']=p+old.q90.to_numpy()-old.center.to_numpy()
                z['width']=z.q90-z.q10;z['error']=z.center-z.actual;z['mae']=z.error.abs()
                z['coverage']=(z.actual>=z.q10)&(z.actual<=z.q90);z['lower_breach']=z.actual<z.q10
                z['cover5']=z.mae<=2.5;z['crash']=z.actual<=-5;z['rally']=z.actual>=5
                z['crash_called']=z.center<=-5;z['rally_called']=z.center>=5
                z['direction_correct']=np.sign(z.center)==np.sign(z.actual)
                rows.extend(z.to_dict('records'))
            audits.append(dict(asset=asset,year=year,train_n=len(tr),train_label_end=str(tr.end_date.max()),test_start=str(te.date.min()),test_n=len(te)))
            print(asset,year,flush=True)
    r=pd.DataFrame(rows);r.to_parquet(OUT/'predictions.parquet',index=False)
    pd.DataFrame(audits).to_csv(OUT/'time_audit.csv',index=False)
    pd.DataFrame(neighbors).to_csv(OUT/'search_evidence.csv',index=False)
    pd.DataFrame(isolation).to_csv(OUT/'shock_isolation.csv',index=False)
    summaries=[]
    for asset,x in [('ALL',r),*list(r.groupby('asset'))]:
        for name,z in x.groupby('method'):
            for regime,mask in [('all',np.ones(len(z),bool)),('crash',z.crash),('rally',z.rally),('high_vol',z.high_vol)]:
                q=z[mask]
                summaries.append(dict(asset=asset,method=name,regime=regime,n=len(q),mae=q.mae.mean(),rmse=np.sqrt((q.error**2).mean()),bias=q.error.mean(),center_mean=q.center.mean(),actual_mean=q.actual.mean(),coverage=q.coverage.mean(),width=q.width.mean(),lower_breach=q.lower_breach.mean(),fixed5_coverage=q.cover5.mean(),direction_accuracy=q.direction_correct.mean(),crash_recall=q.crash_called.mean() if regime=='crash' else None,rally_recall=q.rally_called.mean() if regime=='rally' else None))
    pd.DataFrame(summaries).to_csv(OUT/'metrics.csv',index=False)
    calls=[]
    for name,z in r.groupby('method'):
        for kind in ['crash','rally']:
            called=z[kind+'_called'];true=z[kind]
            calls.append(dict(method=name,event=kind,actual_n=int(true.sum()),called_n=int(called.sum()),true_positive=int((called&true).sum()),recall=float((called&true).sum()/true.sum()),precision=float((called&true).sum()/called.sum()) if called.sum() else None,false_positive=int((called&~true).sum())))
    pd.DataFrame(calls).to_csv(OUT/'event_detection.csv',index=False)
    assert len(r)==918*5 and r.groupby(['asset','date']).width.agg(lambda a: a.max()-a.min()).max()<1e-8
    assert not r.duplicated(['asset','date','method']).any()
    (OUT/'verification.json').write_text(json.dumps(dict(same_918_rows=True,no_interval_widening=True,train_labels_precede_evaluation=True,A_excludes_shocks=True,approved=False),indent=2))

if __name__=='__main__':main()
