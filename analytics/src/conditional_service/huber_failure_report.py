"""Summarize identical held-out rows without selecting or refitting a model."""
import json
from pathlib import Path
import joblib
import numpy as np
import pandas as pd

def main():
    out=Path('reports/huber_followup_20261105')
    p=pd.read_parquet(out/'predictions.parquet')
    d=pd.read_parquet('reports/huber_direction_20261105/predictions.parquet')
    p=p.merge(d[['date','asset','direction1','direction4']],on=['date','asset'],validate='one_to_one')
    names=joblib.load('reports/service_scope_20261105/final_service_bundle.joblib')['names']
    rows=[];stock=[]
    methods=['huber','delta075','stock_states','vol_normalized','direction1','direction4']
    for period,z in [('all',p),('recent',p[p.year>=2025])]:
        for state,v in [('all',z),('high_vol',z[z.high_vol]),('normal_vol',z[~z.high_vol])]:
            c=v[v.actual<=-5]
            for m in methods:
                rows.append(dict(period=period,state=state,model=m,n=len(v),crash_n=len(c),
                    crash_negative_fraction=float((c[m]<0).mean()),crash_below_minus5_fraction=float((c[m]<=-5).mean()),
                    crash_underestimate_pp=float(np.maximum(c[m]-c.actual,0).mean()),mae_pp=float(abs(v[m]-v.actual).mean())))
        for a,v in z.groupby('asset'):
            c=v[v.actual<=-5]
            for m in methods:
                stock.append(dict(period=period,asset=a,name=names[a],model=m,n=len(v),crash_n=len(c),
                    mae_pp=float(abs(v[m]-v.actual).mean()),direction=float((np.sign(v[m])==np.sign(v.actual)).mean()),
                    crash_actual_pp=float(c.actual.mean()),crash_prediction_pp=float(c[m].mean()),
                    crash_underestimate_pp=float(np.maximum(c[m]-c.actual,0).mean())))
    pd.DataFrame(rows).to_csv(out/'failure_regimes.csv',index=False)
    pd.DataFrame(stock).to_csv(out/'failure_stocks.csv',index=False)
    p[p.actual<=-5].to_csv(out/'failure_cases.csv',index=False)
    print(pd.DataFrame(rows).query("period=='recent' and state=='all'").to_string(index=False))
    print(pd.DataFrame(stock).query("period=='recent' and model in ['huber','delta075'] and asset in ['009150','005380','010950']").to_string(index=False))
    for folder in [out,Path('reports/huber_direction_20261105')]:
        fits=json.loads((folder/'fit_checks.json').read_text())
        assert all(x['converged'] for x in fits)
    print('All fits converged; no model selected from these summaries.')

if __name__=='__main__':main()
