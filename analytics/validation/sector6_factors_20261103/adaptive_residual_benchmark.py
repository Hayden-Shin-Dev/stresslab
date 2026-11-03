"""Historical out-of-sample residual banks and causal online updates. Research only."""
import json,sys,hashlib
import numpy as np
import pandas as pd
from scipy.stats import norm
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import Ridge
from lightgbm import LGBMRegressor
from xgboost import XGBRegressor
from gold_quantile_benchmark import ROOT,build,FEATURES
OUT=ROOT/'reports/adaptive_residual_20261103'

def models():
    return {'ridge':make_pipeline(StandardScaler(),Ridge(alpha=30)),
        'lightgbm':LGBMRegressor(objective='quantile',alpha=.5,n_estimators=250,learning_rate=.04,max_depth=4,num_leaves=15,min_child_samples=40,random_state=20261103,n_jobs=2,verbosity=-1),
        'xgboost':XGBRegressor(objective='reg:quantileerror',quantile_alpha=.5,n_estimators=250,learning_rate=.04,max_depth=4,min_child_weight=20,random_state=20261103,n_jobs=2,tree_method='hist')}

def weighted_q(values,weights):
    order=np.argsort(values);v=np.asarray(values)[order];w=np.asarray(weights)[order];w=w/w.sum();t=np.cumsum(w)-w/2;t=(t-t[0])/(t[-1]-t[0]);return np.interp([.1,.5,.9],t,v)

def rec(t,q,model,method,pool,weights,fallback,high_cut,crash,center):
    lo,med,hi=q;y=t.target
    return dict(date=t.date,end_date=t.end_date,asset=t.asset,model=model,method=method,actual=y,center=center,median=med,q10=lo,q90=hi,
        width=hi-lo,coverage=float(lo<=y<=hi),interval_score=hi-lo+(20 if method=='vol90' else 10)*(max(lo-y,0)+max(y-hi,0)),mae=abs(y-med),
        breach=float(y<lo),miss_size=max(lo-y,0),high_vol=t.market_vol20>high_cut,market_crash=crash<=-5,asset_crash=y<=-5,
        cal_n=len(pool),ess=1/(weights@weights) if len(weights) else np.nan,
        latest_residual_ready=str(pool.ready.max()) if len(pool) else None,fallback=fallback,
        forced5_coverage=float(abs(y-med)<=2.5),nominal=.8 if method!='vol90' else .9)

def main():
    OUT.mkdir(parents=True,exist_ok=True);path=ROOT/'exports/seongjin_gold_v1_1/gold_stress_daily.parquet';g=pd.read_parquet(path);data=build(g)
    market=g.groupby('trading_date').kospi_close.first().sort_index();cr=(market.shift(-5)/market-1)*100;cr.index=pd.to_datetime(cr.index)
    protocol={'goal':'mean total width<=5pp, coverage>=80%, no worsened crash capture',
        'alpha':.2,'gold_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
        'center_models':'same fixed yearly Ridge, LightGBM q50, XGBoost q50 settings; no tuning',
        'banks':'annual vintage models train before each calibration year; saved out-of-sample raw and scaled errors; 1,3,5year frozen vs3year online vs5year online age-weighted',
        'vintage_limit':'Older residuals come from earlier eligible model vintages, not in-sample reruns of current model. This is forecast-error pooling, not current-model residuals.',
        'causal_updates':'current-year error can enter only if target end +20calendar days strictly precedes query; model parameters and interval rule never tuned to test scores',
        'decay':'365-calendar-day half-life, full5year online bank',
        'sample_policy':'prior-year frozen baseline at least30 observations; pools below30 fall back explicitly to frozen prior-year bank; no overlapping five-session outcomes in each bank or evaluation',
        'split':'same purged2023-2026 evaluation rows as prior benchmark; older error vintages built from2017 onward',
        'publication':'Gold public-release timestamps unknown; end+20days is a proxy and cannot certify historical availability/vintages',
        'blind':False,'selection':'paired10-date block bootstrap1000, all/highvol/marketcrash; candidate must meet width5 coverage80 and no worsened breach/miss_size vs vol80 and frozen1_scaled; keep vol90 safety reference',
        'cloud_changes':False,'contract_changes':False,
        'additional_predeclared_comparator':'LightGBM direct q10/q50/q90, same settings and evaluation dates; no test-based tuning',
        'acceptance_clarification':'width5 and coverage80 apply to overall mean; highvol and crash must not worsen coverage, interval score, lower breaches or shortfall vs paired80% baselines'}
    (OUT/'protocol.json').write_text(json.dumps(protocol,indent=2),encoding='utf8');rows=[];audit=[]
    for asset,f in data.groupby('asset'):
        f=f.sort_values('date');banks={k:[] for k in models()}
        for year in range(2018,2027):
            cut=pd.Timestamp(year,1,1);cc=pd.Timestamp(year-1,1,1)
            tr=f[f.end_date<cc-pd.Timedelta(days=20)];ca=f[(f.date>=cc)&(f.end_date<cut-pd.Timedelta(days=20))].iloc[::6]
            te=f[(f.date>=cut)&(f.date<pd.Timestamp(year+1,1,1))].iloc[::6];te=te[te.end_date<pd.Timestamp(year+1,1,1)]
            if len(tr)<250 or len(ca)<30:continue
            assert tr.end_date.max()<ca.date.min()
            for z in [ca,te]:assert (z.end_date.to_numpy()[:-1]<z.date.to_numpy()[1:]).all()
            for name,m in models().items():
                m.fit(tr[FEATURES],tr.target/tr.scale);cp=m.predict(ca[FEATURES])*ca.scale.to_numpy()
                residual=ca[['date','end_date','scale']].copy();residual['raw']=ca.target.to_numpy()-cp;residual['scaled']=residual.raw/residual.scale
                residual['ready']=residual.end_date+pd.Timedelta(days=20);residual['vintage']=year
                banks[name].append(residual)
                if year<2023 or not len(te):continue
                frozen=pd.concat(banks[name],ignore_index=True).sort_values('date');frozen=frozen[frozen.ready<cut]
                assert (frozen.end_date.to_numpy()[:-1]<frozen.date.to_numpy()[1:]).all()
                one=residual[residual.ready<cut].copy();assert len(one)>=30
                centers=m.predict(te[FEATURES])*te.scale.to_numpy();high_cut=tr.market_vol20.quantile(2/3)
                online=[]
                for i,(_,t) in enumerate(te.iterrows()):
                    center=centers[i];empty=one.iloc[:0];empty_weights=np.array([])
                    for label,mult in [('vol80',norm.ppf(.9)),('vol90',norm.ppf(.95))]:
                        rows.append(rec(t,np.array([center-mult*t.scale,center,center+mult*t.scale]),name,label,empty,empty_weights,False,high_cut,cr.get(t.date,np.nan),center))
                    mature=pd.DataFrame(online);bank=frozen if mature.empty else pd.concat([frozen,mature[mature.ready<t.date]],ignore_index=True).sort_values('date')
                    for label,years,source,decay in [('frozen1',1,one,False),('frozen3',3,frozen,False),('frozen5',5,frozen,False),('rolling3',3,bank,False),('rolling5_decay',5,bank,True)]:
                        start=(cut if label.startswith('frozen') else t.date)-pd.DateOffset(years=years)
                        pool=source[(source.date>=start)&(source.ready<t.date)].copy();fallback=len(pool)<30
                        if fallback:pool=one.copy()
                        assert (pool.ready<t.date).all() and (pool.end_date.to_numpy()[:-1]<pool.date.to_numpy()[1:]).all()
                        ages=(t.date-pool.date).dt.days.to_numpy();weight=np.exp(-np.log(2)*ages/365) if decay else np.ones(len(pool));weight/=weight.sum()
                        for unit in (['scaled'] if decay else ['raw','scaled']):
                            q=weighted_q(pool[unit],weight);q=center+q*(t.scale if unit=='scaled' else 1)
                            rows.append(rec(t,q,name,label+'_'+unit,pool,weight,fallback,high_cut,cr.get(t.date,np.nan),center))
                    # Appended only after prediction; inaccessible until end+20 days.
                    online.append(dict(date=t.date,end_date=t.end_date,ready=t.end_date+pd.Timedelta(days=20),scale=t.scale,raw=t.target-center,scaled=(t.target-center)/t.scale,vintage=year))
                audit.append(dict(asset=asset,year=year,model=name,train=len(tr),cal1=len(one),cal5=len(frozen[frozen.date>=cut-pd.DateOffset(years=5)]),test=len(te)))
            if year>=2023:print(asset,year,len(te),flush=True)
        if rows:pd.DataFrame(rows).to_parquet(OUT/'predictions.parquet',index=False)
    r=pd.DataFrame(rows);pd.DataFrame(audit).to_csv(OUT/'sample_audit.csv',index=False)
    old=pd.read_parquet(ROOT/'reports/oos_residual_intervals_20261103/predictions.parquet')
    for name in models():
        x=r[(r.model==name)&(r.method=='vol90')].merge(old[old.model.eq(name+'_volatility')],on=['asset','date'],suffixes=('_a','_b'),validate='one_to_one')
        assert len(x)==len(old[old.model.eq(name+'_volatility')])
        assert np.max(abs(x.q10-x.q05))<1e-9 and np.max(abs(x.q90-x.q95))<1e-9
    assert r.groupby(['date','asset','model']).center.nunique().max()==1
    (OUT/'verification.json').write_text(json.dumps({'same_evaluation_rows':True,'old90_bounds_reproduced':True,'same_centers':True,'residual_maturity_assertions':True,'nonoverlapping_banks':True,'rows':len(r),'no_cloud_changes':True},indent=2),encoding='utf8')
    summarize(r)

def summarize(r):
    summaries=[];pairs=[];decisions=[];scores=['coverage','width','interval_score','breach','miss_size','mae','cal_n','ess','fallback','forced5_coverage']
    for scope,x in [('portfolio',r[r.asset.eq('portfolio')]),('stocks',r[~r.asset.eq('portfolio')])]:
        for regime in ['all','high_vol','market_crash','asset_crash']:
            z=x if regime=='all' else x[x[regime]]
            for (model,method),p in z.groupby(['model','method']):
                a=p[scores].mean().to_dict();a.update(scope=scope,regime=regime,model=model,method=method,n=len(p),dates=p.date.nunique());summaries.append(a)
        for (model,method),z in x.groupby(['model','method']):
            if method in ['vol80','vol90']:continue
            total_pass=True
            for baseline in ['vol80','frozen1_scaled']:
                b=x[(x.model==model)&(x.method==baseline)];p=z.merge(b,on=['date','asset'],suffixes=('_a','_b'))
                dates=sorted(p.date.unique());n=len(dates);block=min(10,n);rng=np.random.default_rng(20261103)
                ids=np.array([np.concatenate([(s+np.arange(block))%n for s in rng.integers(n,size=int(np.ceil(n/block)))])[:n] for _ in range(1000)])
                for regime in ['all','high_vol','market_crash']:
                    selected=np.ones(len(p),bool) if regime=='all' else p[regime+'_a'].to_numpy();s=p[selected]
                    if not len(s):total_pass=False;continue
                    target=(regime!='all' or (s.coverage_a.mean()>=.8 and s.width_a.mean()<=5))
                    gate=(target and s.coverage_a.mean()>=s.coverage_b.mean()-1e-12 and s.interval_score_a.mean()<=s.interval_score_b.mean()+1e-12 and s.breach_a.mean()<=s.breach_b.mean()+1e-12 and s.miss_size_a.mean()<=s.miss_size_b.mean()+1e-12)
                    total_pass &= gate
                    for metric in ['coverage','width','interval_score','breach','miss_size']:
                        d=p.assign(delta=(p[metric+'_a']-p[metric+'_b']).where(selected)).groupby('date').delta.agg(['sum','count']).reindex(dates)
                        vv=d['sum'].to_numpy();nn=d['count'].to_numpy();den=nn[ids].sum(axis=1);bs=vv[ids].sum(axis=1)[den>0]/den[den>0]
                        av,bv=s[metric+'_a'].mean(),s[metric+'_b'].mean()
                        pairs.append(dict(scope=scope,model=model,method=method,baseline=baseline,regime=regime,metric=metric,dates=s.date.nunique(),candidate=av,baseline_value=bv,delta=av-bv,ci_low=np.quantile(bs,.025),ci_high=np.quantile(bs,.975),descriptive_gate=gate))
            decisions.append(dict(scope=scope,model=model,method=method,passes_requested_gate=bool(total_pass),production_approved=False))
    pd.DataFrame(summaries).to_csv(OUT/'metrics.csv',index=False);pd.DataFrame(pairs).to_csv(OUT/'paired_blocks.csv',index=False);pd.DataFrame(decisions).to_csv(OUT/'selection.csv',index=False)
    r[r.market_crash].sort_values('miss_size',ascending=False).head(100).to_csv(OUT/'failure_cases.csv',index=False)
    print(pd.DataFrame(summaries).query("scope=='portfolio' and regime=='all'").round(3).to_string(index=False),flush=True)

if __name__=='__main__':main()
