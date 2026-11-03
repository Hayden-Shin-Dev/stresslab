"""Matched tail diagnostics, uncertainty and failures, without changing study methods."""
import json
import numpy as np
import pandas as pd
from tail_reliability_research import SRC,OUT

def weighted_blocks(numerator,denominator):
    n=len(numerator);rng=np.random.default_rng(20261103)
    starts=rng.integers(n,size=(2000,int(np.ceil(n/10))))
    ix=((starts[:,:,None]+np.arange(10))%n).reshape(2000,-1)[:,:n]
    den=denominator[ix].sum(1);valid=den>0
    draws=numerator[ix].sum(1)[valid]/den[valid]
    delta=numerator.sum()/denominator.sum()
    return dict(delta=float(delta),ci_low=float(np.quantile(draws,.025)),ci_high=float(np.quantile(draws,.975)),bootstrap_p=float((1+np.sum(abs(draws-delta)>=abs(delta)))/(1+len(draws))))

def metrics(s):
    return dict(n=len(s),dates=s.date.nunique(),mae=s.center_mae.mean(),coverage=s.coverage.mean(),width=s.width.mean(),interval_score=s.interval_score.mean(),lower_breach=s.lower_breach.mean(),missed_loss_pp=s.missed_loss_pp.mean(),pinball10=np.maximum(.1*(s.actual-s.q10),-.9*(s.actual-s.q10)).mean(),fixed_width5_coverage=(abs(s.actual-s.center)<=2.5).mean())

def main():
    r=pd.read_parquet(OUT/'predictions.parquet');g=pd.read_parquet(OUT/'guard_predictions.parquet')
    r=pd.concat([r,g],ignore_index=True);r.to_parquet(OUT/'all_comparisons.parquet',index=False)
    aggregate=[];per=[];annual=[];comparison=[]
    for method,s in r.groupby('method'):
        for regime in ['all','high_vol','asset_crash']:
            z=s if regime=='all' else s[s[regime]];aggregate.append(dict(method=method,regime=regime,**metrics(z)))
        for asset,z in s.groupby('asset'):
            for regime in ['all','asset_crash']:per.append(dict(asset=asset,method=method,regime=regime,**metrics(z if regime=='all' else z[z.asset_crash])))
        for year,z in s.groupby(s.date.dt.year):annual.append(dict(method=method,year=year,**metrics(z)))
    old=r[r.method=='existing_all4']
    for method,s in r.groupby('method'):
        if method=='existing_all4':continue
        z=s.merge(old,on=['asset','date'],suffixes=('_new','_old'),validate='one_to_one');assert len(z)==918
        for regime in ['all','asset_crash']:
            x=z if regime=='all' else z[z.asset_crash_old]
            for col in ['coverage','width','interval_score','lower_breach','missed_loss_pp']:
                # All assets from one time block are resampled together.
                delta=x.set_index('date')[col+'_new']-x.set_index('date')[col+'_old']
                dates=pd.DatetimeIndex(sorted(old.date.unique()))
                numerator=delta.groupby(level=0).sum().reindex(dates,fill_value=0).to_numpy()
                denominator=delta.groupby(level=0).count().reindex(dates,fill_value=0).to_numpy()
                result=weighted_blocks(numerator,denominator)
                assert abs(result['delta']-delta.mean())<1e-10
                comparison.append(dict(method=method,baseline='existing_all4',regime=regime,metric=col,**result))
    a=r[r.method=='residual_tail_guard'];b=r[r.method=='same_width_symmetric_control']
    z=a.merge(b,on=['asset','date'],suffixes=('_new','_old'),validate='one_to_one')
    assert np.max(abs(z.width_new-z.width_old))<1e-10
    for regime in ['all','asset_crash']:
        x=z if regime=='all' else z[z.asset_crash_old]
        for col in ['coverage','interval_score','lower_breach','missed_loss_pp']:
            delta=x.set_index('date')[col+'_new']-x.set_index('date')[col+'_old'];dates=pd.DatetimeIndex(sorted(old.date.unique()))
            comparison.append(dict(method='residual_tail_guard',baseline='same_width_symmetric_control',regime=regime,metric=col,**weighted_blocks(delta.groupby(level=0).sum().reindex(dates,fill_value=0).to_numpy(),delta.groupby(level=0).count().reindex(dates,fill_value=0).to_numpy())))
    pd.DataFrame(aggregate).to_csv(OUT/'aggregate.csv',index=False);pd.DataFrame(per).to_csv(OUT/'per_asset.csv',index=False);pd.DataFrame(annual).to_csv(OUT/'by_year.csv',index=False);pd.DataFrame(comparison).to_csv(OUT/'block_uncertainty.csv',index=False)
    # Existing calibrated residual q10 against realized normalized OOS residual q10.
    d=pd.read_parquet(SRC/'learning_table.parquet');res=old.merge(d[['asset','date','scale','shock_fx','shock_rate','shock_oil','shock_vix']],on=['asset','date'],suffixes=('','_input'),validate='one_to_one')
    residuals=[]
    for (asset,year),z in res.groupby(['asset',res.date.dt.year]):
        residuals.append(dict(asset=asset,year=year,n=len(z),calibrated_normalized_q10=((z.q10-z.center)/z.scale).median(),realized_normalized_q10=np.quantile((z.actual-z.center)/z.scale,.1),realized_normalized_median=np.median((z.actual-z.center)/z.scale)))
    pd.DataFrame(residuals).to_csv(OUT/'residual_calibration_drift.csv',index=False)
    failures=old[old.asset_crash & old.lower_breach.eq(1)].copy();guard=g[g.method=='residual_tail_guard'][['asset','date','q10','lower_breach']].rename(columns={'q10':'guard_q10','lower_breach':'guard_lower_breach'})
    failures=failures.merge(guard,on=['asset','date'],validate='one_to_one').sort_values('missed_loss_pp',ascending=False)
    failures[['asset','date','end_date','actual','center','q10','q90','guard_q10','guard_lower_breach','missed_loss_pp','shock_fx','shock_rate']].to_csv(OUT/'failure_cases.csv',index=False)
    context=[]
    for (asset,year),z in old.groupby(['asset',old.date.dt.year]):
        tr=d[(d.asset==asset)&(d.end_date<pd.Timestamp(year-1,1,1)-pd.Timedelta(days=20))]
        thresholds=tr[['shock_fx','shock_rate','shock_oil','shock_vix']].abs().quantile(.75)
        h=z.merge(d[['asset','date','shock_oil','shock_vix']],on=['asset','date'],validate='one_to_one')
        small=(h[['shock_fx','shock_rate','shock_oil','shock_vix']].abs()<=thresholds).all(axis=1)
        context.append(dict(asset=asset,year=year,crash_n=int(h.asset_crash.sum()),crashes_with_all_four_within_train_abs_q75=int((h.asset_crash&small).sum())))
    pd.DataFrame(context).to_csv(OUT/'crash_shock_context.csv',index=False)
    print(pd.DataFrame(aggregate).query("regime=='all'").round(4).to_string(index=False))

if __name__=='__main__':main()
