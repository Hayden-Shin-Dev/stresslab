"""One prespecified target-unit ablation; no hyperparameter search."""
import json
import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits
from .gold_quarterly_trial import prep,F
from .training_interval_audit import OUT
from .preopen_method_trial import metrics

def main():
    x=prep(pd.read_parquet('reports/service_scope_20261105/corrected_daily_input.parquet'))
    x=x.merge(pd.read_parquet('reports/service_scope_20261105/corrected_features.parquet')[['date','asset','label_known_by']],on=['date','asset']).dropna(subset=F+['target','end_date','ewma','label_known_by'])
    x['known']=pd.to_datetime(x.label_known_by,utc=True)
    p=pd.read_parquet(OUT/'predictions.parquet');base=p[p.model.eq('original_location_only')].copy()
    base['quarter']=base.date.dt.to_period('Q');out=[];checks=[]
    for (q,a),v in base.groupby(['quarter','asset']):
        cutoff=q.start_time
        z=x[(x.asset==a)&(x.end_date<cutoff)&(x.known<cutoff.tz_localize('UTC'))].sort_values('date').tail(2520)
        t=v[['date','asset']].drop_duplicates().merge(x,on=['date','asset'],validate='one_to_one')
        s=StandardScaler().fit(z[F]);m=Ridge(alpha=100).fit(s.transform(z[F]),z.target)
        c=m.predict(s.transform(t[F]));new=t[['date','asset']].copy();new['raw_center']=c
        vv=v.merge(new,on=['date','asset'],validate='many_to_one')
        shift=vv.raw_center-vv.center
        # Preserve exact old widths to isolate center, not a newly approved interval.
        vv['lo']+=shift;vv['hi']+=shift;vv['center']=vv.raw_center;vv['model']='raw_target_ridge_fixed_width'
        out.append(vv)
        checks.append(dict(asset=a,quarter=str(q),train_n=len(z),train_mae=float(abs(m.predict(s.transform(z[F]))-z.target).mean()),test_n=len(t)))
    allp=pd.concat([p,pd.concat(out)],ignore_index=True);allp.to_parquet(OUT/'center_scale_predictions.parquet',index=False)
    pd.DataFrame(checks).to_csv(OUT/'raw_target_splits.csv',index=False)
    names=['original_location_only','raw_target_ridge_fixed_width']
    v=allp[allp.model.isin(names)]
    pd.DataFrame([dict(period=period,model=m,level=l,**metrics(d)) for period,z in [('all',v),('2025_2026',v[v.date.dt.year>=2025])] for (m,l),d in z.groupby(['model','level'])]).to_csv(OUT/'center_scale_metrics.csv',index=False)
    pd.DataFrame([dict(asset=a,model=m,level=l,**metrics(d)) for (a,m,l),d in v.groupby(['asset','model','level'])]).to_csv(OUT/'center_scale_per_asset.csv',index=False)
    joined=v[(v.model==names[0])&(v.level==.9)].merge(v[(v.model==names[1])&(v.level==.9)],on=['date','asset'],suffixes=('_old','_new'),validate='one_to_one')
    np.testing.assert_allclose(joined.hi_new-joined.lo_new,joined.hi_old-joined.lo_old)
    diff=(abs(joined.actual_old-joined.center_old)-abs(joined.actual_old-joined.center_new)).groupby(joined.date).mean().sort_index().to_numpy()
    rng=np.random.default_rng(20261105);n=len(diff);ix=(rng.integers(0,n,(2000,int(np.ceil(n/4)),1))+np.arange(4)[None,None,:])%n
    draws=diff[ix.reshape(2000,-1)[:,:n]].mean(1)
    summary=dict(mae_improvement_date_equal=float(diff.mean()),ci95=np.quantile(draws,[.025,.975]).tolist(),note='Target-unit ablation changes loss weighting and response form. Not proof normalization is a software bug. Fixed-width translated intervals isolate centers and are not calibrated production intervals.')
    (OUT/'center_scale_audit.json').write_text(json.dumps(summary,indent=2))
    print(pd.read_csv(OUT/'center_scale_metrics.csv').to_string(index=False));print(summary)

if __name__=='__main__':
    with threadpool_limits(limits=2):main()
