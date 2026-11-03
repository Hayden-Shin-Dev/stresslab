"""Asset-only conditional response research. No cloud, contracts or service writes."""
import json,hashlib,sys
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import Ridge
from lightgbm import LGBMRegressor
from scipy.stats import norm
from gold_quantile_benchmark import ROOT,build,FEATURES,STATE,SHOCKS
from adaptive_residual_benchmark import weighted_q
from search_linked_benchmark import weights
OUT=ROOT/'reports/asset_feature_research_20261103'
NEW=['asset_trend60','asset_vol5','market_trend5','market_trend60','market_vol5','market_vol60','relative_market5','relative_market20','relative_market60']
EXPANDED=FEATURES+NEW
CONTEXT=['market_trend20','market_vol20','vix_level','asset_trend20','relative_market20']
INTERACTIONS=[s+'__'+c for s in SHOCKS for c in CONTEXT]
A_STATE=STATE+['market_trend5','market_trend60','market_vol5','market_vol60']

def make_data(g):
    base=build(g);base=base[base.asset!='portfolio'].copy();dates=pd.DatetimeIndex(sorted(pd.to_datetime(g.trading_date).unique()));parts=[];audit=[]
    for asset,z in g.groupby('asset_id'):
        z=z.copy();z.index=pd.to_datetime(z.trading_date);z=z.reindex(dates);p=z.close;r=p.pct_change(fill_method=None)*100;m=z.kospi_close;mr=m.pct_change(fill_method=None)*100
        x=pd.DataFrame(index=dates);x['asset']=asset;x['date']=dates;x['asset_trend60']=p.pct_change(60,fill_method=None)*100;x['asset_vol5']=r.rolling(5).std()
        for h in [5,20,60]:
            x['relative_market'+str(h)]=p.pct_change(h,fill_method=None)*100-m.pct_change(h,fill_method=None)*100
            if h!=20:x['market_trend'+str(h)]=m.pct_change(h,fill_method=None)*100;x['market_vol'+str(h)]=mr.rolling(h).std()
        parts.append(x.reset_index(drop=True))
        audit.append(dict(asset=asset,rows=len(z),max_abs_daily_return=float(r.abs().max()),daily_abs_return_over35=int((r.abs()>35).sum()),sector_available=int(z.sector_id.notna().sum())))
    d=base.merge(pd.concat(parts),on=['asset','date'],validate='one_to_one');d=d.replace([np.inf,-np.inf],np.nan).dropna(subset=EXPANDED)
    for s in SHOCKS:
        for c in CONTEXT:d[s+'__'+c]=d[s]*d[c]
    # Sector fields explicitly unavailable; not used or imputed to zero.
    d['relative_sector5']=np.nan;d['relative_sector20']=np.nan;d['relative_sector60']=np.nan
    return d,pd.DataFrame(audit)

def model(kind):
    if kind.startswith('ridge'):return make_pipeline(StandardScaler(),Ridge(alpha=30))
    return LGBMRegressor(objective='quantile',alpha=.5,n_estimators=250,learning_rate=.04,max_depth=4,num_leaves=15,min_child_samples=40,random_state=20261103,n_jobs=2,verbosity=-1)

def record(t,point,q,method,cut,cr,pool=None,w=None):
    lo,med,hi=q;y=t.target
    return dict(asset=t.asset,date=t.date,end_date=t.end_date,method=method,center=point,median=med,q10=lo,q90=hi,actual=y,
       center_mae=abs(y-point),center_sq_error=(y-point)**2,median_mae=abs(y-med),coverage=float(lo<=y<=hi),width=hi-lo,
       interval_score=hi-lo+10*(max(lo-y,0)+max(y-hi,0)),lower_breach=float(y<lo),missed_loss_pp=max(lo-y,0),
       high_vol=bool(t.market_vol20>cut),asset_crash=bool(y<=-5),market_crash=bool(cr<=-5),
       shock_group='ordinary' if abs(t.shock_fx)<=1 and abs(t.shock_rate)<=25 else 'elevated' if abs(t.shock_fx)<=3 and abs(t.shock_rate)<=75 else 'extreme',
       cal_n=0 if pool is None else len(pool),ess=0 if w is None else 1/(w@w),shock_fx=t.shock_fx,shock_rate=t.shock_rate)

def main():
    OUT.mkdir(parents=True,exist_ok=True);path=ROOT/'exports/seongjin_gold_v1_1/gold_stress_daily.parquet';g=pd.read_parquet(path)
    protocol={'primary':'asset-level center error,80% coverage,total width<=5pp,crash lower breaches','portfolio':'secondary sum of asset points; intervals only from synchronous historical residual vectors, no portfolio ML',
       'gold_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'features':EXPANDED,'interactions':INTERACTIONS,'A_state_no_shocks':A_STATE,
       'sector_limit':'all Gold sector_id null; sector relative returns unavailable, retained null in research table and excluded from training; no backfilled current classification',
       'split':'same annual2023-2026 evaluation and20day end-label embargo; prior-year sparse calibration; 5year historical OOS vintage error pool; nonoverlapping calibration/evaluation5day labels',
       'models':'fixed Ridge alpha30; LightGBM quantile250trees depth4 leaves15 lr.04; no test tuning; recent8year and feature ablations predeclared',
       'calibration':'normalized residuals from prior eligible model vintages, not in-sample residuals; frozen5year each evaluation year',
       'search_connection':'same LGBM center, compare uniform vs state distance weighted residual quantiles; kernel80% uniform20%, distance20thpercentile bandwidth',
       'blind':False,'historical_reconstruction':True,'publication_limit':'Gold availability/revision history absent; embargo does not certify point-in-time releases',
       'no_azure_changes':True,'no_contract_changes':True,'no_production_promotion':True}
    (OUT/'protocol.json').write_text(json.dumps(protocol,ensure_ascii=False,indent=2),encoding='utf8')
    d,quality=make_data(g);d.to_parquet(OUT/'learning_table.parquet',index=False);quality.to_csv(OUT/'input_quality.csv',index=False)
    market=g.groupby('trading_date').kospi_close.first().sort_index();cr=(market.shift(-5)/market-1)*100;cr.index=pd.to_datetime(cr.index)
    rows=[];ablation=[];joints=[];folds=[];coeff=[];isolation=[]
    specs={'ridge_old':FEATURES,'ridge_interactions':EXPANDED+INTERACTIONS,'lgb_expanded':EXPANDED,'lgb_recent8':EXPANDED}
    for asset,f in d.groupby('asset'):
        f=f.sort_values('date');banks={k:[] for k in specs}
        for year in range(2018,2027):
            cut=pd.Timestamp(year,1,1);cc=pd.Timestamp(year-1,1,1);tr=f[f.end_date<cc-pd.Timedelta(days=20)]
            ca=f[(f.date>=cc)&(f.end_date<cut-pd.Timedelta(days=20))].iloc[::6]
            te=f[(f.date>=cut)&(f.date<pd.Timestamp(year+1,1,1))].iloc[::6];te=te[te.end_date<pd.Timestamp(year+1,1,1)]
            if len(tr)<250 or len(ca)<30:continue
            assert tr.end_date.max()<ca.date.min()
            for z in [ca,te]:assert (z.end_date.to_numpy()[:-1]<z.date.to_numpy()[1:]).all()
            ss=StandardScaler().fit(tr[A_STATE]);high=tr.market_vol20.quantile(2/3)
            for name,features in specs.items():
                train=tr[tr.date>=cc-pd.DateOffset(years=8)] if name=='lgb_recent8' else tr
                m=model(name);m.fit(train[features],train.target/train.scale)
                cp=m.predict(ca[features])*ca.scale.to_numpy();p=ca[['date','end_date','scale']+A_STATE].copy();p['residual']=(ca.target.to_numpy()-cp)/ca.scale.to_numpy();p['ready']=p.end_date+pd.Timedelta(days=20);banks[name].append(p)
                if year<2023 or not len(te):continue
                pool=pd.concat(banks[name],ignore_index=True).sort_values('date');pool=pool[(pool.date>=cut-pd.DateOffset(years=5))&(pool.ready<cut)]
                assert (pool.ready<te.date.min()).all() and (pool.end_date.to_numpy()[:-1]<pool.date.to_numpy()[1:]).all()
                centers=m.predict(te[features])*te.scale.to_numpy();states=ss.transform(pool[A_STATE]);uniform=np.ones(len(pool))/len(pool)
                if name.startswith('ridge'):
                    for feature,c in zip(features,m[-1].coef_):coeff.append(dict(asset=asset,year=year,method=name,feature=feature,standardized_coefficient=c))
                for i,(_,t) in enumerate(te.iterrows()):
                    center=centers[i];cw,_=weights(states,ss.transform(t[A_STATE].to_frame().T)[0])
                    modes=[(name+'_residual',uniform)]+([('lgb_search_residual',cw)] if name=='lgb_expanded' else [])
                    if name=='ridge_old':rows.append(record(t,center,[center-norm.ppf(.9)*t.scale,center,center+norm.ppf(.9)*t.scale],'ridge_vol80',high,cr.get(t.date,np.nan)))
                    for label,w in modes:
                        q=center+weighted_q(pool.residual,w)*t.scale;rows.append(record(t,center,q,label,high,cr.get(t.date,np.nan),pool,w))
                        if asset in ['005930','005380']:
                            for k,(_,h) in enumerate(pool.iterrows()):joints.append(dict(asset=asset,date=t.date,method=label,residual_date=h.date,residual_end=h.end_date,center=center,scenario_return=center+h.residual*t.scale,weight=w[k],actual=t.target))
                if name=='lgb_expanded':
                    for scenario,delta in [('fx_plus1',('shock_fx',1)),('rate_plus25',('shock_rate',25)),('market_down3',('market_trend20',-3))]:
                        alt=te.copy();alt[delta[0]]+=delta[1];ap=m.predict(alt[features])*alt.scale.to_numpy()
                        for i,(_,t) in enumerate(te.iterrows()):
                            before,_=weights(states,ss.transform(te.iloc[[i]][A_STATE])[0]);after,_=weights(states,ss.transform(alt.iloc[[i]][A_STATE])[0])
                            if scenario!='market_down3':assert np.array_equal(before,after)
                            isolation.append(dict(asset=asset,date=t.date,scenario=scenario,center_change=ap[i]-centers[i],search_weight_change=abs(after-before).sum()))
                folds.append(dict(asset=asset,year=year,method=name,train_n=len(train),train_end=str(train.end_date.max()),cal_n=len(pool),test_n=len(te)))
                if name=='lgb_expanded':
                    qpred=[]
                    for alpha in [.1,.9]:
                        qm=model('lgb');qm.set_params(alpha=alpha);qm.fit(train[features],train.target/train.scale);qpred.append(qm.predict(te[features])*te.scale.to_numpy())
                    raw=np.column_stack([qpred[0],centers,qpred[1]]);qs=np.sort(raw,axis=1)
                    for i,(_,t) in enumerate(te.iterrows()):
                        v=record(t,centers[i],qs[i],'lgb_direct80',high,cr.get(t.date,np.nan));v['crossing']=bool(np.any(np.diff(raw[i])<0));rows.append(v)
            if year>=2023 and len(te):
                for label,features in [('lgb_no_shock',[c for c in EXPANDED if c not in SHOCKS]),('lgb_shock_only',SHOCKS),('ridge_expanded',EXPANDED)]:
                    m=model(label);m.fit(tr[features],tr.target/tr.scale);pred=m.predict(te[features])*te.scale.to_numpy()
                    for i,(_,t) in enumerate(te.iterrows()):ablation.append(dict(asset=asset,date=t.date,method=label,actual=t.target,center=pred[i],center_mae=abs(t.target-pred[i]),high_vol=t.market_vol20>high,asset_crash=t.target<=-5))
                print(asset,year,len(te),flush=True)
        if rows:pd.DataFrame(rows).to_parquet(OUT/'predictions.parquet',index=False)
    r=pd.DataFrame(rows);r.to_parquet(OUT/'predictions.parquet',index=False);pd.DataFrame(ablation).to_csv(OUT/'center_ablations.csv',index=False);pd.DataFrame(folds).to_csv(OUT/'folds.csv',index=False);pd.DataFrame(coeff).to_csv(OUT/'coefficients.csv',index=False);pd.DataFrame(isolation).to_csv(OUT/'isolations.csv',index=False);pd.DataFrame(joints).to_parquet(OUT/'joint_scenarios.parquet',index=False)
    old=pd.read_parquet(ROOT/'reports/adaptive_residual_20261103/predictions.parquet');old=old[(old.asset!='portfolio')&(old.model=='ridge')&(old.method=='vol80')]
    check=r[r.method=='ridge_vol80'].merge(old,on=['asset','date'],suffixes=('_a','_b'),validate='one_to_one')
    assert len(check)==len(old) and abs(check.q10_a-check.q10_b).max()<1e-7 and abs(check.q90_a-check.q90_b).max()<1e-7
    reference=set(map(tuple,r[r.method=='ridge_vol80'][['asset','date']].to_numpy()))
    for _,x in r.groupby('method'):assert set(map(tuple,x[['asset','date']].to_numpy()))==reference
    (OUT/'verification.json').write_text(json.dumps({'same_asset_date_pairs':True,'old_ridge_vol80_exactly_reproduced':True,'asset_date_count':len(reference),'no_portfolio_models_trained':True,'A_shock_invariance':True,'sector_features_excluded':True},indent=2),encoding='utf8')
if __name__=='__main__':main()
