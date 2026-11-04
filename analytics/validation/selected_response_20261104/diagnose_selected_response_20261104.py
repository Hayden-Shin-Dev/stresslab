"""Distinguish mean group contrast from individual return direction and stationarity."""
import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits
from balance_effect_atlas_20261104 import ROOT, weights, controls_for
OUT=ROOT/'reports/selected_response_20261104'

def wq(y,w,q):
    order=np.argsort(y);return float(np.interp(q,np.cumsum(w[order]),y[order]))

def main():
    data=pd.read_parquet(ROOT/'reports/rich_context_20261103/learning_table.parquet');rows=[]
    with threadpool_limits(limits=1):
        for asset in ['003490','010950']:
            for start,end in [('2000-01-01','2010-01-01'),('2010-01-01','2016-01-01'),('2016-01-01','2022-01-01'),('2000-01-01','2022-01-01'),('2023-01-01','2027-01-01')]:
                z=data[(data.asset==asset)&(data.date>=start)&(data.end_date<pd.Timestamp(end)-pd.Timedelta(days=20))].sort_values('date').iloc[::6]
                s='shock_oil';low,high=z[s].quantile([.25,.75]);ia=np.where(z[s]>=high)[0];ib=np.where(z[s]<=low)[0]
                controls=[c for c in controls_for(s) if z[c].notna().mean()>=.5 and z[c].std()>1e-8]
                raw=z[controls];x=raw.fillna(raw.median()).to_numpy();x=(x-x.mean(0))/np.maximum(x.std(0),1e-8)
                missing=raw.isna().to_numpy().astype(float);vary=missing.std(0)>.01
                if vary.any():x=np.column_stack([x,missing[:,vary]])
                target=np.vstack([x[ia],x[ib]]).mean(0);wa,oka=weights(x[ia],target);wb,okb=weights(x[ib],target)
                ya=z.target.to_numpy()[ia];yb=z.target.to_numpy()[ib]
                smd=float(np.max(abs(wa@x[ia]-wb@x[ib])));ea=1/(wa@wa);eb=1/(wb@wb)
                row=dict(asset=asset,start=start,end=end,n=len(z),high_n=len(ia),low_n=len(ib),max_control_smd=smd,high_ess=ea,low_ess=eb,
                    supported=bool(oka and okb and smd<=.1 and min(ea,eb)>=30 and max(wa.max(),wb.max())<=.1),
                    high_shock=float(wa@z[s].to_numpy()[ia]),low_shock=float(wb@z[s].to_numpy()[ib]),
                    high_mean=float(wa@ya),low_mean=float(wb@yb),contrast_pp=float(wa@ya-wb@yb),
                    high_median=wq(ya,wa,.5),low_median=wq(yb,wb,.5),high_up_fraction=float(wa@(ya>0)),low_up_fraction=float(wb@(yb>0)),
                    high_width80=wq(ya,wa,.9)-wq(ya,wa,.1),low_width80=wq(yb,wb,.9)-wq(yb,wb,.1),
                    high_crash_fraction=float(wa@(ya<=-5)),low_crash_fraction=float(wb@(yb<=-5)),
                    used_for_selection=False,causal=False)
                rows.append(row)
    pd.DataFrame(rows).to_csv(OUT/'oil_period_diagnosis.csv',index=False)
if __name__=='__main__':main()
