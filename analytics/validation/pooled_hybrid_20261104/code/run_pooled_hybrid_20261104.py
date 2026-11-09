"""Frozen local research, no provider/API/cloud mutation."""
import json,hashlib,datetime,os
import joblib
import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits
from catboost import CatBoostRegressor
from lightgbm import LGBMRegressor
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
from pooled_stress_core_20261104 import *
from four_models_gold_20261104 import model as individual_model

OLD=ROOT/'reports/four_models_gold_20261104'
MODELS=['ridge','lightgbm','catboost','partial_ridge','hybrid_catboost','hybrid_lightgbm']
TREECOLS=FEATURES+[f'id_{a}' for a in ASSETS]

def tree_x(d):return np.column_stack([d[FEATURES].to_numpy(),np.eye(len(ASSETS))[[ASSETS.index(a) for a in d.asset]]])
def progress(stage,**kw):
    (OUT/'progress.json').write_text(json.dumps(dict(stage=stage,**kw)));print(stage,kw,flush=True)

def reproduce():
    r=pd.read_parquet(OLD/'predictions.parquet');z=r[r.model=='catboost'];audit=pd.read_csv(OLD/'fit_audit.csv')
    s=point_score(z);s.update(interval_score(z));s.update(cal_min=int(audit.cal_n.min()),cal_max=int(audit.cal_n.max()),source='four_models_gold_20261104 (original split; not latest refresh)')
    scenarios=pd.read_csv(OLD/'scenario_sensitivity.csv',dtype={'asset':str});p=scenarios.pivot(index=['asset','model'],columns='scenario',values='center')
    p['saturated_2_5_to_10']=(p['fx2.5_rate50']-p.fx10_rate200).abs()<1e-10;p.reset_index().to_csv(OUT/'legacy_saturation.csv',index=False)
    s['saturation_count']=p.groupby('model').saturated_2_5_to_10.sum().astype(int).to_dict()
    (OUT/'legacy_reproduction.json').write_text(json.dumps(s,indent=2));return r

def oof_factor(d):
    folder=OUT/'factor_cache';folder.mkdir(exist_ok=True)
    for origin in range(2005,2026):
        path=folder/f'{origin}.joblib'
        if path.exists():continue
        m,tr,tune=fit_factor(d,origin)
        q=d[(d.date>=pd.Timestamp(origin,1,1))&(d.date<pd.Timestamp(origin+1,1,1))&d.oil_valid].copy()
        q['factor_oof']=m.predict(q);q['residual_oof']=q.target/q.scale-q.factor_oof
        q['oof_train_label_end']=tr.end_date.max()
        assert (q.date>q.oof_train_label_end).all()
        q.to_parquet(folder/f'{origin}.parquet',index=False)
        pd.DataFrame(tune).to_csv(folder/f'{origin}_tuning.csv',index=False)
        joblib.dump(m,path);progress('factor_crossfit',year=origin)
    return pd.concat([pd.read_parquet(p) for p in folder.glob('*.parquet')],ignore_index=True)

def run_fold(d,oof,year,keys):
    folder=OUT/'folds';folder.mkdir(exist_ok=True);dest=folder/f'{year}_points.parquet'
    if dest.exists():return
    origin=year-1;cut=pd.Timestamp(origin,1,1)-pd.Timedelta(days=20)
    tr=d[(d.end_date<cut)&d.oil_valid].copy()
    cal=chronological_anchors(d[(d.date>=pd.Timestamp(origin,1,1))&(d.end_date<pd.Timestamp(year,1,1)-pd.Timedelta(days=20))&d.oil_valid])
    te=d.merge(keys[keys.fold==year][['asset','date']],on=['asset','date'],validate='one_to_one')
    use=sorted(te.asset.unique());cal=cal[cal.asset.isin(use)];tr=tr[tr.asset.isin(use)]
    assert tr.end_date.max()<cal.date.min() and cal.end_date.max()<te.date.min()
    # Factor pool includes eligible historical assets; common information sharing is intentional.
    lin=joblib.load(OUT/'factor_cache'/f'{origin}.joblib')
    residual=oof[(oof.end_date<cut)&oof.asset.isin(use)].copy()
    assert (residual.oof_train_label_end<residual.date).all() and residual.end_date.max()<cal.date.min()
    support=JointSupport().fit(tr)
    trees={
      'hybrid_catboost':CatBoostRegressor(iterations=150,depth=3,learning_rate=.04,loss_function='Quantile:alpha=0.5',thread_count=2,verbose=False,allow_writing_files=False,random_seed=SEED),
      'hybrid_lightgbm':LGBMRegressor(objective='quantile',alpha=.5,n_estimators=150,max_depth=3,num_leaves=7,learning_rate=.04,min_child_samples=30,reg_lambda=10,n_jobs=2,verbosity=-1,random_state=SEED)}
    for tree in trees.values():tree.fit(tree_x(residual),residual.residual_oof,sample_weight=weights(residual))
    # HAR-style daily squared-return proxy, not intraday realized variance.
    har=make_pipeline(StandardScaler(),Ridge(alpha=30)).fit(tree_x_har(tr),tr.future_log_rv5,ridge__sample_weight=weights(tr))
    scale_bounds=np.quantile(np.exp(tr.future_log_rv5/2),[.01,.99])
    fitted={};configs=json.loads((OLD/'frozen_configs.json').read_text())
    for a in use:
        f=tr[tr.asset==a];fitted[a]={k:individual_model(k,configs[k]).fit(f[FEATURES].to_numpy(),f.target/f.scale) for k in ['ridge','lightgbm','catboost']}
    vcut=tr.drop_duplicates('date').market_vol20.quantile([1/3,2/3]).to_numpy()
    out={};audits=[]
    for split,frame in [('cal',cal),('test',te)]:
        gate,ratio,outside=support.inspect(frame);factor=lin.predict(frame)*frame.scale.to_numpy()
        hs=np.clip(np.exp(har.predict(tree_x_har(frame))/2),*scale_bounds)
        regime=np.select([frame.market_vol20<=vcut[0],frame.market_vol20<=vcut[1]],['low','medium'],default='high')
        pieces=[]
        for name in MODELS:
            if name=='partial_ridge':center=factor;cor=np.zeros(len(frame))
            elif name in trees:
                cor=trees[name].predict(tree_x(frame))*frame.scale.to_numpy()*gate;center=factor+cor
            else:
                center=np.zeros(len(frame))
                for a in use:
                    mask=(frame.asset==a).to_numpy();center[mask]=fitted[a][name].predict(frame.loc[mask,FEATURES].to_numpy())*frame.loc[mask,'scale'].to_numpy()
                cor=np.zeros(len(frame))
            z=frame[['asset','date','end_date','sector','scale','target']].rename(columns={'target':'actual'}).copy()
            z['fold']=year;z['model']=name;z['center']=center;z['factor_center']=factor if name.startswith(('partial','hybrid')) else np.nan;z['residual_correction']=cor;z['har_scale']=hs;z['regime']=regime;z['support_ratio']=ratio;z['residual_gate']=gate;z['outside_marginal']=outside
            pieces.append(z)
        out[split]=pd.concat(pieces,ignore_index=True)
    bounds=[]
    for name,z in out['test'].groupby('model'):
        c=out['cal'][out['cal'].model==name].copy();c['rn']=(c.actual-c.center)/c.scale;c['rh']=(c.actual-c.center)/c.har_scale
        for method in ['asset','pooled','sector','regime','har_proxy']:
            rows=[]
            for _,t in z.iterrows():
                pool=c;fallback=False
                if method=='asset':pool=c[c.asset==t.asset]
                if method=='sector':
                    pool=c[c.sector==t.sector]
                    if pool.asset.nunique()<2:pool=c;fallback=True
                if method=='regime':
                    pool=c[c.regime==t.regime]
                    if pool.date.nunique()<20:pool=c;fallback=True
                res=pool.rh if method=='har_proxy' else pool.rn;s=t.har_scale if method=='har_proxy' else t.scale
                q=np.quantile(res,[.1,.9]);row=t.to_dict();row.update(interval=method,lo=t.center+q[0]*s,hi=t.center+q[1]*s,cal_rows=len(pool),cal_dates=pool.date.nunique(),pool_fallback=fallback);rows.append(row)
            bounds.append(pd.DataFrame(rows))
    # Unconditional distribution: identical training cutoff, asset history, nonoverlapping anchors.
    un=[]
    for a,f in te.groupby('asset'):
        h=chronological_anchors(tr[tr.asset==a]);q=np.quantile(h.target,[.1,.9]);z=f[['asset','date','sector','target']].rename(columns={'target':'actual'}).copy();z['fold']=year;z['model']='unconditional';z['interval']='historical';z['center']=float(h.target.median());z['lo']=q[0];z['hi']=q[1];un.append(z)
    pd.concat(bounds+un,ignore_index=True).to_parquet(folder/f'{year}_intervals.parquet',index=False)
    out['cal'].to_parquet(folder/f'{year}_calibration.parquet',index=False)
    # Explicit scenario inputs; zero is change=0, never a level replacement.
    scenario=[];slope=[]
    for a,f in te.groupby('asset'):
        row=f.iloc[[-1]].copy()
        for shock in SHOCKS:
            slope.extend([dict(fold=year,**v) for v in lin.slopes(row) if v['shock']==shock])
        variants=[('zero',0,0,0,0),('moderate',2.5,50,0,0),('large',5,100,0,0),('extreme',10,200,0,0),('fx_only',5,0,0,0),('rate_only',0,100,0,0),('oil_only',0,0,20,0),('vix_only',0,0,0,10)]
        for label,fx,rate,oil,vix in variants:
            x=row.copy();x[SHOCKS]=[fx,rate,oil,vix]
            for s in SHOCKS:
                for c in ['market_trend20','market_vol20']:x[s+'__'+c]=x[s]*x[c]
            gate,dist,ext=support.inspect(x);p=float(lin.predict(x)[0]*x.scale.iloc[0])
            for name in MODELS:
                correction=0.
                if name in trees:correction=float(trees[name].predict(tree_x(x))[0]*x.scale.iloc[0]*gate[0]);value=p+correction
                elif name=='partial_ridge':value=p
                else:value=float(fitted[a][name].predict(x[FEATURES].to_numpy())[0]*x.scale.iloc[0])
                scenario.append(dict(asset=a,fold=year,state_date=str(x.date.iloc[0].date()),model=name,scenario=label,fx_pct=fx,rate_bp=rate,oil_pct=oil,vix_change_points=vix,center=value,factor_center=p if name.startswith(('partial','hybrid')) else np.nan,residual_correction=correction,support_ratio=float(dist[0]),residual_gate=float(gate[0]),outside_marginal=bool(ext[0]),validated_extreme=False))
    pd.DataFrame(scenario).to_csv(folder/f'{year}_scenarios.csv',index=False);pd.DataFrame(slope).to_csv(folder/f'{year}_slopes.csv',index=False)
    audits.append(dict(fold=year,train_rows=len(tr),train_dates=tr.date.nunique(),train_label_end=str(tr.end_date.max()),cal_start=str(cal.date.min()),cal_label_end=str(cal.end_date.max()),test_start=str(te.date.min()),residual_oof_rows=len(residual),residual_oof_dates=residual.date.nunique(),residual_label_end=str(residual.end_date.max()),joint_support_threshold=support.threshold,har_proxy=True))
    pd.DataFrame(audits).to_csv(folder/f'{year}_audit.csv',index=False)
    joblib.dump(dict(linear=lin,trees=trees,support=support,individual=fitted,har=har,har_bounds=scale_bounds),folder/f'{year}_models.joblib')
    out['test'].to_parquet(dest,index=False);progress('fold_complete',year=year,rows=len(te))

def tree_x_har(d):return np.column_stack([d[HAR].to_numpy(),np.eye(len(ASSETS))[[ASSETS.index(a) for a in d.asset]]])

def main():
    OUT.mkdir(exist_ok=True);legacy=reproduce();d,g=prepare()
    protocol=dict(version='pooled_hybrid_v1_20261104',gold_sha256=hashlib.sha256((ROOT/'exports/seongjin_gold_v1_1/gold_stress_daily.parquet').read_bytes()).hexdigest(),contract_changed=False,azure_changed=False,models=MODELS,features=FEATURES,factor_interactions=INTER,partial_pooling='common standardized factors + penalized asset intercept and asset x 4 standardized shock deviations; penalty ratio10/100; alpha300/3000',tuning='Each factor origin: previous year temporal inner validation with20day label embargo; no outer cal/test tuning. Trees fixed150depth3lr.04. Variant selection only2020/21 development.',training='Daily overlapping5day targets. Outer previous year strictly reserved calibration;20calendar-day label embargo. Identical locked stock/date evaluation keys.',residual_training='Annual forward-only OOF linear errors, outcomes finish before outer training cutoff. No in-sample linear residual targets.',support='12dim state+shock IQR scaled neighbor distance, historical anchors6days, threshold95% of historical neighbor distances excluding20day-near points; taper residual weight1->0 from ratio1->2. This is heuristic support, not probability.',intervals=['asset','pooled','sector (>=2 stocks else pooled)','market-vol regime (>=20 dates else pooled)','HAR-style daily squared-return proxy with1/5/22 horizons (not intraday HAR-RV)'],evaluation='historical observed future shocks as conditions; not causal or ex-ante shock prediction; reused research evaluation not blind',acceptance='relative centerMAE vszero and CatBoost; pinball/intervalscore vsunconditional; crash breaches and stockheterogeneity guards. No5pp cap.',limitations='Missing available_at, no historical revision vintages, current20 survivorship. Rows across stocks not independent. No airline/refinery in current20.',sectors=SECTORS)
    (OUT/'protocol.json').write_text(json.dumps(protocol,indent=2))
    (OUT/'lockbox.json').write_text(json.dumps(dict(status='reserved_not_yet_evaluated',first_eligible_state_date='2026-11-05',rule='Only not-previously-inspected data after frozen protocol; wait5tradingdays for each label; preserve raw arrival and revision timestamps. No hyperparameter selection on lockbox.',model_promotion=False,requires_point_in_time_ingestion=True),indent=2))
    keys=legacy[legacy.model=='catboost'][['asset','date','fold']]
    dev=pd.concat([pd.read_parquet(p) for p in (OLD/'development').glob('*.parquet')]);dev=dev[(dev.model=='catboost')&(dev.config==0)][['asset','date','fold']];keys=pd.concat([keys,dev]).drop_duplicates()
    oof=oof_factor(d)
    for year in [2020,2021,2023,2024,2025,2026]:run_fold(d,oof,year,keys)
    progress('training_complete')

if __name__=='__main__':
    with threadpool_limits(limits=2):main()
