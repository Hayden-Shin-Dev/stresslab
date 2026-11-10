"""Actual-history scenario intervention: A must stay fixed when shocks change."""
import argparse,json
from pathlib import Path
import pandas as pd
from threadpoolctl import threadpool_limits
from .core import features,SHOCKS,Factor
from .matched_comparison import MatchedResponse

def run(gold,out):
    d=features(pd.read_parquet(gold)).dropna(subset=SHOCKS+['target','end_date'])
    tr=d[d.end_date<'2022-12-12'];q=d[(d.date=='2026-10-19')&d.asset.isin(['003490','010950'])].copy()
    if len(q)!=2:raise ValueError('This fixed evidence check requires both airline and refinery on 2026-10-19')
    m=MatchedResponse().fit(tr,Factor().fit(tr));records=[];diagnostics=[]
    for name,shock in [('zero',{}),('oil10',{'wti_pct':10}),('oil_minus10',{'wti_pct':-10}),('fx5_rate100',{'fx_pct':5,'us_rate_bp':100})]:
        x=q.copy();x[SHOCKS]=0
        for k,v in shock.items():x[k]=v
        predictions,ds,_=m.predict(x,'scenario',2026)
        for row in ds:row['scenario']=name
        diagnostics+=ds
        for method,ys in predictions.items():
            for asset,y in zip(x.asset,ys):records.append(dict(scenario=name,method=method,asset=asset,center_pp=float(y),pnl_per_million_krw=float(y*10000)))
    diag=pd.DataFrame(diagnostics);assert diag.groupby(['asset','shock']).candidate_id_hash.nunique().max()==1
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    pd.DataFrame(records).to_csv(out/'scenarios.csv',index=False);diag.to_csv(out/'support.csv',index=False)
    (out/'verification.json').write_text(json.dumps(dict(actual_state_date='2026-10-19',user_shock_changes_leave_A_unchanged=True,scenario_not_actual_outcome=True,training_label_end=str(tr.end_date.max())),indent=2),encoding='utf8')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--gold',required=True);p.add_argument('--out',required=True);a=p.parse_args()
    with threadpool_limits(limits=2):run(a.gold,a.out)
