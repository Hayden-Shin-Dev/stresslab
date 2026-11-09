"""Failure-led domestic-state diagnosis and center-only matched experiments."""
import json
from concurrent.futures import ThreadPoolExecutor,as_completed
import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.pipeline import make_pipeline
from catboost import CatBoostRegressor
from lightgbm import LGBMRegressor
from xgboost import XGBRegressor
from gold_quantile_benchmark import ROOT,FEATURES,STATE,EXTRA,SHOCKS,build
from four_models_gold_20261104 import model,KINDS
OUT=ROOT/'reports/crash_cases_center_20261104';PRIOR=ROOT/'reports/shared_improvement_20261104'
DOM=['market_return1','market_return5','market_drawdown60','market_downside20','market_acceleration','asset_return1','asset_drawdown20','relative_market5','beta60','observed_stock_down_fraction']
INTER=[s+'__'+c for s in SHOCKS for c in ['market_return5','market_drawdown60']]
COLS=FEATURES+DOM+INTER
def inputs():
    g=pd.read_parquet(ROOT/'exports/seongjin_gold_v1_1/gold_stress_daily.parquet');g['trading_date']=pd.to_datetime(g.trading_date);dates=pd.DatetimeIndex(sorted(g.trading_date.unique()))
    px=g.assign(p=g.close.where(g.quality_status.eq('valid'))).pivot(index='trading_date',columns='asset_id',values='p').sort_index();rets=px.pct_change(fill_method=None)*100
    # Preferred/common Samsung shares are not counted twice in breadth.
    cohort=[c for c in px if c!='005935'];br=rets[cohort].lt(0).sum(axis=1)/rets[cohort].notna().sum(axis=1).replace(0,np.nan)
    rows=[]
    for a,z in g.groupby('asset_id'):
        z=z.set_index('trading_date').reindex(dates);mr=z.kospi_close.pct_change(fill_method=None)*100;ar=z.close.pct_change(fill_method=None)*100
        x=pd.DataFrame(dict(asset=a,date=dates,market_return1=mr,market_return5=z.kospi_close.pct_change(5,fill_method=None)*100,market_drawdown60=(z.kospi_close/z.kospi_close.rolling(60).max()-1)*100,market_downside20=np.sqrt(mr.clip(upper=0).pow(2).rolling(20).mean()),market_acceleration=z.kospi_close.pct_change(5,fill_method=None)*100-z.kospi_close.pct_change(20,fill_method=None)*25,asset_return1=ar,asset_drawdown20=(z.close/z.close.rolling(20).max()-1)*100,relative_market5=z.close.pct_change(5,fill_method=None)*100-z.kospi_close.pct_change(5,fill_method=None)*100,beta60=ar.rolling(60).cov(mr)/mr.rolling(60).var().replace(0,np.nan),observed_stock_down_fraction=br.reindex(dates),oil_valid=z.wti.gt(0)&z.wti.shift(-5).gt(0),diagnostic_only_future_market5=(z.kospi_close.shift(-5)/z.kospi_close-1)*100,start_close=z.close,end_close=z.close.shift(-5)))
        rows.append(x.reset_index(drop=True))
    d=build(g);d=d[d.asset!='portfolio'].merge(pd.concat(rows),on=['asset','date'],validate='one_to_one')
    for s in SHOCKS:
        for c in ['market_return5','market_drawdown60']:d[s+'__'+c]=d[s]*d[c]
    assert 'diagnostic_only_future_market5' not in COLS and len(d)==100871
    return d.replace([np.inf,-np.inf],np.nan)
def metrics(z):
    y=z.actual;p=z.center;cr=y<=-5;up=y>=5;nz=y!=0
    return dict(n=len(z),stocks=z.asset.nunique(),mae=float(abs(y-p).mean()),rmse=float(np.sqrt(((y-p)**2).mean())),direction=float((np.sign(y[nz])==np.sign(p[nz])).mean()),crash_n=int(cr.sum()),crash_mae=float(abs(y[cr]-p[cr]).mean()),crash_actual_mean=float(y[cr].mean()),crash_center_mean=float(p[cr].mean()),crash_wrong_sign=float(p[cr].ge(0).mean()),crash_caught=int((p[cr]<=-5).sum()),false_crash=int(((p<=-5)&~cr).sum()),surge_mae=float(abs(y[up]-p[up]).mean()))
def diagnose(d):
    r=pd.read_parquet(PRIOR/'predictions.parquet');r=r[(r.policy=='refresh')&(r.model=='catboost')].merge(d,on=['asset','date'],validate='one_to_one');r['center_error']=r.center-r.actual
    crash=r[r.actual<=-5];cases=crash.sort_values('center_error',ascending=False).groupby('asset',sort=False).head(1).copy();cases.to_csv(OUT/'worst_crash_by_stock.csv',index=False)
    pd.DataFrame([dict(asset=a,**metrics(z)) for a,z in r.groupby('asset')]).to_csv(OUT/'baseline_per_stock.csv',index=False)
    crash.groupby('date').agg(stocks=('asset','size'),mean_center_error=('center_error','mean'),actual_market5=('diagnostic_only_future_market5','first'),prior_market5=('market_return5','first'),fx=('shock_fx','first'),vix=('shock_vix','first')).sort_values('mean_center_error',ascending=False).to_csv(OUT/'shared_failure_dates.csv')
    neighbors=[];summary=[]
    for _,case in cases.iterrows():
        tr=d[(d.asset==case.asset)&(d.end_date<pd.Timestamp(case.fold,1,1)-pd.Timedelta(days=20))&d.oil_valid].sort_values('date').iloc[::6]
        state=STATE+EXTRA;median=tr[state].median();scale=(tr[state].quantile(.75)-tr[state].quantile(.25)).replace(0,1)
        dist=((tr[state]-case[state].astype(float))/scale).pow(2).mean(axis=1);pool=tr.loc[dist.nsmallest(100).index].copy()
        shockscale=(tr[SHOCKS].quantile(.75)-tr[SHOCKS].quantile(.25)).replace(0,1);pool['shock_distance']=((pool[SHOCKS]-case[SHOCKS].astype(float))/shockscale).pow(2).mean(axis=1)
        chosen=pool.nsmallest(20,'shock_distance');near=chosen.target
        summary.append(dict(asset=case.asset,date=case.date,actual=case.actual,center=case.center,prior_market5=case.market_return5,future_market5_diagnostic=case.diagnostic_only_future_market5,neighbor_n=len(chosen),neighbor_crash_fraction=float((near<=-5).mean()),neighbor_median=float(near.median()),neighbor_mean=float(near.mean()),neighbor_min=float(near.min()),neighbor_max=float(near.max()),neighbor_market5_median=float(chosen.market_return5.median())))
        for _,n in chosen.iterrows():neighbors.append(dict(asset=case.asset,case_date=case.date,historical_date=n.date,historical_end=n.end_date,historical_return=n.target,shock_distance=n.shock_distance,market_return5=n.market_return5,**{c:n[c] for c in SHOCKS}))
    pd.DataFrame(summary).to_csv(OUT/'case_support_summary.csv',index=False);pd.DataFrame(neighbors).to_csv(OUT/'case_neighbors.csv',index=False)
    diag=r[['center_error','diagnostic_only_future_market5']].corr().iloc[0,1]
    (OUT/'diagnostic_summary.json').write_text(json.dumps(dict(crash_rows=len(crash),crash_distinct_start_dates=crash.date.nunique(),stocks=cases.asset.nunique(),error_vs_future_market_correlation=diag,future_market_used_as_model_feature=False,warning='Correlation and selected neighbors are diagnostics, not independent causal effects. Historical universe survivorship and missing publication times remain.'),indent=2))
def estimator(kind,objective,config):
    if objective=='median' or kind=='ridge':return model(kind,config)
    if kind=='catboost':return CatBoostRegressor(iterations=150,depth=3,learning_rate=.04,loss_function='RMSE',random_seed=20261104,thread_count=2,verbose=False,allow_writing_files=False)
    if kind=='lightgbm':return LGBMRegressor(objective='regression',n_estimators=150,max_depth=3,num_leaves=7,learning_rate=.04,min_child_samples=30,reg_lambda=10,random_state=20261104,n_jobs=2,verbosity=-1)
    return XGBRegressor(objective='reg:squarederror',n_estimators=150,max_depth=3,learning_rate=.04,min_child_weight=10,reg_lambda=10,tree_method='hist',random_state=20261104,n_jobs=2)
def job(asset,f,base,config):
    path=OUT/'checkpoints'/f'{asset}.parquet'
    if path.exists():return
    rows=[];audit=[]
    for year in [2020,2021,2023,2024,2025,2026]:
        tr=f[(f.end_date<pd.Timestamp(year,1,1)-pd.Timedelta(days=20))&f.oil_valid];ref=base[(base.asset==asset)&(base.fold==year)];te=f[f.date.isin(ref.date.unique())].sort_values('date')
        if te.empty:continue
        assert len(tr)>=250 and tr.end_date.max()<te.date.min()
        for kind in KINDS:
            for policy,cols,obj in [('domestic',COLS,'median'),('domestic_mean',COLS,'mean')]:
                m=make_pipeline(SimpleImputer(strategy='median'),estimator(kind,obj,config[kind]));m.fit(tr[cols].to_numpy(),tr.target/tr.scale);p=m.predict(te[cols].to_numpy())*te.scale.to_numpy()
                rows.append(pd.DataFrame(dict(asset=asset,date=te.date.to_numpy(),fold=year,model=kind,policy=policy,actual=te.target.to_numpy(),center=p)))
                audit.append(dict(asset=asset,fold=year,model=kind,policy=policy,train_n=len(tr),test_n=len(te),train_label_end=str(tr.end_date.max()),test_start=str(te.date.min()),feature_count=len(cols),future_market_input=False))
    pd.concat(rows).to_parquet(path,index=False);pd.DataFrame(audit).to_csv(path.with_suffix('.csv'),index=False)
def main():
    OUT.mkdir(exist_ok=True);(OUT/'checkpoints').mkdir(exist_ok=True);d=inputs();diagnose(d)
    config=json.loads((ROOT/'reports/four_models_gold_20261104/frozen_configs.json').read_text());b=pd.read_parquet(PRIOR/'predictions.parquet');b=b[b.policy=='refresh'].copy();bd=pd.read_parquet(PRIOR/'development_predictions.parquet');bd=bd[bd.policy=='refresh'].copy();base=pd.concat([b,bd]);base['policy']='baseline'
    protocol=dict(features=COLS,source='Existing Gold34 only, no contract change',new_features=DOM,interactions=INTER,objective='Center-only, no prediction interval or width adjustment. Mean experiment symmetric squared loss, no crash oversampling or imposed negative response.',selection='2020/2021: crash MAE improves>=5%, total MAE no worse, direction no worse, false crash <= baseline+2. Lowest crash MAE, otherwise baseline. Independent rule per algorithm, all stocks included.',blind=False,diagnostic_future_market_not_used=True,training='same annual refresh split, label-end embargo20 calendar days',limitations='Failure-led design uses previously researched evaluation; not blind. Gold publication times missing. Breadth from observed common-stock cohort only, not whole KOSPI.')
    (OUT/'protocol.json').write_text(json.dumps(protocol,indent=2))
    with ThreadPoolExecutor(max_workers=4) as pool:
        fs=[pool.submit(job,a,f,base,config) for a,f in d.groupby('asset')]
        for i,f in enumerate(as_completed(fs),1):f.result();print('stocks',i,20,flush=True);(OUT/'progress.json').write_text(json.dumps(dict(stage='training',completed=i,total=20)))
    r=pd.concat([pd.read_parquet(p) for p in (OUT/'checkpoints').glob('*.parquet')]);r=pd.concat([r,base[['asset','date','fold','model','policy','actual','center']]],ignore_index=True)
    dev=r[r.fold<2023];ev=r[r.fold>=2023];selected={}
    for kind in KINDS:
        z=dev[dev.model==kind];bm=metrics(z[z.policy=='baseline']);eligible=[]
        for p in ['domestic','domestic_mean']:
            s=metrics(z[z.policy==p])
            if s['crash_mae']<=bm['crash_mae']*.95 and s['mae']<=bm['mae'] and s['direction']>=bm['direction'] and s['false_crash']<=bm['false_crash']+2:eligible.append((s['crash_mae'],p))
        selected[kind]=min(eligible)[1] if eligible else 'baseline'
    (OUT/'development_selection.json').write_text(json.dumps(selected,indent=2))
    for (kind,p),z in ev.groupby(['model','policy']):
        baseline=ev[(ev.model==kind)&(ev.policy=='baseline')];q=z.merge(baseline[['asset','date','actual']],on=['asset','date'],suffixes=('','_baseline'),validate='one_to_one');assert len(q)==2928 and np.array_equal(q.actual,q.actual_baseline)
    ev.to_parquet(OUT/'predictions.parquet',index=False);dev.to_parquet(OUT/'development_predictions.parquet',index=False)
    for name,frame in [('metrics',ev),('development_metrics',dev)]:pd.DataFrame([dict(model=k,policy=p,**metrics(z)) for (k,p),z in frame.groupby(['model','policy'])]).to_csv(OUT/f'{name}.csv',index=False)
    pd.DataFrame([dict(asset=a,model=k,policy=p,**metrics(z)) for (a,k,p),z in ev.groupby(['asset','model','policy'])]).to_csv(OUT/'per_stock.csv',index=False)
    pd.DataFrame([dict(fold=y,model=k,policy=p,**metrics(z)) for (y,k,p),z in ev.groupby(['fold','model','policy'])]).to_csv(OUT/'per_year.csv',index=False)
    pd.concat([pd.read_csv(p,dtype={'asset':str}) for p in (OUT/'checkpoints').glob('*.csv')]).to_csv(OUT/'fit_audit.csv',index=False)
    (OUT/'progress.json').write_text(json.dumps(dict(stage='complete',selected=selected)));print(pd.read_csv(OUT/'metrics.csv').to_string(index=False))
if __name__=='__main__':main()
