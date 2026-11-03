"""Predictive residual response learner. Not a causal identification procedure."""
import json,joblib,hashlib
from concurrent.futures import ThreadPoolExecutor,as_completed
import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from threadpoolctl import threadpool_limits
from analyze_variables_20261104 import OUT,ROOT,SRC,RAW,SHOCKS,nuisance

STATE=[c for c in RAW if c not in SHOCKS]
BASIS=['market_trend20','market_vol20','asset_trend20','foreign_flow_20','institution_flow_20','debt_assets']

def design(s,b,interaction):
    return np.column_stack([s]+[s*b[:,i,None] for i in range(b.shape[1])]) if interaction else s

def main():
    OUT.mkdir(exist_ok=True);(OUT/'response_checkpoints').mkdir(exist_ok=True)
    d=pd.read_parquet(ROOT/'reports/rich_context_20261103/learning_table.parquet');ref=pd.read_parquet(ROOT/'reports/rich_context_20261103/predictions.parquet');ref=ref[ref.method.eq('all')]
    assets=json.loads((SRC/'selected_assets.json').read_text());rows=[];audit=[];coefs=[];fail=[]
    protocol=dict(target='Raw5-session stock return; conditional mean, not median or market excess return',
        method='Past-only nonlinear E[Y|state] and E[shocks|state]. Chronological OOS residuals fit joint4shock response, constant or state-varying ridge. Inference=state mean+(user shocks-expected shocks given state)*response.',
        state=STATE,basis=BASIS,constant_alpha=10,interaction_alpha=30,nuisance=nuisance().get_params(),
        dates='2016-2026 annual chronological folds,20day label embargo. Residual-bank labels before current cutoff; non-overlapping5session calibration labels.',
        evaluation='Same2023-2026 keys as main study; reused research period; no causal effect claim; no production promotion')
    (OUT/'response_protocol.json').write_text(json.dumps(protocol,indent=2),encoding='utf8')
    def run(asset):
        f=d[d.asset.eq(asset)].sort_values('date');bank=[];result=[];times=[];coefficients=[]
        for year in range(2016,2027):
            cut=pd.Timestamp(year,1,1);tr=f[f.end_date<cut-pd.Timedelta(days=20)]
            validation=f[(f.date>=cut)&(f.end_date<pd.Timestamp(year+1,1,1)-pd.Timedelta(days=20))].iloc[::6]
            if len(tr)<500 or len(validation)<15:continue
            my=nuisance().fit(tr[STATE],tr.target);ms=[nuisance().fit(tr[STATE],tr[s]) for s in SHOCKS]
            old=ref[(ref.asset==asset)&(ref.date.dt.year==year)].sort_values('date') if year>=2023 else pd.DataFrame()
            if len(old):
                te=f.set_index('date').loc[old.date].reset_index();pool=pd.concat(bank,ignore_index=True);pool=pool[pool.end_date<cut-pd.Timedelta(days=20)]
                assert len(pool)>=30 and pool.end_date.max()<te.date.min() and tr.end_date.max()<te.date.min()
                ymean=my.predict(te[STATE]);expected=np.column_stack([m.predict(te[STATE]) for m in ms])
                sr=pool[[s+'_residual' for s in SHOCKS]].to_numpy();sc=np.maximum(sr.std(axis=0),1e-6)
                med=pool[BASIS].median().fillna(0);b=pool[BASIS].fillna(med).to_numpy();bm=b.mean(axis=0);bs=np.maximum(b.std(axis=0),1e-6)
                tb=(te[BASIS].fillna(med).to_numpy()-bm)/bs;b=(b-bm)/bs
                for name,inter,alpha in [('orthogonal_constant',False,10),('orthogonal_state_response',True,30)]:
                    fit=Ridge(alpha=alpha,fit_intercept=False).fit(design(sr/sc,b,inter),pool.return_residual)
                    pred=ymean+fit.predict(design((te[SHOCKS].to_numpy()-expected)/sc,tb,inter))
                    for i,(_,v) in enumerate(old.iterrows()):
                        record=v.to_dict();record.update(method=name,center=float(pred[i]));result.append(record)
                    for i,s in enumerate(SHOCKS):
                        coefficients.append(dict(asset=asset,year=year,method=name,shock=s,coefficient_at_mean_state=float(fit.coef_[i]/sc[i]),calibration_n=len(pool)))
                    if year==2026:
                        folder=OUT/'response_models'/asset;folder.mkdir(parents=True,exist_ok=True)
                        joblib.dump(dict(state_model=my,shock_models=ms,response_model=fit,state_features=STATE,basis_features=BASIS,
                            shock_scale=sc,basis_median=med,basis_mean=bm,basis_scale=bs,interaction=inter,train_label_end=str(tr.end_date.max()),approved=False),folder/(name+'.joblib'))
                times.append(dict(asset=asset,year=year,train_label_end=str(tr.end_date.max()),calibration_label_end=str(pool.end_date.max()),test_start=str(te.date.min()),test_n=len(te),calibration_n=len(pool)))
            # Only truly subsequent predictions are deposited into the residual bank.
            p=validation[['date','end_date']+BASIS].copy();p['return_residual']=validation.target.to_numpy()-my.predict(validation[STATE])
            for shock,m in zip(SHOCKS,ms):p[shock+'_residual']=validation[shock].to_numpy()-m.predict(validation[STATE])
            bank.append(p)
        out=pd.DataFrame(result);out.to_parquet(OUT/'response_checkpoints'/f'{asset}.parquet',index=False);return out,times,coefficients
    with threadpool_limits(limits=1,user_api='blas'),ThreadPoolExecutor(max_workers=2) as pool:
        futures={pool.submit(run,a):a for a in assets}
        for i,fu in enumerate(as_completed(futures),1):
            try:r,t,c=fu.result();rows.append(r);audit.extend(t);coefs.extend(c)
            except Exception as e:fail.append(dict(asset=futures[fu],error=repr(e)))
            (OUT/'response_progress.json').write_text(json.dumps(dict(status='running',completed=i,total=len(assets),failed=fail),indent=2));print(i,len(assets),flush=True)
    assert not fail,fail
    r=pd.concat(rows,ignore_index=True);assert r.groupby(['asset','date']).method.nunique().eq(2).all();r.to_parquet(OUT/'response_predictions.parquet',index=False)
    pd.DataFrame(audit).to_csv(OUT/'response_time_audit.csv',index=False);pd.DataFrame(coefs).to_csv(OUT/'response_coefficients.csv',index=False)
    (OUT/'response_progress.json').write_text(json.dumps(dict(status='complete',completed=len(assets),failed=[]),indent=2))

if __name__=='__main__':main()
