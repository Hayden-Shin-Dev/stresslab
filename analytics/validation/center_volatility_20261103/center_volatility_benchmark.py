"""Center model ablation with identical symmetric volatility intervals."""
import json,sys,hashlib
import numpy as np
import pandas as pd
from scipy.stats import norm
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import Ridge
from lightgbm import LGBMRegressor
from xgboost import XGBRegressor
from gold_quantile_benchmark import ROOT,build,FEATURES,record
OUT=ROOT/'reports/center_volatility_20261103'

def main():
    OUT.mkdir(parents=True,exist_ok=True);path=ROOT/'exports/seongjin_gold_v1_1/gold_stress_daily.parquet'
    protocol={'source':'Gold v1.1 only','sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'features':FEATURES,
        'center_models':{'ridge':'squared loss; conditional mean, not median','lightgbm':'quantile alpha=.5','xgboost':'reg:quantileerror quantile_alpha=.5','constant':'training median baseline'},
        'fixed_interval':'center +/- 1.64485362695 * sqrt(5*(daily_std20^2+daily_std60^2)/2)',
        'calibrated_interval':'center +/- k*sigma5; k is previous-year 90th percentile of abs(actual-center)/sigma5',
        'width':'total 2*k*sigma5; same fixed width across all center models',
        'split':'annual 2023-2026; train through two years before test; previous year disjoint calibration; label-end 20 calendar-day embargo',
        'params':'250 trees, learning_rate=.04, depth4; lgbm15 leaves/min_child_samples40; xgb min_child_weight20; seed20261103; no test tuning',
        'limitations':'Previously examined dates; publication timestamps unknown; not blind, not causal, not intraday; symmetry and sqrt5 scaling are hypotheses, not guarantees',
        'portfolio':'direct same-date 50/50 Samsung/Hyundai targets; portfolio volatility uses historical joint daily returns, not average stock volatilities',
        'no_deployment':True}
    (OUT/'protocol.json').write_text(json.dumps(protocol,ensure_ascii=False,indent=2),encoding='utf8')
    data=build(pd.read_parquet(path));rows=[];factors=[];counts=[]
    for asset,frame in data.groupby('asset'):
        frame=frame.sort_values('date')
        for year in [2023,2024,2025,2026]:
            cut=pd.Timestamp(year,1,1);calcut=pd.Timestamp(year-1,1,1)
            train=frame[frame.end_date<calcut-pd.Timedelta(days=20)]
            cal=frame[(frame.date>=calcut)&(frame.end_date<cut-pd.Timedelta(days=20))].iloc[::6]
            test=frame[(frame.date>=cut)&(frame.date<pd.Timestamp(year+1,1,1))].iloc[::6]
            counts.append(dict(asset=asset,year=year,train=len(train),cal=len(cal),test=len(test)))
            if len(train)<250 or len(cal)<30 or not len(test):continue
            assert train.end_date.max()<cal.date.min() and cal.end_date.max()<test.date.min()
            tx=train[FEATURES];cx=cal[FEATURES];qx=test[FEATURES];y=train.target/train.scale
            models={'constant':None,'ridge':make_pipeline(StandardScaler(),Ridge(alpha=30)),
                'lightgbm':LGBMRegressor(objective='quantile',alpha=.5,n_estimators=250,learning_rate=.04,max_depth=4,num_leaves=15,min_child_samples=40,random_state=20261103,n_jobs=2,verbosity=-1),
                'xgboost':XGBRegressor(objective='reg:quantileerror',quantile_alpha=.5,n_estimators=250,learning_rate=.04,max_depth=4,min_child_weight=20,random_state=20261103,n_jobs=2,tree_method='hist')}
            for name,model in models.items():
                if model is None:c=np.full(len(cal),np.median(y));m=np.full(len(test),np.median(y))
                else:model.fit(tx,y);c=model.predict(cx);m=model.predict(qx)
                ratio=np.abs(cal.target.to_numpy()/cal.scale.to_numpy()-c)
                k=float(np.quantile(ratio,min(1,np.ceil((len(cal)+1)*.9)/len(cal)),method='higher'))
                factors.append(dict(asset=asset,year=year,model=name,cal_n=len(cal),k=k,normal_k=norm.ppf(.95)))
                center=m*test.scale.to_numpy()
                for mode,mult in [('normal90',norm.ppf(.95)),('calibrated90',k)]:
                    half=mult*test.scale.to_numpy();q=np.column_stack([center-half,center,center+half])
                    result=record(test,q,name+'_'+mode,year,train,cal);result['center_model']=name;result['interval_method']=mode;result['multiplier']=mult
                    result['upper_breach']=(result.actual>result.q95).astype(float);result['residual']=result.actual-result['median']
                    rows.append(result)
            print(asset,year,len(test),flush=True)
        if rows:pd.concat(rows,ignore_index=True).to_parquet(OUT/'predictions.parquet',index=False)
    pd.DataFrame(factors).to_csv(OUT/'calibration_multipliers.csv',index=False);pd.DataFrame(counts).to_csv(OUT/'sample_counts.csv',index=False)
    import lightgbm,xgboost,sklearn
    (OUT/'environment.json').write_text(json.dumps({'python':sys.version,'lightgbm':lightgbm.__version__,'xgboost':xgboost.__version__,'sklearn':sklearn.__version__},indent=2),encoding='utf8')
    summarize(pd.concat(rows,ignore_index=True))

def summarize(r):
    scores=['mae','coverage','width','interval_score','pinball05','breach','upper_breach','miss_size','forced_width5_coverage'];summaries=[];comparisons=[]
    for scope,x in [('portfolio',r[r.asset.eq('portfolio')]),('stocks',r[~r.asset.eq('portfolio')])]:
        for period,z in [('all',x),('recent3m',x[x.date>='2026-07-30']),('loss_over5',x[x.actual < -5])]:
            for model,p in z.groupby('model'):
                row=p[scores].mean().to_dict();row.update(scope=scope,period=period,model=model,n=len(p),dates=p.date.nunique(),rmse=np.sqrt(p.sq_error.mean()));summaries.append(row)
        for mode in ['normal90','calibrated90']:
            for name in ['ridge','lightgbm','xgboost']:
                pair=x[x.model.eq(name+'_'+mode)].merge(x[x.model.eq('constant_'+mode)],on=['date','asset'],suffixes=('_a','_b'))
                for metric in ['mae','interval_score','coverage','width']:
                    d=pair.assign(delta=pair[metric+'_a']-pair[metric+'_b']).groupby('date').delta.mean().sort_index().to_numpy();n=len(d);block=min(10,n);rng=np.random.default_rng(20261103)
                    boot=[d[np.concatenate([(s+np.arange(block))%n for s in rng.integers(n,size=int(np.ceil(n/block)))])[:n]].mean() for _ in range(1000)]
                    comparisons.append(dict(scope=scope,model=name+'_'+mode,metric=metric,delta=d.mean(),ci_low=np.quantile(boot,.025),ci_high=np.quantile(boot,.975)))
    pd.DataFrame(summaries).to_csv(OUT/'metrics.csv',index=False);pd.DataFrame(comparisons).to_csv(OUT/'paired_comparisons.csv',index=False)
    groups=r.groupby(['asset','model','regime','shock_group']);scenario=groups[scores].mean();scenario['n']=groups.size();scenario['support_windows']=groups.support_windows.median();scenario.to_csv(OUT/'scenario_metrics.csv')
    fixed=r[r.interval_method.eq('normal90')];widths=fixed.groupby(['date','asset']).width.agg(['min','max']);err=(widths['max']-widths['min']).abs().max();assert err<1e-9
    for _,z in r.groupby(['date','asset','center_model']):assert z['median'].max()-z['median'].min()<1e-10
    assert np.max(abs((r.q05+r.q95)/2-r['median']))<1e-9
    old=pd.read_parquet(ROOT/'reports/gold_quantile_benchmark_20261103/predictions.parquet');p=fixed[fixed.center_model.eq('ridge')].merge(old[old.model.eq('ridge')],on=['date','asset'],suffixes=('_new','_old'))
    assert np.max(abs(p.actual_new-p.actual_old))<1e-10
    (OUT/'verification.json').write_text(json.dumps({'same_fixed_width_across_centers':True,'max_width_difference':err,'symmetric':True,'same_center_across_interval_methods':True,'same_actuals_as_previous_gold_run':True,'rows':len(r),'cloud_changes':False},indent=2),encoding='utf8')
    print(pd.DataFrame(summaries).to_string(index=False),flush=True)

if __name__=='__main__':main()
