"""Conservative US macro timing sensitivity, not a certified publication calendar."""
import json
import numpy as np
import pandas as pd
from asset_feature_research import make_data,EXPANDED,model
from fresh_center_audit import SRC,OUT

def main():
    g=pd.read_parquet(SRC/'research_daily_input.parquet').sort_values(['asset_id','trading_date'])
    lagged=g.copy()
    for col in ['us_treasury_10y','wti','vix']:lagged[col]=g.groupby('asset_id')[col].shift(1)
    d,_=make_data(lagged)
    oil=lagged.groupby('trading_date').wti.first().sort_index();bad=set(pd.to_datetime(oil.index[oil.le(0).rolling(6).max().shift(-5).eq(1)]))
    b=pd.read_parquet(OUT/'predictions.parquet');b=b[b.method.eq('clean_quarter')];rows=[]
    for asset,x in b.groupby('asset'):
        f=d[d.asset.eq(asset)]
        for period,zz in x.groupby(x.date.dt.to_period('Q')):
            cut=period.start_time;tr=f[(f.end_date<cut-pd.Timedelta(days=20))&~f.date.isin(bad)];te=f.set_index('date').loc[zz.date].reset_index()
            m=model('lgb').fit(tr[EXPANDED],tr.target/tr.scale);p=m.predict(te[EXPANDED])*te.scale.to_numpy()
            assert np.max(abs(te.target.to_numpy()-zz.actual.to_numpy()))<1e-8
            z=zz.copy();z['method']='us_macro_prior_session';z['center']=p;z['mae']=(z.actual-z.center).abs();z['direction_correct']=np.sign(z.actual)==np.sign(z.center);z['fixed5_coverage']=z.mae<=2.5;rows.extend(z.to_dict('records'))
    r=pd.DataFrame(rows);r.to_parquet(OUT/'timing_predictions.parquet',index=False)
    results=[]
    for name,z in [('same_date',b),('us_macro_prior_session',r)]:
        for scope,q in [('all',z),('fixed_original_shock_subset',z[z.event])]:
            nz=q[q.actual.ne(0)];results.append(dict(method=name,scope=scope,n=len(q),direction_accuracy=nz.direction_correct.mean(),mae=q.mae.mean()))
    pd.DataFrame(results).to_csv(OUT/'timing_metrics.csv',index=False)
    (OUT/'timing_limit.json').write_text(json.dumps(dict(definition='US10Y,WTI,VIX shifted by one KRX trading row before computing state and5day shock endpoints; Korean FX and KR3Y unchanged',matched_targets=True,matched_dates=True,actual_shock_inputs_changed=True,subset='Original fixed231 shock observations retained for comparison; not reselected using shifted shocks',availability='Sensitivity only: provider publication timestamps and vintage history absent, not certified as-of reconstruction',rows=len(r),approved=False),indent=2))
if __name__=='__main__':main()
