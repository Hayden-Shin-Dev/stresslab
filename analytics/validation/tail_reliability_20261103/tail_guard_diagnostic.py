"""Explicit conservative tail policy, not an asserted calibrated probability interval."""
import json
import numpy as np
import pandas as pd
from tail_reliability_research import SRC,OUT

def main():
    policy={'policy':'retain conditional centre and upper boundary; lower residual offset cannot shrink relative to state-only residual offset',
        'interpretation':'conservative model-risk reference interval, not a proven nominal80% probability interval',
        'reason':'2x2 attribution identifies shrinking lower residual offset as the main cause of incremental crash misses',
        'comparison':'same per-query total width, extra width split equally between lower/upper; changes derived from already available model outputs, never test outcomes',
        'research_status':'post-diagnosis development check on reused dates, no independent holdout; no production promotion'}
    (OUT/'guard_policy.json').write_text(json.dumps(policy,indent=2),encoding='utf8')
    selected=json.loads((SRC/'selected_assets.json').read_text());r=pd.read_parquet(SRC/'predictions.parquet');r=r[r.asset.isin(selected)&(r.model=='lgb')]
    z=r[r.spec=='all4'].merge(r[r.spec=='state_only'][['asset','date','center','q10']],on=['asset','date'],suffixes=('','_state'),validate='one_to_one')
    extra=np.maximum(0,(z.q10-z.center)-(z.q10_state-z.center_state))
    variants=[]
    for name,lo,hi in [('residual_tail_guard',z.q10-extra,z.q90),('same_width_symmetric_control',z.q10-extra/2,z.q90+extra/2)]:
        x=z.copy();x['method']=name;x['q10']=lo;x['q90']=hi;x['width']=hi-lo;x['coverage']=((x.actual>=lo)&(x.actual<=hi)).astype(float);x['lower_breach']=(x.actual<lo).astype(float)
        x['missed_loss_pp']=np.maximum(lo-x.actual,0);x['interval_score']=hi-lo+10*(np.maximum(lo-x.actual,0)+np.maximum(x.actual-hi,0));x['extra_width']=extra
        x['nominal_probability_approved']=False;variants.append(x.drop(columns=['center_state','q10_state']))
    out=pd.concat(variants,ignore_index=True);out.to_parquet(OUT/'guard_predictions.parquet',index=False)
    print(out.groupby('method')[['coverage','width','lower_breach','interval_score']].mean().to_string())
    print(out[out.asset_crash].groupby('method')[['coverage','width','lower_breach','missed_loss_pp']].mean().to_string())

if __name__=='__main__':main()
