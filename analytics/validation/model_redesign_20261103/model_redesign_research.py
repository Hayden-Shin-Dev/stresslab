"""Per-asset vs pooled and partially pooled stress ML; research only."""
import json,hashlib
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler
from sklearn.cluster import KMeans
from lightgbm import LGBMRegressor
from asset_feature_research import ROOT,make_data,model,FEATURES,EXPANDED,SHOCKS,A_STATE,record
from adaptive_residual_benchmark import weighted_q
from search_linked_benchmark import weights
OUT=ROOT/'reports/model_redesign_20261103'
LOCAL_STATE=['asset_trend20','asset_vol20','relative_market20']
SCENARIOS={'zero':{},'oil+10':{'shock_oil':10},'oil+20':{'shock_oil':20},'oil-10':{'shock_oil':-10},'fx+3':{'shock_fx':3},'fx+5':{'shock_fx':5},'fx-3':{'shock_fx':-3},'rate+25':{'shock_rate':25},'rate+50':{'shock_rate':50},'rate+100':{'shock_rate':100},'vix+5':{'shock_vix':5},'vix+10':{'shock_vix':10},'fx5_rate100':{'shock_fx':5,'shock_rate':100}}

def pooled_x(x,categories):
    v=x[EXPANDED].copy();v['asset_id']=pd.Categorical(x.asset,categories=categories);return v

def learner(alpha=.5):
    return LGBMRegressor(objective='quantile',alpha=alpha,n_estimators=250,learning_rate=.04,max_depth=4,num_leaves=15,min_child_samples=40,random_state=20261103,n_jobs=2,verbosity=-1)

class PartialPool:
    def __init__(self,categories):self.categories=list(categories)
    def design(self,x):
        v=self.scaler.transform(x[EXPANDED]);ids=pd.Categorical(x.asset,categories=self.categories).codes
        assert (ids>=0).all()
        one=np.eye(len(self.categories))[ids];shock=v[:,[EXPANDED.index(s) for s in SHOCKS]]
        return np.column_stack([np.ones(len(x)),v,one,(one[:,:,None]*shock[:,None,:]).reshape(len(x),-1)])
    def fit(self,x,y,w):
        self.scaler=StandardScaler().fit(x[EXPANDED]);v=self.design(x);penalty=np.r_[0,np.full(len(EXPANDED),30.),np.full(len(self.categories)*5,300.)]
        self.coef=np.linalg.solve(v.T@(v*w[:,None])+np.diag(penalty),v.T@(np.asarray(y)*w));return self
    def predict(self,x):return self.design(x)@self.coef

def date_weights(x):
    w=1/x.groupby('date').date.transform('size').to_numpy();return w/w.mean()

def main():
    OUT.mkdir(parents=True,exist_ok=True);gold_path=ROOT/'exports/seongjin_gold_v1_1/gold_stress_daily.parquet';g=pd.read_parquet(gold_path)
    d,_=make_data(g);infer,_=make_data(g,require_outcome=False);cats=sorted(d.asset.unique());d.to_parquet(OUT/'learning_table.parquet',index=False)
    protocol={'gold_hash':hashlib.sha256(gold_path.read_bytes()).hexdigest(),'purpose':'asset-independent vs pooled categorical LGBM vs shared effects plus asset intercept and shock-slope deviations',
      'pooled_features':EXPANDED+['asset_id'],'sector':'absent from Gold; not fabricated or trained','partial_penalties':{'global':30,'asset_deviations':300},'row_weights':'inverse stocks per date, normalized to mean1; avoid treating same-date macro shocks as independent new events',
      'A_methods':['market standardized distance','KMeans4 trained on unique training dates','market plus local asset state distance'],'A_no_user_shocks':True,
      'B_paths':['no A adjustment','evidence only identical output','distance-weighted residual','cluster-weighted residual','asset-state-weighted residual'],
      'split':'same2023-2026 dates and asset samples; annual train before prior calibration year with20day label embargo;5year OOS vintage residuals',
      'calibration_limit':'historical vintage errors; not one fixed model with a single disjoint5year calibration interval',
      'model_settings':'LGBM250trees depth4 leaves15 lr.04 same as independent comparator; no test tuning; categories fixed identity, no target encoding',
      'sensitivity':'2026 frozen training boundary, same snapshot2026-10-30, full vs recent8years; input perturbation not causal validation',
      'goal':'asset5day mean width<=5pp,coverage>=80%,preserve lower-tail capture','blind':False,'cloud_changes':False,'contract_changes':False}
    (OUT/'protocol.json').write_text(json.dumps(protocol,ensure_ascii=False,indent=2),encoding='utf8')
    market=g.groupby('trading_date').kospi_close.first().sort_index();cr=(market.shift(-5)/market-1)*100;cr.index=pd.to_datetime(cr.index)
    banks={'pooled':{},'partial':{}};rows=[];audit=[];search_audit=[];models_2026=None
    for year in range(2018,2027):
        cut=pd.Timestamp(year,1,1);cc=pd.Timestamp(year-1,1,1);train=[];cal=[];test=[];train_by={}
        for asset,f in d.groupby('asset'):
            f=f.sort_values('date');tr=f[f.end_date<cc-pd.Timedelta(days=20)];ca=f[(f.date>=cc)&(f.end_date<cut-pd.Timedelta(days=20))].iloc[::6]
            te=f[(f.date>=cut)&(f.date<pd.Timestamp(year+1,1,1))].iloc[::6];te=te[te.end_date<pd.Timestamp(year+1,1,1)]
            if len(tr)<250 or len(ca)<30:continue
            assert tr.end_date.max()<ca.date.min()
            for z in [ca,te]:assert (z.end_date.to_numpy()[:-1]<z.date.to_numpy()[1:]).all()
            train.append(tr);cal.append(ca);test.append(te);train_by[asset]=tr
        tr=pd.concat(train,ignore_index=True);ca=pd.concat(cal,ignore_index=True);te=pd.concat(test,ignore_index=True);w=date_weights(tr)
        pm=learner().fit(pooled_x(tr,cats),tr.target/tr.scale,sample_weight=w);hm=PartialPool(cats).fit(tr,tr.target/tr.scale,w)
        common=tr.drop_duplicates('date');ss=StandardScaler().fit(common[A_STATE]);km=KMeans(n_clusters=4,n_init=10,random_state=20261103).fit(ss.transform(common[A_STATE]));local_scaler=StandardScaler().fit(tr[A_STATE+LOCAL_STATE])
        if year>=2023:
            qp=[learner(alpha).fit(pooled_x(tr,cats),tr.target/tr.scale,sample_weight=w) for alpha in [.1,.9]]
        for name,m in [('pooled',pm),('partial',hm)]:
            cp=m.predict(pooled_x(ca,cats) if name=='pooled' else ca)*ca.scale.to_numpy()
            c=ca[['asset','date','end_date','scale']+A_STATE+LOCAL_STATE].copy();c['residual']=(ca.target.to_numpy()-cp)/ca.scale.to_numpy();c['ready']=ca.end_date+pd.Timedelta(days=20)
            for asset,z in c.groupby('asset'):banks[name].setdefault(asset,[]).append(z)
            if year<2023:continue
            centers=m.predict(pooled_x(te,cats) if name=='pooled' else te)*te.scale.to_numpy()
            if name=='pooled':direct=np.column_stack([qp[0].predict(pooled_x(te,cats))*te.scale.to_numpy(),centers,qp[1].predict(pooled_x(te,cats))*te.scale.to_numpy()])
            for asset,idx in te.groupby('asset').groups.items():
                pool=pd.concat(banks[name][asset],ignore_index=True).sort_values('date');pool=pool[(pool.date>=cut-pd.DateOffset(years=5))&(pool.ready<cut)]
                assert (pool.end_date.to_numpy()[:-1]<pool.date.to_numpy()[1:]).all() and (pool.ready<cut).all()
                ps=ss.transform(pool[A_STATE]);ls=local_scaler.transform(pool[A_STATE+LOCAL_STATE]);clusters=km.predict(ps);high=train_by[asset].market_vol20.quantile(2/3)
                for i in idx:
                    t=te.loc[i];center=centers[i];uniform=np.ones(len(pool))/len(pool);state=ss.transform(te.loc[[i],A_STATE])[0];dw,dist=weights(ps,state)
                    group=clusters==km.predict(state.reshape(1,-1))[0];fallback=group.sum()<30;cw=uniform if fallback else .2*uniform+.8*group/group.sum()
                    aw,_=weights(ls,local_scaler.transform(te.loc[[i],A_STATE+LOCAL_STATE])[0])
                    modes=[(name+'_residual',uniform)]
                    if name=='pooled':modes += [('pooled_evidence_only',uniform),('pooled_search_residual',dw),('pooled_cluster_residual',cw),('pooled_asset_search_residual',aw)]
                    for label,rw in modes:
                        q=center+weighted_q(pool.residual,rw)*t.scale;v=record(t,center,q,label,high,cr.get(t.date,np.nan),pool,rw);v['cluster_fallback']=fallback if 'cluster' in label else False;rows.append(v)
                    if name=='pooled':
                        q=np.sort(direct[i]);v=record(t,center,q,'pooled_direct80',high,cr.get(t.date,np.nan));v['crossing']=bool(np.any(np.diff(direct[i])<0));rows.append(v)
                        # Search stability, evaluated as retrieval behavior, not semantic truth.
                        count=min(len(dist),max(30,int(np.ceil(len(dist)*.2))));baseids=set(np.argsort(dist)[:count]);out={}
                        for label,delta in [('small',.05),('large',1.)]:
                            pert=state.copy();pert[0]+=delta;dd=((ps-pert)**2).mean(1);ids=set(np.argsort(dd)[:count]);out[label+'_jaccard']=len(ids&baseids)/len(ids|baseids)
                        search_audit.append(dict(asset=asset,date=t.date,cal_n=len(pool),distance_ess=1/(dw@dw),cluster_n=int(group.sum()),cluster_fallback=fallback,**out))
                audit.append(dict(year=year,asset=asset,model=name,pooled_train_n=len(tr),asset_train_n=len(train_by[asset]),cal_n=len(pool),test_n=len(idx)))
        if year==2026:models_2026=(pm,hm,tr,train_by,ss,banks)
        print(year,len(tr),len(te),flush=True)
        if rows:pd.DataFrame(rows).to_parquet(OUT/'predictions.parquet',index=False)
    result=pd.DataFrame(rows);old=pd.read_parquet(ROOT/'reports/asset_feature_research_20261103/predictions.parquet');old=old[old.method.isin(['ridge_vol80','ridge_old_residual','ridge_interactions_residual','lgb_expanded_residual','lgb_direct80','lgb_search_residual'])]
    ref=set(map(tuple,old[old.method=='ridge_vol80'][['asset','date']].to_numpy()))
    for _,x in result.groupby('method'):assert set(map(tuple,x[['asset','date']].to_numpy()))==ref
    e=result[result.method=='pooled_evidence_only'].merge(result[result.method=='pooled_residual'],on=['asset','date'],suffixes=('_a','_b'),validate='one_to_one');assert abs(e.q10_a-e.q10_b).max()==0 and abs(e.q90_a-e.q90_b).max()==0
    pd.concat([result,old],ignore_index=True).to_parquet(OUT/'predictions.parquet',index=False);pd.DataFrame(audit).to_csv(OUT/'folds.csv',index=False);pd.DataFrame(search_audit).to_csv(OUT/'A_search_audit.csv',index=False)
    sensitivity(d,infer,cats,models_2026)
    (OUT/'verification.json').write_text(json.dumps({'same_asset_date_pairs':True,'asset_date_count':len(ref),'evidence_only_identical':True,'no_portfolio_model':True,'A_features_exclude_shocks':True,'point_in_time_publication_certified':False},indent=2))

def sensitivity(d,infer,cats,stored):
    pm,hm,tr,train_by,ss,banks=stored;asof=infer.date.max();q=infer[infer.date==asof].copy();out=[];calcut=pd.Timestamp('2025-01-01');base_models={'pooled':pm,'partial':hm}
    for version in ['full','recent8']:
        train=tr if version=='full' else tr[tr.date>=calcut-pd.DateOffset(years=8)]
        if version=='recent8':base_models={'pooled':learner().fit(pooled_x(train,cats),train.target/train.scale,sample_weight=date_weights(train)),'partial':PartialPool(cats).fit(train,train.target/train.scale,date_weights(train))}
        for asset,t in q.groupby('asset'):
            local=train[train.asset==asset]
            independent={'ridge':model('ridge').fit(local[FEATURES],local.target/local.scale),'lgb_independent':model('lgb').fit(local[EXPANDED],local.target/local.scale)}
            for name,m in {**base_models,**independent}.items():
                baseline=None
                for label,changes in SCENARIOS.items():
                    x=t.copy()
                    for s in SHOCKS:x[s]=changes.get(s,0.)
                    pred=float(m.predict(pooled_x(x,cats) if name=='pooled' else x if name=='partial' else x[FEATURES if name=='ridge' else EXPANDED])[0]*x.scale.iloc[0])
                    if label=='zero':baseline=pred
                    # Calibrated interval only for the frozen validated full models.
                    lo=hi=np.nan;ess=np.nan
                    if version=='full' and name in ['pooled','partial']:
                        p=pd.concat(banks[name][asset],ignore_index=True);p=p[(p.date>=pd.Timestamp('2021-01-01'))&(p.ready<pd.Timestamp('2026-01-01'))];w=np.ones(len(p))/len(p);lo,_,hi=pred+weighted_q(p.residual,w)*x.scale.iloc[0];ess=len(p)
                    outside=[s for s in SHOCKS if x[s].iloc[0]<local[s].min() or x[s].iloc[0]>local[s].max()]
                    out.append(dict(asset=asset,model=name,version=version,state_date=asof,scenario=label,center=pred,delta_from_zero=pred-baseline,q10=lo,q90=hi,cal_n=ess,outside_training_range='|'.join(outside),approved=False))
    pd.DataFrame(out).to_csv(OUT/'asset_shock_sensitivity.csv',index=False)

if __name__=='__main__':main()
