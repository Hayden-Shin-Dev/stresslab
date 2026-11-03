"""Four interval families, fixed centers and chronological out-of-sample residuals."""
import json,hashlib,sys
import numpy as np
import pandas as pd
from scipy.stats import norm
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import Ridge
from lightgbm import LGBMRegressor
from xgboost import XGBRegressor
from gold_quantile_benchmark import ROOT,build,FEATURES,record
OUT=ROOT/'reports/oos_residual_intervals_20261103'

def lgb(q):
    return LGBMRegressor(objective='quantile',alpha=q,n_estimators=250,learning_rate=.04,max_depth=4,num_leaves=15,min_child_samples=40,random_state=20261103,n_jobs=2,verbosity=-1)

def main():
    OUT.mkdir(parents=True,exist_ok=True);path=ROOT/'exports/seongjin_gold_v1_1/gold_stress_daily.parquet';g=pd.read_parquet(path)
    protocol={'gold_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'features':FEATURES,
        'centers':'Same existing normalized-target Ridge(mean), LightGBM(q50), XGBoost(q50), fixed settings',
        'methods':{'volatility':'center +/- norm.ppf(.95)*sigma5','raw_residual':'center + calibration raw-return residual quantiles(.05,.5,.95)','scaled_residual':'center + test sigma5 * calibration (residual/cal sigma5) quantiles(.05,.5,.95)','lightgbm_direct':'separate q05/q50/q95 models on train only, times test sigma5; crossing sorted and counted'},
        'splits':'yearly 2023-2026; train end before prior year minus20calendar days; previous year calibration with end before test year minus20days; cal/test every6 valid rows; remove test outcomes ending in next calendar year',
        'overlap':'No overlapping five-session outcomes between train/cal/test or within cal/test; overlap within training only allowed',
        'scopes':'selected20 assets, not entire KOSPI; portfolio equal initial Samsung/Hyundai 50/50',
        'regimes':'all; high market volatility above training 2/3 quantile; market crash = KOSPI five-session simple return<=-5%; actual asset loss<=-5% extra diagnostic',
        'bootstrap':'paired moving circular date blocks of10 evaluation dates,1000 repeats; within regime resample full chronological date series then subset',
        'acceptance':'descriptive coverage>=.88 and no decrease vs own volatility baseline; smaller width; lower interval score; no greater lower breach or shortfall in all/high_vol/market_crash; >=30 dates each for robust selection; CI uncertainty reported, no test tuning',
        'blind':False,'limits':'reused dates, publication timestamps null, revision/survivorship bias, macro observation endpoints asynchronous',
        'deployment':False}
    (OUT/'protocol.json').write_text(json.dumps(protocol,ensure_ascii=False,indent=2),encoding='utf8')
    data=build(g);market=g.groupby('trading_date').kospi_close.first().sort_index();crash=(market.shift(-5)/market-1)*100;crash.index=pd.to_datetime(crash.index)
    rows=[];boundaries=[];quantiles=[];crossings=0
    for asset,f in data.groupby('asset'):
        f=f.sort_values('date')
        for year in [2023,2024,2025,2026]:
            cut=pd.Timestamp(year,1,1);calcut=pd.Timestamp(year-1,1,1)
            train=f[f.end_date<calcut-pd.Timedelta(days=20)]
            cal=f[(f.date>=calcut)&(f.end_date<cut-pd.Timedelta(days=20))].iloc[::6]
            test=f[(f.date>=cut)&(f.date<pd.Timestamp(year+1,1,1))].iloc[::6]
            test=test[test.end_date<pd.Timestamp(year+1,1,1)]
            if len(train)<250 or len(cal)<30 or not len(test):continue
            assert train.end_date.max()<cal.date.min() and cal.end_date.max()<test.date.min()
            for z in [cal,test]:assert (z.end_date.to_numpy()[:-1]<z.date.to_numpy()[1:]).all()
            boundaries.append(dict(asset=asset,fold=year,train_n=len(train),cal_n=len(cal),test_n=len(test),train_end=str(train.end_date.max()),cal_start=str(cal.date.min()),cal_end=str(cal.end_date.max()),test_start=str(test.date.min()),test_end=str(test.end_date.max())))
            tx=train[FEATURES];cx=cal[FEATURES];qx=test[FEATURES];y=train.target/train.scale;ss=test.scale.to_numpy();cs=cal.scale.to_numpy()
            models={'ridge':make_pipeline(StandardScaler(),Ridge(alpha=30)),'lightgbm':lgb(.5),
                'xgboost':XGBRegressor(objective='reg:quantileerror',quantile_alpha=.5,n_estimators=250,learning_rate=.04,max_depth=4,min_child_weight=20,random_state=20261103,n_jobs=2,tree_method='hist')}
            for name,model in models.items():
                model.fit(tx,y);center=model.predict(qx)*ss;c=model.predict(cx)*cs;res=cal.target.to_numpy()-c
                rq=np.quantile(res,[.05,.5,.95]);sq=np.quantile(res/cs,[.05,.5,.95])
                quantiles.append(dict(asset=asset,fold=year,model=name,raw_q05=rq[0],raw_q50=rq[1],raw_q95=rq[2],scaled_q05=sq[0],scaled_q50=sq[1],scaled_q95=sq[2]))
                bounds={'volatility':np.column_stack([center-norm.ppf(.95)*ss,center,center+norm.ppf(.95)*ss]),
                    'raw_residual':center[:,None]+rq[None,:], 'scaled_residual':center[:,None]+sq[None,:]*ss[:,None]}
                if name=='lightgbm':
                    low=lgb(.05).fit(tx,y).predict(qx)*ss;high=lgb(.95).fit(tx,y).predict(qx)*ss
                    q=np.column_stack([low,center,high]);crossings+=int((np.diff(q,axis=1)<0).any(axis=1).sum());bounds['direct_quantile']=np.sort(q,axis=1)
                for method,q in bounds.items():
                    out=record(test,q,name+'_'+method,year,train,cal);out['center_model']=name;out['method']=method;out['raw_center']=center
                    out['market_return5']=test.date.map(crash).to_numpy();out['high_vol']=out.regime.eq('high');out['market_crash']=out.market_return5<=-5
                    out['asset_crash']=out.actual<=-5;out['upper_breach']=(out.actual>out.q95).astype(float);rows.append(out)
            print(asset,year,len(test),flush=True)
        if rows:pd.concat(rows,ignore_index=True).to_parquet(OUT/'predictions.parquet',index=False)
    pd.DataFrame(boundaries).to_csv(OUT/'time_boundaries.csv',index=False);pd.DataFrame(quantiles).to_csv(OUT/'calibration_quantiles.csv',index=False)
    r=pd.concat(rows,ignore_index=True)
    for _,z in r[['date','asset']].drop_duplicates().merge(data[['date','asset','end_date']],on=['date','asset'],validate='one_to_one').groupby('asset'):
        z=z.sort_values('date');assert (z.end_date.to_numpy()[:-1]<z.date.to_numpy()[1:]).all()
    assert r.groupby(['date','asset']).model.nunique().min()==10
    assert r.groupby(['date','asset','center_model']).raw_center.nunique().max()==1
    old=pd.read_parquet(ROOT/'reports/center_volatility_20261103/predictions.parquet');a=r[r.method.eq('volatility')];b=old[old.interval_method.eq('normal90')]
    paired=a.merge(b,on=['date','asset','center_model'],suffixes=('_a','_b'));err=max((paired[c+'_a']-paired[c+'_b']).abs().max() for c in ['q05','q95','median','actual']);assert err<1e-9
    (OUT/'verification.json').write_text(json.dumps({'models_trained':True,'same_samples':True,'same_raw_centers':True,'time_boundary_and_nonoverlap_assertions':True,'volatility_matches_previous_max_error':err,'direct_quantile_crossings_sorted':crossings,'rows':len(r),'no_cloud_changes':True},indent=2),encoding='utf8')
    summarize(r)

def summarize(r):
    scores=['coverage','width','interval_score','breach','miss_size','upper_breach','mae','pinball05'];summaries=[];comparisons=[];decisions=[]
    for scope,x in [('portfolio',r[r.asset.eq('portfolio')]),('stocks',r[~r.asset.eq('portfolio')])]:
        for regime in ['all','high_vol','market_crash','asset_crash']:
            part=x if regime=='all' else x[x[regime]]
            for name,z in part.groupby('model'):
                row=z[scores].mean().to_dict();row.update(scope=scope,regime=regime,model=name,n=len(z),dates=z.date.nunique());summaries.append(row)
        for name,z in x.groupby('model'):
            if z.method.iloc[0]=='volatility':continue
            base=x[x.model.eq(z.center_model.iloc[0]+'_volatility')];pair=z.merge(base,on=['date','asset'],suffixes=('_a','_b'))
            all_pass=True
            for regime in ['all','high_vol','market_crash','asset_crash']:
                mask=np.ones(len(pair),dtype=bool) if regime=='all' else pair[regime+'_a'].to_numpy()
                selected=pair[mask];n_dates=selected.date.nunique()
                if not len(selected):all_pass=False;continue
                means={c:(selected[c+'_a'].mean(),selected[c+'_b'].mean()) for c in scores}
                passes=(means['coverage'][0]>=.88 and means['coverage'][0]>=means['coverage'][1]-1e-12 and means['width'][0]<means['width'][1] and means['interval_score'][0]<means['interval_score'][1] and means['breach'][0]<=means['breach'][1]+1e-12 and means['miss_size'][0]<=means['miss_size'][1]+1e-12)
                if regime!='asset_crash':all_pass &= passes and n_dates>=30
                # Full-date block resampling keeps chronology before filtering rare regimes.
                pair=pair.assign(selected=mask)
                dategrid=sorted(pair.date.unique());n=len(dategrid);block=min(10,n);rng=np.random.default_rng(20261103)
                indices=[np.concatenate([(s+np.arange(block))%n for s in rng.integers(n,size=int(np.ceil(n/block)))])[:n] for _ in range(1000)]
                for metric in ['coverage','width','interval_score','breach','miss_size']:
                    grouped=pair.assign(delta=(pair[metric+'_a']-pair[metric+'_b']).where(pair.selected)).groupby('date').delta.agg(['sum','count']).reindex(dategrid)
                    totals=grouped['sum'].to_numpy();counts=grouped['count'].to_numpy()
                    boot=[totals[i].sum()/counts[i].sum() for i in indices if counts[i].sum()>0]
                    av,bv=means[metric];comparisons.append(dict(scope=scope,model=name,regime=regime,metric=metric,dates=n_dates,candidate=av,baseline=bv,delta=av-bv,improvement_pct=((av-bv) if metric=='coverage' else (bv-av))/abs(bv)*100 if bv else np.nan,ci_low=np.quantile(boot,.025),ci_high=np.quantile(boot,.975),descriptive_gate=passes))
            decisions.append(dict(scope=scope,model=name,passes_all_regimes_with_sample_min=bool(all_pass),production_approved=False,reason='research_only; see regime metrics and uncertainty; publication unverified'))
    pd.DataFrame(summaries).to_csv(OUT/'metrics.csv',index=False);pd.DataFrame(comparisons).to_csv(OUT/'paired_block_comparisons.csv',index=False);pd.DataFrame(decisions).to_csv(OUT/'selection.csv',index=False)
    r[r.asset_crash].sort_values('miss_size',ascending=False).head(60).to_csv(OUT/'failure_cases.csv',index=False)
    print(pd.DataFrame(summaries).query("scope=='portfolio'").round(4).to_string(index=False),flush=True)

def audit_holdout():
    g=pd.read_parquet(ROOT/'exports/seongjin_gold_v1_1/gold_stress_daily.parquet')
    old=pd.read_parquet(ROOT/'reports/gold_quantile_benchmark_20261103/predictions.parquet')
    result={'gold_first':str(pd.to_datetime(g.trading_date).min().date()),'gold_last':str(pd.to_datetime(g.trading_date).max().date()),
        'prior_evaluation_first':str(old.date.min().date()),'prior_evaluation_last':str(old.date.max().date()),
        'independent_blind_claim':False,'certified_unused_historical_final_period':None,
        'reason':'Existing Gold has supported model comparisons and overlapping five-session outcomes. Unused rows are not necessarily independent holdout.',
        'prospective_plan':{'new_origin_after':'2026-11-03','freeze_before_new_evaluation':True,
        'wait_for':'five observed KRX trading-session closes and required factor observations/publications',
        'sampling':'nonoverlapping six-session-spaced origins','minimum_30_windows':'approximately180 trading sessions; independent crises not guaranteed',
        'required':'versioned Gold, real publication times, corporate actions and universe membership','cloud_changes':False}}
    (OUT/'holdout_audit.json').write_text(json.dumps(result,indent=2),encoding='utf8')

def recheck_cached():
    """Remove cross-year evaluation overlap without retraining or changing predictions."""
    data=build(pd.read_parquet(ROOT/'exports/seongjin_gold_v1_1/gold_stress_daily.parquet'))
    r=pd.read_parquet(OUT/'predictions.parquet').merge(data[['date','asset','end_date']],on=['date','asset'],validate='many_to_one')
    before=len(r);r=r[r.end_date.dt.year.eq(r.fold)].copy()
    for _,z in r[['date','asset','end_date']].drop_duplicates().groupby('asset'):
        z=z.sort_values('date');assert (z.end_date.to_numpy()[:-1]<z.date.to_numpy()[1:]).all()
    r.drop(columns='end_date').to_parquet(OUT/'predictions.parquet',index=False)
    b=pd.read_csv(OUT/'time_boundaries.csv')
    for i,row in b.iterrows():
        z=r[(r.asset==row.asset)&(r.fold==row.fold)]
        b.loc[i,'test_n']=z.date.nunique();b.loc[i,'test_end']=str(z.end_date.max())
    b.to_csv(OUT/'time_boundaries.csv',index=False)
    v=json.loads((OUT/'verification.json').read_text());v.update(rows=len(r),all_evaluation_windows_nonoverlapping_across_years=True,removed_cross_year_prediction_rows=before-len(r),cache_purge_retrained=False)
    (OUT/'verification.json').write_text(json.dumps(v,indent=2),encoding='utf8')
    protocol=json.loads((OUT/'protocol.json').read_text());protocol['cross_year_purge']='exclude every test outcome ending in next calendar year; same rows removed in all10 methods'
    (OUT/'protocol.json').write_text(json.dumps(protocol,indent=2),encoding='utf8');summarize(r);audit_holdout()

if __name__=='__main__':
    if '--recheck-cache' in sys.argv:recheck_cached()
    else:
        main()
        audit_holdout()
