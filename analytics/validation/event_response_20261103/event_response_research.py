"""Train-only event learning and feature ablation; no interval widening or deployment."""
import json
import numpy as np
import pandas as pd
from lightgbm import LGBMClassifier, LGBMRegressor
from asset_feature_research import ROOT, EXPANDED, SHOCKS

SRC=ROOT/'reports/exposure_universe_20261103'
OUT=ROOT/'reports/event_response_20261103'
def features(d):
    d=d.copy();new=[]
    for s in SHOCKS:
        for c in ['market_trend20','market_vol20','asset_trend20','asset_vol20','relative_market20']:
            n=s+'__'+c;d[n]=d[s]*d[c];new.append(n)
    for a,b in [('asset_vol5','asset_vol60'),('market_vol5','market_vol60')]:
        n=a+'_ratio';d[n]=d[a]/d[b].clip(lower=.1);new.append(n)
    for a,b in [('asset_trend5','asset_trend20'),('market_trend5','market_trend20')]:
        n=a+'_acceleration';d[n]=d[a]-d[b]/4;new.append(n)
    return d,EXPANDED+new
def label(y):return np.where(y<=-5,0,np.where(y>=5,2,1))
def main():
    OUT.mkdir(exist_ok=True)
    assets=json.loads((SRC/'selected_assets.json').read_text())
    d,extended=features(pd.read_parquet(SRC/'learning_table.parquet'))
    base=pd.read_parquet(SRC/'predictions.parquet');base=base[base.asset.isin(assets)&base.model.eq('lgb')&base.spec.eq('all4')]
    protocol=dict(assets=assets,train='Same prior-year Jan1 minus20day label cutoff; no evaluation labels used in fitting or thresholds',evaluation='Same918rows,2023-2026 reused development evaluation; not blind',event='5day return<=-5%, >=+5%; other neutral',new_features=extended[len(EXPANDED):],methods='Baseline; natural classifier base/engineered; balanced classifier engineered. Mixture and hard routing separately.',routing='Class-specific training medians; neutral hard route uses separately trained median regressor. Mixture sums class median times uncalibrated classifier scores. Not a conditional median.',weights='Balanced class inverse frequencies from training only; no evaluation threshold tuning',interval='Each baseline interval width and offsets frozen, translate with centre only; diagnostic not newly calibrated interval',production_approved=False)
    (OUT/'protocol.json').write_text(json.dumps(protocol,ensure_ascii=False,indent=2),encoding='utf8')
    rows=[];audit=[];importance=[];contrasts=[]
    params=dict(n_estimators=250,learning_rate=.04,max_depth=4,num_leaves=15,min_child_samples=40,random_state=20261103,n_jobs=2,verbosity=-1)
    for asset in assets:
        for year in range(2023,2027):
            old=base[base.asset.eq(asset)&base.year.eq(year)].sort_values('date');f=d[d.asset.eq(asset)]
            tr=f[f.end_date<pd.Timestamp(year-1,1,1)-pd.Timedelta(days=20)]
            te=f.set_index('date').loc[old.date].reset_index();assert tr.end_date.max()<te.date.min()
            y=label(tr.target);yt=label(te.target);med=np.array([tr.target[y==k].median() for k in range(3)])
            preds={'baseline':old.center.to_numpy()};probs={}
            reg=LGBMRegressor(objective='quantile',alpha=.5,**params).fit(tr[extended],tr.target)
            neutral=reg.predict(te[extended]);preds['engineered_median']=neutral
            for name,cols,balanced in [('base_natural',EXPANDED,False),('engineered_natural',extended,False),('engineered_balanced',extended,True)]:
                model=LGBMClassifier(objective='multiclass',class_weight='balanced' if balanced else None,**params).fit(tr[cols],y)
                p=model.predict_proba(te[cols]);called=p.argmax(axis=1)
                preds[name+'_mixture']=p@med;preds[name+'_route']=np.where(called==1,neutral,med[called]);probs[name]=p
                if name=='engineered_natural':
                    # Evaluation-label use is diagnostic only; never feeds training or selection.
                    rng=np.random.default_rng(20261103);loss=-np.log(np.maximum(p[np.arange(len(yt)),yt],1e-12)).mean()
                    for col in cols:
                        x=te[cols].copy();x[col]=rng.permutation(x[col].to_numpy());pp=model.predict_proba(x)
                        importance.append(dict(asset=asset,year=year,feature=col,logloss_increase=float(-np.log(np.maximum(pp[np.arange(len(yt)),yt],1e-12)).mean()-loss)))
            for name,pred in preds.items():
                z=old[['asset','date','end_date','actual','q10','q90','center']].copy();shift=pred-z.center.to_numpy();z['center']=pred;z.q10+=shift;z.q90+=shift;z['method']=name
                for key,p in probs.items():
                    if name.startswith(key):z['down_score']=p[:,0];z['neutral_score']=p[:,1];z['up_score']=p[:,2]
                rows.extend(z.to_dict('records'))
            for col in extended:
                sd=max(tr[col].std(),1e-8)
                contrasts.append(dict(asset=asset,year=year,feature=col,crash_standardized_shift=(tr.loc[y==0,col].mean()-tr.loc[y==1,col].mean())/sd,rally_standardized_shift=(tr.loc[y==2,col].mean()-tr.loc[y==1,col].mean())/sd))
            audit.append(dict(asset=asset,year=year,train_end=str(tr.end_date.max()),test_start=str(te.date.min()),train_n=len(tr),crash_train_n=int((y==0).sum()),rally_train_n=int((y==2).sum()),down_center=med[0],neutral_center=med[1],up_center=med[2]))
            print(asset,year,flush=True)
    r=pd.DataFrame(rows);r['mae']=(r.actual-r.center).abs();r['width']=r.q90-r.q10;r['coverage']=r.actual.between(r.q10,r.q90);r['fixed5_coverage']=r.mae<=2.5
    r.to_parquet(OUT/'predictions.parquet',index=False)
    metrics=[]
    for asset,x in [('ALL',r),*list(r.groupby('asset'))]:
        for name,z in x.groupby('method'):
            down=z.actual<=-5;up=z.actual>=5;dc=z.center<=-5;uc=z.center>=5
            nz=z.actual.ne(0);hits=np.sign(z.actual[nz])==np.sign(z.center[nz])
            metrics.append(dict(asset=asset,method=name,n=len(z),direction_n=int(nz.sum()),direction_accuracy=hits.mean(),always_up_accuracy=z.loc[nz,'actual'].gt(0).mean(),balanced_direction_accuracy=.5*((z.loc[z.actual<0,'center']<0).mean()+(z.loc[z.actual>0,'center']>0).mean()),mae=z.mae.mean(),crash_mae=z.loc[down,'mae'].mean(),rally_mae=z.loc[up,'mae'].mean(),crash_n=int(down.sum()),crash_tp=int((down&dc).sum()),crash_recall=(down&dc).sum()/down.sum(),crash_precision=(down&dc).sum()/dc.sum() if dc.sum() else None,crash_false=int((dc&~down).sum()),rally_n=int(up.sum()),rally_tp=int((up&uc).sum()),rally_recall=(up&uc).sum()/up.sum(),rally_precision=(up&uc).sum()/uc.sum() if uc.sum() else None,rally_false=int((uc&~up).sum()),width=z.width.mean(),coverage=z.coverage.mean(),fixed5_coverage=z.fixed5_coverage.mean()))
    pd.DataFrame(metrics).to_csv(OUT/'metrics.csv',index=False);pd.DataFrame(audit).to_csv(OUT/'time_audit.csv',index=False)
    pd.DataFrame(importance).to_csv(OUT/'feature_permutation.csv',index=False);pd.DataFrame(contrasts).to_csv(OUT/'training_feature_contrasts.csv',index=False)
    assert len(r)==918*8 and r.groupby(['asset','date']).width.agg(lambda x:x.max()-x.min()).max()<1e-8
    (OUT/'verification.json').write_text(json.dumps(dict(same918=True,interval_not_widened=True,train_only_class_weights=True,train_only_features=True,approved=False),indent=2))
if __name__=='__main__':main()
