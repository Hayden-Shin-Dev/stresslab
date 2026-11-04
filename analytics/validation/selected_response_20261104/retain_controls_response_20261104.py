"""Exploratory follow-up after pair-only ablation: retain controls and robust center loss."""
import json
from concurrent.futures import ThreadPoolExecutor,as_completed
import numpy as np
import pandas as pd
from lightgbm import LGBMRegressor
from threadpoolctl import threadpool_limits
from train_selected_response_20261104 import ROOT,OUT,STATE,SHOCKS,score

METHODS=['all4_mean','all4_huber','all4_huber_selected_signs']

def main():
    pairs=pd.read_csv(OUT/'frozen_pairs.csv',dtype={'asset':str});data=pd.read_parquet(ROOT/'reports/rich_context_20261103/learning_table.parquet')
    ref=pd.read_parquet(OUT/'predictions.parquet');ref=ref[ref.method.eq('all4_median')]
    (OUT/'followup_protocol.json').write_text(json.dumps(dict(
      motivation='Pair-only omission lost useful controls; squared-error mean target worsened MAE. Keep four shocks, apply robust loss, then constrain only previously frozen signs.',
      selection_changed=False,models=METHODS,objective='LightGBM huber alpha=0.9 default, no tuning',
      exploratory_after_first_evaluation=True,independent_confirmation=False,production_approved=False),indent=2))
    def run(asset):
        f=data[data.asset.eq(asset)].sort_values('date');ps=pairs[pairs.asset.eq(asset)];signs=dict(zip(ps.feature,ps.sign));cols=STATE+SHOCKS
        records=[];responses=[]
        for year in range(2023,2027):
            start=pd.Timestamp(year-1,1,1);cut=pd.Timestamp(year,1,1)
            tr=f[f.end_date<start-pd.Timedelta(days=20)];ca=f[(f.date>=start)&(f.end_date<cut-pd.Timedelta(days=20))].iloc[::6]
            old=ref[ref.asset.eq(asset)&ref.date.dt.year.eq(year)].sort_values('date');te=f.set_index('date').loc[old.date].reset_index()
            if old.empty:continue
            for method in METHODS:
                args=dict(objective='regression' if method=='all4_mean' else 'huber',n_estimators=250,learning_rate=.04,max_depth=4,num_leaves=15,min_child_samples=40,random_state=20261104,n_jobs=1,verbosity=-1)
                if method.endswith('selected_signs'):args.update(monotone_constraints=[int(signs.get(c,0)) for c in cols],monotone_constraints_method='advanced')
                m=LGBMRegressor(**args).fit(tr[cols],tr.target);q=np.quantile(ca.target-m.predict(ca[cols]),[.1,.9]);pred=m.predict(te[cols])
                r=old[['asset','date','actual']+SHOCKS].copy();r['method']=method;r['center']=pred;r['lower']=pred+q[0];r['upper']=pred+q[1];records.append(r)
                for shock in list(signs)+(['shock_oil'] if asset=='003490' and 'shock_oil' not in signs else []):
                    low,high=tr[shock].quantile([.25,.75]);a=te[cols].copy();b=a.copy();a[shock]=low;b[shock]=high
                    for dt,x,y in zip(te.date,m.predict(a),m.predict(b)):
                        responses.append(dict(asset=asset,date=dt,method=method,shock=shock,shock_low=low,shock_high=high,low_prediction=x,high_prediction=y,response_pp=y-x,selected=shock in signs))
        return pd.concat(records),responses
    packs=[];responses=[];failed=[]
    with threadpool_limits(limits=1,user_api='blas'),ThreadPoolExecutor(max_workers=4) as pool:
        jobs={pool.submit(run,a):a for a in sorted(pairs.asset.unique())}
        for i,fu in enumerate(as_completed(jobs),1):
            try:p,r=fu.result();packs.append(p);responses+=r
            except Exception as e:failed.append(dict(asset=jobs[fu],error=repr(e)))
            (OUT/'followup_progress.json').write_text(json.dumps(dict(completed=i,total=len(jobs),failed=failed)));print(i,len(jobs),flush=True)
    assert not failed,failed
    p=pd.concat(packs);p.to_parquet(OUT/'controls_predictions.parquet',index=False,compression='zstd')
    pd.DataFrame(responses).to_parquet(OUT/'controls_interventions.parquet',index=False,compression='zstd')
    pd.DataFrame([dict(method=m,**score(z)) for m,z in p.groupby('method')]).to_csv(OUT/'controls_aggregate.csv',index=False)
    pd.DataFrame([dict(asset=a,method=m,**score(z)) for (a,m),z in p.groupby(['asset','method'])]).to_csv(OUT/'controls_asset_metrics.csv',index=False)
    (OUT/'followup_progress.json').write_text(json.dumps(dict(status='complete',completed=len(jobs),failed=[])))
if __name__=='__main__':main()
