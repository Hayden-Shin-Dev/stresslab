"""Service-shaped scenario examples and paired baseline reporting, no promotion."""
import json
import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits
from .market_bridge_trial import OUT,F,SHOCKS,regress

def main():
    p=pd.read_parquet(OUT/'predictions.parquet');assert np.isfinite(p[['center','lo','hi','actual']]).all().all();assert (p.lo<=p.hi).all()
    ref=pd.read_parquet('reports/three_model_intervals_20261105/points.parquet');ref=ref[ref.model.eq('catboost')]
    keys=p[['date','asset']].drop_duplicates();ref=ref.merge(keys,on=['date','asset'],validate='one_to_one')
    rows=[dict(model='saved_catboost',n=len(ref),mae=float(abs(ref.actual-ref.center).mean()),direction=float((np.sign(ref.actual[ref.actual!=0])==np.sign(ref.center[ref.actual!=0])).mean())),dict(model='zero',n=len(ref),mae=float(abs(ref.actual).mean()),direction=None)]
    pd.DataFrame(rows).to_csv(OUT/'existing_baselines.csv',index=False)
    x=pd.read_parquet('reports/service_scope_20261105/corrected_features.parquet').dropna(subset=F+['target','end_date','label_known_by']);x['known']=pd.to_datetime(x.label_known_by,utc=True)
    mf=pd.read_parquet(OUT/'market_forecasts.parquet');day=p.date.max();cutoff=day.to_period('Q').start_time
    period_rows=[]
    for period,v in [('2011_2016_all_dates',mf[(mf.date>='2011-01-01')&(mf.date<='2016-12-31')]),('recent_shared_dates',mf[mf.date.isin(p.date.unique())])]:
        for arm,z in v.groupby('arm'):period_rows.append(dict(period=period,arm=arm,n=len(z),width90=float((z.hi-z.lo).mean()),coverage90=float(((z.market_actual>=z.lo)&(z.market_actual<=z.hi)).mean()),mae=float(abs(z.market_actual-z.market_prediction).mean())))
    pd.DataFrame(period_rows).to_csv(OUT/'market_period_check.csv',index=False)
    examples=[];models=[];shocks=dict(zip(SHOCKS,[5.,100.,10.,5.]));supported=set(ref.asset)
    for arm in mf.arm.unique():
        d=x.merge(mf[mf.arm.eq(arm)][['date','market_prediction','market_actual']],on='date',validate='many_to_one')
        for a,t in d[(d.date==day)&d.asset.isin(supported)].groupby('asset'):
            z=d[(d.asset==a)&(d.end_date<cutoff)&(d.known<cutoff.tz_localize('UTC'))].sort_values('date').tail(2520)
            beta=float(np.cov(z.market_actual,z.target,ddof=0)[0,1]/np.var(z.market_actual))
            for variant in ['unlinked','forecast_feature','forecast_anchor']:
                cols=F+(['market_prediction'] if variant=='forecast_feature' else []);offset=beta if variant=='forecast_anchor' else 0.
                _,m,s=regress(z,t,cols,z.target-offset*z.market_prediction)
                zero=t[cols].copy();zero[SHOCKS]=0;scenario=zero.copy()
                for k,v in shocks.items():scenario[k]=v
                base=float(m.predict(s.transform(zero))[0]+offset*t.market_prediction.iloc[0]);stress=float(m.predict(s.transform(scenario))[0]+offset*t.market_prediction.iloc[0])
                contributions={k:float(m.coef_[cols.index(k)]/s.scale_[cols.index(k)]*v) for k,v in shocks.items()}
                assert abs(stress-base-sum(contributions.values()))<1e-8
                support={k:dict(train_min=float(z[k].min()),train_max=float(z[k].max()),outside_marginal_range=bool(v<z[k].min() or v>z[k].max())) for k,v in shocks.items()}
                examples.append(dict(asset=a,model=arm+'__'+variant,state_date=str(day.date()),fit_cutoff=str(cutoff.date()),shocks=shocks,baseline_return_pct=base,stress_return_pct=stress,shock_change_pp=stress-base,contributions_pp=contributions,holding_krw=1000000,hypothetical_pnl_krw=1000000*stress/100,shock_increment_pnl_krw=1000000*(stress-base)/100,support=support,exploratory=True,joint_shock_support_certified=False))
                models.append(dict(asset=a,model=arm+'__'+variant,columns=cols,mean=s.mean_.tolist(),scale=s.scale_.tolist(),coef=m.coef_.tolist(),intercept=float(m.intercept_),forecast_anchor_beta=offset,fit_cutoff=str(cutoff.date()),train_n=len(z)))
    (OUT/'scenario_examples.json').write_text(json.dumps(examples,indent=2,allow_nan=False),encoding='utf8');(OUT/'research_stock_models.json').write_text(json.dumps(models,allow_nan=False),encoding='utf8')
    pp=p[p.level.eq(.9)].copy();pp['error']=abs(pp.actual-pp.center)
    diff=[]
    for arm in mf.arm.unique():
        a=pp[pp.model.eq(arm+'__unlinked')].groupby('asset').error.mean()
        for variant in ['forecast_feature','forecast_anchor']:
            b=pp[pp.model.eq(arm+'__'+variant)].groupby('asset').error.mean();diff.append(dict(arm=arm,variant=variant,improved_assets=int((b<a).sum()),total=len(a)))
    pd.DataFrame(diff).to_csv(OUT/'improved_assets.csv',index=False)
    (OUT/'checks.json').write_text(json.dumps(dict(finite_outputs=True,intervals_ordered=True,shock_contribution_identity=True,scenario_example_date=str(day.date()),scenarios=len(examples),not_live_or_approved=True),indent=2))
    print(pd.DataFrame(rows).to_string(index=False));print(pd.DataFrame(diff).to_string(index=False))

if __name__=='__main__':
    with threadpool_limits(limits=2):main()
