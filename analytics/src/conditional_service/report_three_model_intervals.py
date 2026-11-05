"""Paired point/interval assessment, retaining failures and date clustering."""
import json
import numpy as np
import pandas as pd
from .three_model_intervals import OUT,MODELS

def point(z):
    y=z.actual.to_numpy();v=z.center.to_numpy();nz=y!=0;cr=y<=-5
    return dict(n=len(z),dates=z.date.nunique(),stocks=z.asset.nunique(),mae_pp=float(abs(y-v).mean()),rmse_pp=float(np.sqrt(((y-v)**2).mean())),direction=float((np.sign(y[nz])==np.sign(v[nz])).mean()),zero_excluded=int((~nz).sum()),crash_n=int(cr.sum()),crash_mae_pp=float(abs(y[cr]-v[cr]).mean()),crash_underestimate_pp=float(np.maximum(v[cr]-y[cr],0).mean()),crash_direction=float((v[cr]<0).mean()),crash_magnitude_caught=float((v[cr]<=-5).mean()),false_crash_count=int(((v<=-5)&~cr).sum()))

def interval(z):
    alpha=1-float(z.level.iloc[0]);y=z.actual;lo=z.lo;hi=z.hi;cr=y<=-5
    score=hi-lo+2/alpha*((lo-y).clip(lower=0)+(y-hi).clip(lower=0))
    return dict(n=len(z),coverage=float(((y>=lo)&(y<=hi)).mean()),width_pp=float((hi-lo).mean()),interval_score=float(score.mean()),pinball_mean=float((alpha/4*score).mean()),lower_breach=float((y<lo).mean()),crash_lower_breach=float((y[cr]<lo[cr]).mean()),crash_shortfall_pp=float((lo[cr]-y[cr]).clip(lower=0).mean()))

def ci(values):
    a=values.to_numpy();rng=np.random.default_rng(20261105);n=len(a);length=4
    sims=[]
    for _ in range(2000):
        ix=np.concatenate([(np.arange(length)+s)%n for s in rng.integers(n,size=(n+length-1)//length)])[:n];sims.append(a[ix].mean())
    return dict(mean=float(a.mean()),ci95=np.quantile(sims,[.025,.975]).tolist(),dates=n,block_length=length)

def main():
    assert json.loads((OUT/'verification.json').read_text())['passed']
    p=pd.read_parquet(OUT/'points.parquet');v=pd.read_parquet(OUT/'intervals.parquet');c=pd.read_parquet(OUT/'calibration.parquet')
    # Prior-year asset unconditional return quantiles, same availability and dates.
    baseline=[]
    for (year,a),z in p[p.model.eq('huber')].groupby(['year','asset']):
        hist=c[(c.year==year)&(c.asset==a)&c.model.eq('huber')]
        for level in [.8,.9]:
            q=np.quantile(hist.actual,[(1-level)/2,(1+level)/2]);b=z.copy();b['model']='historical';b['center']=float(hist.actual.median());b['interval']='pooled';b['level']=level;b['lo']=q[0];b['hi']=q[1];baseline.append(b)
    base=pd.concat(baseline);v=pd.concat([v,base],ignore_index=True)
    p=pd.concat([p,base[base.level.eq(.8)][p.columns]],ignore_index=True)
    zero=p[p.model.eq('huber')].copy();zero['center']=0.;zero['model']='zero';p=pd.concat([p,zero])
    points=[];ints=[]
    periods=[('all',p),('2025_2026',p[p.year>=2025])]+[(str(y),z) for y,z in p.groupby('year')]
    for period,z in periods:
        for m,s in z.groupby('model'):points.append(dict(period=period,model=m,**point(s)))
        w=v if period=='all' else v[v.year>=2025] if period=='2025_2026' else v[v.year==int(period)]
        for (m,method,level),s in w.groupby(['model','interval','level']):ints.append(dict(period=period,model=m,interval=method,level=level,**interval(s)))
    pd.DataFrame(points).to_csv(OUT/'point_metrics.csv',index=False);pd.DataFrame(ints).to_csv(OUT/'interval_metrics.csv',index=False)
    pd.DataFrame([dict(asset=a,model=m,**point(s)) for (a,m),s in p.groupby(['asset','model'])]).to_csv(OUT/'per_stock.csv',index=False)
    pd.DataFrame([dict(high_vol=bool(h),model=m,**point(s)) for (h,m),s in p.groupby(['high_vol','model'])]).to_csv(OUT/'per_regime.csv',index=False)
    pd.DataFrame([dict(asset=a,model=m,interval=k,level=l,**interval(s)) for (a,m,k,l),s in v.groupby(['asset','model','interval','level'])]).to_csv(OUT/'per_stock_intervals.csv',index=False)
    pd.DataFrame([dict(high_vol=bool(h),model=m,interval=k,level=l,**interval(s)) for (h,m,k,l),s in v.groupby(['high_vol','model','interval','level'])]).to_csv(OUT/'per_regime_intervals.csv',index=False)
    p[p.actual<=-5].to_csv(OUT/'crash_cases.csv',index=False)
    uncertainty={}
    for period,z in [('all',p),('2025_2026',p[p.year>=2025])]:
        wide=z.pivot(index=['date','asset','actual'],columns='model',values='center').reset_index();result={}
        for m in ['catboost','hybrid_lightgbm']:
            mae=abs(wide.actual-wide.huber)-abs(wide.actual-wide[m]);nz=wide.actual.ne(0)
            direction=(np.sign(wide[m])==np.sign(wide.actual)).astype(float)-(np.sign(wide.huber)==np.sign(wide.actual)).astype(float)
            result[m]=dict(mae_reduction_vs_huber=ci(mae.groupby(wide.date).mean().sort_index()),direction_gain_vs_huber=ci(direction[nz].groupby(wide.loc[nz,'date']).mean().sort_index()))
        uncertainty[period]=result
    interval_uncertainty={}
    for level in [.8,.9]:
        z=v[v.interval.eq('pooled')&v.level.eq(level)].copy();alpha=1-level
        z['score']=z.hi-z.lo+2/alpha*((z.lo-z.actual).clip(lower=0)+(z.actual-z.hi).clip(lower=0))
        w=z.pivot(index=['date','asset'],columns='model',values='score').reset_index()
        interval_uncertainty[str(level)]={m:ci((w.huber-w[m]).groupby(w.date).mean().sort_index()) for m in ['catboost','hybrid_lightgbm']}
    uncertainty['interval_score_reduction_vs_huber']=interval_uncertainty
    (OUT/'uncertainty.json').write_text(json.dumps(uncertainty,indent=2),encoding='utf8')
    # Nested empirical quantile intervals must share center and calibration, without artificial caps.
    key=['date','asset','model','interval'];q=v[v.level.eq(.8)].merge(v[v.level.eq(.9)],on=key,suffixes=('_80','_90'),validate='one_to_one')
    assert (q.lo_90<=q.lo_80).all() and (q.hi_90>=q.hi_80).all()
    assert np.isfinite(v[['actual','center','lo','hi']]).all().all()
    print(pd.DataFrame(points).query("period in ['all','2025_2026']").to_string(index=False))
    print(pd.DataFrame(ints).query("period=='all' and interval=='pooled'").to_string(index=False))
    (OUT/'report_checks.json').write_text(json.dumps(dict(intervals_nested=True,finite=True,point_sign_definition_unified=True,zero_direction_not_meaningful=True,production_promoted=False),indent=2))

if __name__=='__main__':main()
