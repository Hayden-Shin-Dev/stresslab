"""Paired uncertainty and exact log-space contribution audit for failure cases."""
import json
import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits
from .training_interval_audit import OUT, F
from .gold_quarterly_trial import prep
from .core import SHOCKS
from .preopen_method_trial import metrics

def main():
    allp=pd.read_parquet(OUT/'predictions.parquet')
    fixed=allp[allp.model.eq('original_forward_residual')].copy()
    shift=np.log1p(fixed.location/100)-np.log1p(fixed.center/100)
    for col in ['center','lo','hi']:fixed[col]=100*np.expm1(np.log1p(fixed[col]/100)+shift)
    fixed['model']='original_forward_residual_fixed_center'
    allp=pd.concat([allp[~allp.model.eq(fixed.model.iloc[0])],fixed],ignore_index=True)
    allp.to_parquet(OUT/'predictions.parquet',index=False)
    pd.DataFrame([dict(period=period,model=m,level=l,**metrics(v)) for period,z in [('all',allp),('2025_2026',allp[allp.date.dt.year>=2025])] for (m,l),v in z.groupby(['model','level'])]).to_csv(OUT/'metrics.csv',index=False)
    pd.DataFrame([dict(asset=a,model=m,level=l,**metrics(v)) for (a,m,l),v in allp.groupby(['asset','model','level'])]).to_csv(OUT/'per_asset.csv',index=False)
    p=allp[allp.level.eq(.9)]
    pairs=[('original_location_only','original_return_distribution'),('safe_scale_return_distribution','original_return_distribution'),('original_forward_residual_fixed_center','original_location_only'),('original_forward_residual','original_return_distribution'),('scale_aware_location_only','original_location_only'),('legacy_cat_median_centered','legacy_cat_original')]
    rng=np.random.default_rng(20261105);rows=[]
    for new,ref in pairs:
        z=p[p.model.eq(new)].merge(p[p.model.eq(ref)],on=['date','asset'],suffixes=('_new','_ref'),validate='one_to_one')
        np.testing.assert_allclose(z.actual_new,z.actual_ref)
        for metric,diff in [('mae',abs(z.actual_new-z.center_ref)-abs(z.actual_new-z.center_new)),('width',(z.hi_ref-z.lo_ref)-(z.hi_new-z.lo_new))]:
            d=diff.groupby(z.date).mean().sort_index().to_numpy();n=len(d)
            ix=(rng.integers(0,n,(2000,int(np.ceil(n/4)),1))+np.arange(4)[None,None,:])%n
            draws=d[ix.reshape(2000,-1)[:,:n]].mean(1)
            rows.append(dict(candidate=new,reference=ref,metric=metric,improvement=float(d.mean()),ci_low=float(np.quantile(draws,.025)),ci_high=float(np.quantile(draws,.975)),dates=n))
    pd.DataFrame(rows).to_csv(OUT/'paired_ci.csv',index=False)
    x=prep(pd.read_parquet('reports/service_scope_20261105/corrected_daily_input.parquet'))
    x=x.merge(pd.read_parquet('reports/service_scope_20261105/corrected_features.parquet')[['date','asset','label_known_by']],on=['date','asset'])
    x=x.dropna(subset=F+['target','ewma','end_date','label_known_by']);x['known']=pd.to_datetime(x.label_known_by,utc=True)
    # Two worst crash misses per stock, explicitly failure analysis, never selection.
    d=p[p.model.eq('original_location_only')&p.actual.le(-5)].copy()
    d['miss']=d.center-d.actual
    d=d.sort_values('miss',ascending=False).groupby('asset').head(2)
    cases=[]
    for r in d.itertuples():
        cutoff=r.date.to_period('Q').start_time
        tr=x[(x.asset==r.asset)&(x.end_date<cutoff)&(x.known<cutoff.tz_localize('UTC'))].sort_values('date').tail(2520)
        t=x[(x.asset==r.asset)&(x.date==r.date)]
        s=StandardScaler().fit(tr[F]);y=100*np.log1p(tr.target/100)/tr.ewma
        m=Ridge(alpha=100).fit(s.transform(tr[F]),y)
        z=t[F].copy();z[SHOCKS]=0
        location=float(m.predict(s.transform(t[F]))[0]);zero=float(m.predict(s.transform(z))[0]);scale=float(t.ewma.iloc[0])
        contributions={v:float(m.coef_[F.index(v)]/s.scale_[F.index(v)]*t[v].iloc[0]*scale) for v in SHOCKS}
        assert abs(sum(contributions.values())-(location-zero)*scale)<1e-8
        pred=100*np.expm1(location*scale/100)
        assert abs(pred-r.center)<1e-7
        trainpred=100*np.expm1(m.predict(s.transform(tr[F]))*tr.ewma/100)
        cases.append(dict(asset=r.asset,date=str(r.date.date()),actual=r.actual,center=pred,zero_shock_model_return=100*np.expm1(zero*scale/100),shock_model_change=pred-100*np.expm1(zero*scale/100),train_mae=float(abs(trainpred-tr.target).mean()),market_trend20=float(t.market_trend20.iloc[0]),market_vol20=float(t.market_vol20.iloc[0]),**{'input_'+v:float(t[v].iloc[0]) for v in SHOCKS},**{v+'_log_return_pp':v2 for v,v2 in contributions.items()}))
    pd.DataFrame(cases).to_csv(OUT/'crash_attribution.csv',index=False)
    # Same evaluation sample zero-return benchmark, by asset.
    b=p[p.model.eq('original_location_only')]
    pd.DataFrame([dict(asset=a,n=len(v),zero_mae=float(abs(v.actual).mean()),model_mae=float(abs(v.actual-v.center).mean())) for a,v in b.groupby('asset')]).to_csv(OUT/'zero_baseline.csv',index=False)
    (OUT/'report_checks.json').write_text(json.dumps(dict(paired_actuals_equal=True,contribution_identity_checked=True,contribution_unit='log-return percentage points; arithmetic contributions are not asserted additive',bootstrap='2000 circular date-block resamples, length4; reused development sample',worst_cases='Two largest center-over-actual crash errors per stock; no tuning from cases'),indent=2))
    print(pd.DataFrame(rows).to_string(index=False))
    print(pd.DataFrame(cases).sort_values('actual').head(8).to_string(index=False))

if __name__=='__main__':
    with threadpool_limits(limits=2):main()
