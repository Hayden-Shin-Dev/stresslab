"""Prespecified Korean Air oil control: isolate adding oil from imposing its sign."""
import pandas as pd
import numpy as np
from train_selected_response_20261104 import ROOT, OUT, STATE, SHOCKS, estimator, score

def main():
    pairs=pd.read_csv(OUT/'frozen_pairs.csv',dtype={'asset':str});ps=pairs[pairs.asset.eq('003490')]
    signs=dict(zip(ps.feature,ps.sign));cols=list(dict.fromkeys(STATE+list(signs)+['shock_oil']))
    data=pd.read_parquet(ROOT/'reports/rich_context_20261103/learning_table.parquet');f=data[data.asset.eq('003490')].sort_values('date')
    ref=pd.read_parquet(ROOT/'reports/variable_analysis_20261104/predictions.parquet');ref=ref[ref.method.eq('baseline')&ref.asset.eq('003490')]
    records=[];responses=[]
    for year in range(2023,2027):
        cut=pd.Timestamp(year,1,1);start=pd.Timestamp(year-1,1,1)
        tr=f[f.end_date<start-pd.Timedelta(days=20)];ca=f[(f.date>=start)&(f.end_date<cut-pd.Timedelta(days=20))].iloc[::6]
        old=ref[ref.date.dt.year.eq(year)].sort_values('date');te=f.set_index('date').loc[old.date].reset_index()
        for name in ['air_oil_unconstrained','air_other_signs_only']:
            method='selected_mean' if name=='air_oil_unconstrained' else 'selected_monotone_mean'
            m=estimator(method,cols,signs).fit(tr[cols],tr.target)
            q=np.quantile(ca.target-m.predict(ca[cols]),[.1,.9]);pred=m.predict(te[cols])
            r=old[['asset','date','actual']].copy();r['method']=name;r['center']=pred;r['lower']=pred+q[0];r['upper']=pred+q[1]
            for s in SHOCKS:r[s]=te[s].to_numpy()
            records.append(r);low,high=tr.shock_oil.quantile([.25,.75]);a=te[cols].copy();b=a.copy();a.shock_oil=low;b.shock_oil=high
            for dt,x,y in zip(te.date,m.predict(a),m.predict(b)):
                responses.append(dict(asset='003490',date=dt,method=name,shock='shock_oil',shock_low=low,shock_high=high,low_prediction=x,high_prediction=y,response_pp=y-x,selected=False))
    p=pd.concat(records);p.to_parquet(OUT/'air_oil_control.parquet',index=False,compression='zstd')
    pd.DataFrame(responses).to_parquet(OUT/'air_oil_control_responses.parquet',index=False,compression='zstd')
    pd.DataFrame([dict(asset=a,method=m,**score(z)) for (a,m),z in p.groupby(['asset','method'])]).to_csv(OUT/'air_oil_control_metrics.csv',index=False)
if __name__=='__main__':main()
