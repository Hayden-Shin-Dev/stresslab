"""Exploratory application of past-only variable evidence, not forced additive effects."""
import json
from concurrent.futures import ThreadPoolExecutor,as_completed
import numpy as np
import pandas as pd
from lightgbm import LGBMRegressor
from threadpoolctl import threadpool_limits
from crash_mechanism_20261104 import ROOT,OUT,PREVIOUS,FEATURES,SHOCKS,inputs

def main():
    pairs,data,_=inputs();v=pd.read_csv(OUT/'variable_stability.csv',dtype={'asset':str});inter=json.loads((OUT/'interactions.json').read_text())
    ref=pd.read_parquet(PREVIOUS/'predictions.parquet');ref=ref[ref.method.eq('all4_median')];packs=[];chosen=[];aud=[]
    (OUT/'application_protocol.json').write_text(json.dumps(dict(
      exploratory_followup=True,rules_use_only_pre2022_tables=True,cohort_unchanged=True,
      methods=['scaled_huber_interactions','stable_analysis_huber'],
      stable_rule='Both pre2022 crash-deletion effects positive, average overall MAE deletion positive, training missing <=50%; top20 by crash value, plus four shocks and five mandatory market states.',
      interactions='Previously frozen pairs only. In stable model both inputs must survive; financial_missing and report_age products excluded because availability is not an economic interaction.',
      repeated_evaluation_not_blind=True,production_approved=False),indent=2))
    def run(asset):
        f=data[data.asset.eq(asset)].sort_values('date');r=[];features_record=[];time=[]
        evidence=v[v.asset.eq(asset)];stable=evidence[(evidence.positive_crash_folds==2)&(evidence.mae_value>0)&(evidence.missing<=.5)].sort_values('crash_value',ascending=False).head(20).feature.tolist()
        stable=list(dict.fromkeys(SHOCKS+['market_trend20','market_vol20','asset_trend20','asset_vol20','vix_level']+stable))
        signs=dict(zip(pairs[pairs.asset.eq(asset)].feature,pairs[pairs.asset.eq(asset)].sign))
        for method in ['scaled_huber_interactions','stable_analysis_huber']:
            cols=FEATURES.copy() if method=='scaled_huber_interactions' else stable
            crosses=[(a,b) for a,b in inter[asset] if a in cols and b in cols and a not in ['report_age','financial_missing'] and b not in ['report_age','financial_missing']]
            names=cols+[a+'__'+b for a,b in crosses]
            features_record += [dict(asset=asset,method=method,feature=c,selection_period='before2022') for c in names]
            for year in range(2023,2027):
                cut=pd.Timestamp(year-1,1,1);tr=f[f.end_date<cut-pd.Timedelta(days=20)];old=ref[ref.asset.eq(asset)&ref.date.dt.year.eq(year)].sort_values('date');te=f.set_index('date').loc[old.date].reset_index()
                if old.empty:continue
                x=tr[cols].copy();test=te[cols].copy()
                for a,b in crosses:
                    # Units standardized from training only; bounded by training marginals.
                    values=[]
                    for c in [a,b]:
                        med=tr[c].median();med=0. if pd.isna(med) else med;sd=max(float(tr[c].std()),1e-6);lo=tr[c].min();hi=tr[c].max()
                        values.append(((tr[c].fillna(med)-med)/sd,(te[c].fillna(med).clip(lo,hi)-med)/sd))
                    name=a+'__'+b;x[name]=values[0][0]*values[1][0];test[name]=values[0][1]*values[1][1]
                scale=max(1.,1.4826*np.median(abs(tr.target-tr.target.median())))
                # A shock appearing inside a product cannot be guaranteed monotone by constraining its raw column alone.
                # Disable that shock's constraint rather than falsely claim global monotonicity.
                cross_inputs={c for pair in crosses for c in pair};constraints=[int(signs.get(c,0)) if c not in cross_inputs else 0 for c in names]
                m=LGBMRegressor(objective='huber',alpha=.9,n_estimators=250,learning_rate=.04,max_depth=4,num_leaves=15,min_child_samples=40,random_state=20261104,n_jobs=1,verbosity=-1,
                  monotone_constraints=constraints,monotone_constraints_method='advanced').fit(x,tr.target/scale)
                out=old[['asset','date','actual']+SHOCKS].copy();out['method']=method;out['center']=m.predict(test)*scale;r.append(out)
                time.append(dict(asset=asset,year=year,method=method,train_end=str(tr.end_date.max()),test_start=str(te.date.min()),n=len(te),unconstrained_cross_inputs=','.join(sorted(cross_inputs))))
        return pd.concat(r),features_record,time
    with threadpool_limits(limits=1,user_api='blas'),ThreadPoolExecutor(max_workers=4) as pool:
        futures={pool.submit(run,a):a for a in sorted(pairs.asset.unique())}
        for i,f in enumerate(as_completed(futures),1):
            p,c,t=f.result();packs.append(p);chosen+=c;aud+=t;print('apply',i,len(futures),flush=True)
    pd.concat(packs).to_parquet(OUT/'application_predictions.parquet',index=False,compression='zstd')
    pd.DataFrame(chosen).to_csv(OUT/'applied_features.csv',index=False);pd.DataFrame(aud).to_csv(OUT/'application_time_audit.csv',index=False)
    (OUT/'application_complete.json').write_text(json.dumps(dict(complete=True,assets=len(futures))))
if __name__=='__main__':main()
