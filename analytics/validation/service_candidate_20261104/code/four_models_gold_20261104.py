"""Four algorithms, stock-level frozen Gold samples, temporal tuning and residual risk."""
import json,hashlib,time
from concurrent.futures import ThreadPoolExecutor,as_completed
import numpy as np
import pandas as pd
from catboost import CatBoostRegressor
from lightgbm import LGBMRegressor
from xgboost import XGBRegressor
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import Ridge
from gold_quantile_benchmark import ROOT,FEATURES,SHOCKS,build
OUT=ROOT/'reports/four_models_gold_20261104'
KINDS=['catboost','xgboost','lightgbm','ridge']
SPECS=[(150,3,.04),(250,4,.04),(400,5,.03)]
def model(kind,k):
    n,d,lr=SPECS[k]
    if kind=='catboost':return CatBoostRegressor(iterations=n,depth=d,learning_rate=lr,loss_function='Quantile:alpha=0.5',random_seed=20261104,thread_count=2,verbose=False,allow_writing_files=False)
    if kind=='lightgbm':return LGBMRegressor(objective='quantile',alpha=.5,n_estimators=n,max_depth=d,num_leaves=2**d-1,learning_rate=lr,min_child_samples=30,reg_lambda=10,random_state=20261104,n_jobs=2,verbosity=-1)
    if kind=='xgboost':return XGBRegressor(objective='reg:quantileerror',quantile_alpha=.5,n_estimators=n,max_depth=d,learning_rate=lr,min_child_weight=10,reg_lambda=10,tree_method='hist',random_state=20261104,n_jobs=2)
    return make_pipeline(StandardScaler(),Ridge(alpha=[3,30,300][k]))
def score(z):
    y=z.actual;p=z.center;cr=y<=-5;nz=y!=0
    return dict(n=len(z),stocks=z.asset.nunique(),mae=float(abs(y-p).mean()),rmse=float(np.sqrt(((y-p)**2).mean())),direction=float((np.sign(y[nz])==np.sign(p[nz])).mean()),coverage80=float(((y>=z.lo)&(y<=z.hi)).mean()),width80=float((z.hi-z.lo).mean()),interval_score80=float((z.hi-z.lo+10*np.maximum(z.lo-y,0)+10*np.maximum(y-z.hi,0)).mean()),lower_breach=float((y<z.lo).mean()),var95_exceedance=float((y<z.q05).mean()),pinball05=float(np.maximum(.05*(y-z.q05),-.95*(y-z.q05)).mean()),crash_n=int(cr.sum()),crash_mae=float(abs(y[cr]-p[cr]).mean()),crash_lower_breach=float((y[cr]<z.loc[cr,'lo']).mean()),crash_shortfall=float(np.maximum(z.loc[cr,'lo']-y[cr],0).mean()),crash_center_caught=int(((p<=-5)&cr).sum()),false_crash=int(((p<=-5)&~cr).sum()),es_moment=float(((z.q05-z.es)-(z.q05-y).clip(lower=0)/.05).mean()))
def job(asset,f,year,configs,locked):
    cut=pd.Timestamp(year,1,1);tr=f[f.end_date<pd.Timestamp(year-1,1,1)-pd.Timedelta(days=20)]
    cal=f[(f.date>=pd.Timestamp(year-1,1,1))&(f.end_date<cut-pd.Timedelta(days=20))].iloc[::6]
    te=f[f.date.isin(locked.loc[(locked.asset==asset)&(locked.fold==year),'date'])] if year>=2023 else f[(f.date>=cut)&(f.date<pd.Timestamp(year+1,1,1))].iloc[::6]
    if len(tr)<250 or len(cal)<30 or te.empty:return None
    assert tr.end_date.max()<cal.date.min() and cal.end_date.max()<te.date.min()
    result=[];audits=[];scenarios=[]
    for kind,k in configs:
        m=model(kind,k).fit(tr[FEATURES].to_numpy(),tr.target/tr.scale)
        residual=cal.target/cal.scale-m.predict(cal[FEATURES].to_numpy())
        quant=np.quantile(residual,[.05,.1,.9]);tail=residual[residual<=quant[0]];es=float(tail.mean())
        center=m.predict(te[FEATURES].to_numpy());s=te.scale.to_numpy();vcut=tr.market_vol20.quantile(2/3)
        result.append(pd.DataFrame(dict(asset=asset,date=te.date.to_numpy(),fold=year,model=kind,config=k,actual=te.target.to_numpy(),center=center*s,lo=(center+quant[1])*s,hi=(center+quant[2])*s,q05=(center+quant[0])*s,es=(center+es)*s,high_vol=te.market_vol20.to_numpy()>vcut,cal_n=len(cal),es_tail_n=len(tail))))
        audits.append(dict(asset=asset,fold=year,model=kind,config=k,train_n=len(tr),cal_n=len(cal),test_n=len(te),train_label_end=str(tr.end_date.max()),cal_start=str(cal.date.min()),cal_label_end=str(cal.end_date.max()),test_start=str(te.date.min()),es_tail_n=len(tail)))
        if year==2026:
            row=te.iloc[[-1]].copy();hist=tr.iloc[::6]
            variants=[('zero',0,0,0,0),('fx2.5_rate50',2.5,50,0,0),('fx5_rate100',5,100,0,0),('fx10_rate200',10,200,0,0),('fx_only',5,0,0,0),('rate_only',0,100,0,0),('oil_only',0,0,20,0),('vix_only',0,0,0,10)]
            for name,fx,rate,oil,vix in variants:
                x=row.copy();x[SHOCKS]=[fx,rate,oil,vix];p=float(m.predict(x[FEATURES].to_numpy())[0]*x.scale.iloc[0]);support=np.ones(len(hist),dtype=bool)
                for c,tol in zip(SHOCKS,[.5,10,3,2]):support&=(hist[c]-x[c].iloc[0]).abs().le(tol).to_numpy()
                outside=[c for c in SHOCKS if not tr[c].quantile(.01)<=x[c].iloc[0]<=tr[c].quantile(.99)]
                scenarios.append(dict(asset=asset,model=kind,config=k,state_date=str(x.date.iloc[0].date()),scenario=name,fx_pct=fx,rate_bp=rate,oil_pct=oil,vix_points=vix,center=p,lo=p+quant[1]*x.scale.iloc[0],hi=p+quant[2]*x.scale.iloc[0],shock_near_disjoint_windows=int(support.sum()),outside_training_1_99=';'.join(outside),interpretation='hypothetical_unvalidated'))
    return pd.concat(result),pd.DataFrame(audits),pd.DataFrame(scenarios)
def run(data,locked,years,configs,stage):
    folder=OUT/stage;folder.mkdir(exist_ok=True);jobs=[]
    with ThreadPoolExecutor(max_workers=4) as pool:
        for asset,f in data.groupby('asset'):
            for year in years:
                stem=folder/f'{asset}_{year}'
                if stem.with_suffix('.parquet').exists():continue
                jobs.append((pool.submit(job,asset,f.sort_values('date'),year,configs,locked),stem))
        lookup=dict(jobs)
        for i,future in enumerate(as_completed(lookup),1):
            result=future.result();stem=lookup[future]
            if result:
                pred,audit,scen=result;pred.to_parquet(stem.with_suffix('.parquet'),index=False);audit.to_csv(str(stem)+'_audit.csv',index=False)
                if not scen.empty:scen.to_csv(str(stem)+'_scenarios.csv',index=False)
            (OUT/'progress.json').write_text(json.dumps(dict(stage=stage,completed=i,total=len(jobs))),encoding='utf8');print(stage,i,len(jobs),flush=True)
    return pd.concat([pd.read_parquet(p) for p in folder.glob('*.parquet')],ignore_index=True)
def main():
    OUT.mkdir(exist_ok=True);path=ROOT/'exports/seongjin_gold_v1_1/gold_stress_daily.parquet';g=pd.read_parquet(path);data=build(g);data=data[data.asset!='portfolio']
    locked=pd.read_parquet(ROOT/'reports/gold20_locked_20261104/locked_baseline.parquet')
    protocol=dict(features=FEATURES,gold_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),models=KINDS,configs=SPECS,ridge_alphas=[3,30,300],tuning='Three configurations per algorithm, global mean stock-date MAE on 2020-2021 only. Frozen before 2023-2026 evaluation. No evaluation tuning.',training='Same original annual split: prior calendar year reserved calibration, label-end embargo20 calendar days. Test stock-date keys frozen initial Gold20.',target='5-trading-day simple percentage return divided by ex-ante mixed20/60 volatility scale. Tree models median quantile objective; Ridge squared error conditional mean, explicitly different.',interval='Same separate calibration normalized residual empirical q10/q90 for every algorithm; q05 and empirical lower5% ES diagnostic. No width cap.',blind=False,limits='Research periods reused; original available_at incomplete; original Gold timeline preserved for comparability. Retrospective observed future-shock reconstruction, not causality or ex ante forecast. Thin calibration tail not ES approval.',changes='No Gold schema, Azure, production changes')
    (OUT/'protocol.json').write_text(json.dumps(protocol,indent=2),encoding='utf8')
    dev=run(data,locked,[2020,2021],[(k,c) for k in KINDS for c in range(3)],'development')
    dm=pd.DataFrame([dict(model=m,config=c,**score(z)) for (m,c),z in dev.groupby(['model','config'])]);dm.to_csv(OUT/'development_metrics.csv',index=False)
    chosen={k:int(dm[dm.model==k].sort_values(['mae','config']).iloc[0].config) for k in KINDS}
    (OUT/'frozen_configs.json').write_text(json.dumps(chosen,indent=2),encoding='utf8')
    ev=run(data,locked,[2023,2024,2025,2026],list(chosen.items()),'evaluation')
    for kind,z in ev.groupby('model'):
        assert len(z)==2928 and z.asset.nunique()==20
        q=z.merge(locked[['asset','date','actual']],on=['asset','date'],validate='one_to_one',suffixes=('','_old'));assert len(q)==2928 and np.array_equal(q.actual,q.actual_old)
    ev.to_parquet(OUT/'predictions.parquet',index=False)
    pd.DataFrame([dict(model=m,**score(z)) for m,z in ev.groupby('model')]).to_csv(OUT/'metrics.csv',index=False)
    pd.DataFrame([dict(asset=a,model=m,**score(z)) for (a,m),z in ev.groupby(['asset','model'])]).to_csv(OUT/'per_stock.csv',index=False)
    pd.DataFrame([dict(fold=y,model=m,**score(z)) for (y,m),z in ev.groupby(['fold','model'])]).to_csv(OUT/'per_year.csv',index=False)
    pd.DataFrame([dict(model=m,regime='high' if h else 'other',**score(z)) for (m,h),z in ev.groupby(['model','high_vol'])]).to_csv(OUT/'per_regime.csv',index=False)
    scen=pd.concat([pd.read_csv(p,dtype={'asset':str}) for p in (OUT/'evaluation').glob('*_scenarios.csv')]);scen.to_csv(OUT/'scenario_sensitivity.csv',index=False)
    audit=pd.concat([pd.read_csv(p,dtype={'asset':str}) for p in (OUT/'evaluation').glob('*_audit.csv')]);audit.to_csv(OUT/'fit_audit.csv',index=False)
    base=locked[['asset','date','median']].rename(columns={'median':'base'});cis=[]
    for m,z in ev.groupby('model'):
        q=z.merge(base,on=['asset','date']);q['gain']=abs(q.actual-q.base)-abs(q.actual-q.center);q['dirgain']=np.where(q.actual.ne(0),(np.sign(q.actual)==np.sign(q.center)).astype(float)-(np.sign(q.actual)==np.sign(q.base)).astype(float),np.nan)
        agg=q.groupby('date').agg(gain=('gain','sum'),n=('gain','size'),direction=('dirgain','sum'),dn=('dirgain','count')).sort_index().to_numpy();n=len(agg);rng=np.random.default_rng(20261104);samples=[]
        for _ in range(1500):
            starts=rng.integers(0,n,int(np.ceil(n/5)));idx=np.concatenate([(s+np.arange(5))%n for s in starts])[:n];v=agg[idx].sum(axis=0);samples.append([v[0]/v[1],v[2]/v[3]])
        ci=np.quantile(samples,[.025,.975],axis=0);cis.append(dict(model=m,mae_gain_lo=ci[0,0],mae_gain_hi=ci[1,0],direction_gain_lo=ci[0,1],direction_gain_hi=ci[1,1]))
    pd.DataFrame(cis).to_csv(OUT/'paired_uncertainty.csv',index=False)
    schema_path=ROOT.parent/'stresslab-team/contracts/daily/schema.json';schema=json.loads(schema_path.read_text(encoding='utf8'));(OUT/'gold_schema_snapshot.json').write_text(json.dumps(schema,ensure_ascii=False,indent=2),encoding='utf8')
    timestamps=[c for c in g if c.endswith('_available_at')];audit_schema=dict(contract_path='contracts/daily/schema.json',gold_columns=list(g.columns),gold_rows=len(g),stocks=int(g.asset_id.nunique()),missing_available_at_fraction={c:float(g[c].isna().mean()) for c in timestamps},features_all_computed_from_existing_gold=True,extra_flow_ohlc_financial_inputs_used=False,schema_changed=False)
    (OUT/'gold_input_audit.json').write_text(json.dumps(audit_schema,indent=2),encoding='utf8')
    (OUT/'progress.json').write_text(json.dumps(dict(stage='complete',stocks=20,per_model_rows=2928)),encoding='utf8');print(pd.read_csv(OUT/'metrics.csv').to_string(index=False))
if __name__=='__main__':main()
