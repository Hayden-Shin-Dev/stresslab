"""Conditional all-variable deletion analysis followed by same-key center ablation.
No claim that dependent financial inputs have uniquely identifiable causal effects.
"""
import json,hashlib,argparse
from concurrent.futures import ThreadPoolExecutor,as_completed
import numpy as np
import pandas as pd
from lightgbm import LGBMRegressor
from threadpoolctl import threadpool_limits
from train_selected_response_20261104 import ROOT,STATE,SHOCKS
from report_long_universe import metric

OUT=ROOT/'reports/crash_mechanism_20261104'
PREVIOUS=ROOT/'reports/selected_response_20261104'
FEATURES=STATE+SHOCKS

class Additive:
    """Joint regularized piecewise-linear main effects and named product interactions."""
    def __init__(self,interactions=(),alpha=100.):self.interactions=list(interactions);self.alpha=alpha
    def raw(self,frame):
        a=frame[FEATURES].fillna(self.median).to_numpy(float)
        a=np.maximum(self.minimum,np.minimum(self.maximum,a))
        return (a-self.median.to_numpy())/self.scale
    def basis(self,frame):
        a=self.raw(frame);parts=[]
        for i,c in enumerate(FEATURES):parts.append(np.column_stack([a[:,i]]+[np.maximum(a[:,i]-k,0) for k in self.knots[:,i]]))
        for s,t in self.interactions:parts.append((a[:,FEATURES.index(s)]*a[:,FEATURES.index(t)])[:,None])
        return np.column_stack(parts)
    def fit(self,frame,y):
        self.median=frame[FEATURES].median().fillna(0);a=frame[FEATURES].fillna(self.median).to_numpy(float)
        self.minimum=a.min(0);self.maximum=a.max(0);self.scale=np.maximum(a.std(0),1e-6)
        norm=(a-self.median.to_numpy())/self.scale;self.knots=np.quantile(norm,[.2,.4,.6,.8],axis=0)
        x=self.basis(frame);self.bmean=x.mean(0);self.bstd=np.maximum(x.std(0),1e-6);x=(x-self.bmean)/self.bstd
        self.mean=float(np.mean(y));self.inverse=np.linalg.inv(x.T@x+self.alpha*np.eye(x.shape[1]));self.coef=self.inverse@(x.T@(np.asarray(y)-self.mean))
        self.groups={c:list(range(i*5,(i+1)*5)) for i,c in enumerate(FEATURES)}
        for j,(s,t) in enumerate(self.interactions):
            self.groups[s].append(len(FEATURES)*5+j);self.groups[t].append(len(FEATURES)*5+j)
        return self
    def design(self,frame):return (self.basis(frame)-self.bmean)/self.bstd
    def predict(self,frame):return self.mean+self.design(frame)@self.coef
    def without(self,frame,feature):
        g=self.groups[feature];correction=self.inverse[:,g]@np.linalg.solve(self.inverse[np.ix_(g,g)],self.coef[g])
        return self.mean+self.design(frame)@(self.coef-correction)
    def components(self,frame):
        x=self.design(frame);v={c:x[:,i*5:(i+1)*5]@self.coef[i*5:(i+1)*5] for i,c in enumerate(FEATURES)}
        for j,(s,t) in enumerate(self.interactions):v[s+'__'+t]=x[:,len(FEATURES)*5+j]*self.coef[len(FEATURES)*5+j]
        assert np.allclose(self.mean+np.column_stack(list(v.values())).sum(1),self.predict(frame),atol=1e-7)
        return v

def inputs():
    pairs=pd.read_csv(PREVIOUS/'frozen_pairs.csv',dtype={'asset':str})
    data=pd.read_parquet(ROOT/'reports/rich_context_20261103/learning_table.parquet')
    h=pd.read_parquet(ROOT/'reports/effect_atlas_20261104/coordinates/heterogeneity.parquet')
    inter={}
    for asset in sorted(pairs.asset.unique()):
        z=h[h.asset.eq(asset)&h.outcome.eq('return')&h.state.isin(STATE)]
        g=z.groupby(['shock','state']).agg(n=('fold','nunique'),pos=('response_difference',lambda x:(x>0).sum()),neg=('response_difference',lambda x:(x<0).sum()),strength=('response_difference',lambda x:x.abs().mean()))
        g=g[(g.n==2)&((g.pos==2)|(g.neg==2))].sort_values('strength',ascending=False).head(8)
        inter[asset]=list(g.index)
    return pairs,data,inter

def analyze():
    OUT.mkdir(exist_ok=True);pairs,data,inter=inputs();rows=[];dependence=[];folds=[];saturation=[];audit=[]
    (OUT/'protocol.json').write_text(json.dumps(dict(assets=42,variables=FEATURES,
       analysis_periods=['2018-2019','2020-2021'],selection='Fixed previous 42 stocks, no reselection on 2023-2026 results',
       analysis='Joint regularized additive functions. Exact leave-variable-out refits, removing its interactions too. Held-out deletion error measures conditional predictive information, not pure causal effect.',
       overlap='Correlated inputs are not made independent. Exact identities already excluded; shared information and interactions remain explicit.',
       training_followup=['scale_corrected_huber','joint_additive','joint_additive_interactions'],
       no_interval_tuning=True,blind=False,alpha=100,huberscale='training target MAD*1.4826, floor 1pp, alpha0.9',
       interpolation='Input values outside training extrema are capped and flagged; no unrestricted spline extrapolation.',
       azure_modified=False,gold_modified=False),indent=2))
    def run(asset):
        f=data[data.asset.eq(asset)].sort_values('date');records=[];deps=[];quality=[];units=[];times=[]
        for year in [2018,2020]:
            cut=pd.Timestamp(year,1,1);tr=f[f.end_date<cut-pd.Timedelta(days=20)];te=f[(f.date>=cut)&(f.end_date<pd.Timestamp(year+2,1,1)-pd.Timedelta(days=20))].iloc[::6]
            if len(tr)<500 or len(te)<20:continue
            # Main effects only: these held-out windows cannot use interaction rankings derived from the windows themselves.
            m=Additive().fit(tr,tr.target);pred=m.predict(te);parts=m.components(te);cr=te.target.to_numpy()<=-5;ra=te.target.to_numpy()>=5;y=te.target.to_numpy()
            quality.append(dict(asset=asset,fold=year,n=len(te),mae=float(abs(y-pred).mean()),crash_n=int(cr.sum()),crash_mae=float(abs(y[cr]-pred[cr]).mean())))
            correlations=tr[FEATURES].corr();test_design=m.design(te)
            for c in FEATURES:
                g=m.groups[c];correction=m.inverse[:,g]@np.linalg.solve(m.inverse[np.ix_(g,g)],m.coef[g])
                dropped=m.mean+test_design@(m.coef-correction);effect=parts[c];correlation=correlations[c].drop(c).abs();partner=correlation.idxmax() if correlation.notna().any() else None
                records.append(dict(asset=asset,fold=year,feature=c,n=len(te),train_missing=float(tr[c].isna().mean()),train_distinct=int(tr[c].nunique()),
                  conditional_mae_value=float(abs(y-dropped).mean()-abs(y-pred).mean()),
                  conditional_crash_value=float(abs(y[cr]-dropped[cr]).mean()-abs(y[cr]-pred[cr]).mean()),
                  crash_n=int(cr.sum()),crash_contribution=float(effect[cr].mean()),rally_contribution=float(effect[ra].mean()),
                  ordinary_contribution=float(effect[~(cr|ra)].mean()),mean_abs_contribution=float(abs(effect).mean()),
                  most_correlated=partner,max_abs_correlation=float(correlation.max())))
            # Identity check: block-inverse deletion equals an actual reduced ridge refit.
            X=m.design(tr);Y=tr.target.to_numpy()-m.mean
            for feature in ['shock_oil','foreign_flow_20','market_vol20']:
                keep=np.setdiff1d(np.arange(X.shape[1]),m.groups[feature]);coef=np.linalg.solve(X[:,keep].T@X[:,keep]+m.alpha*np.eye(len(keep)),X[:,keep].T@Y)
                assert np.allclose(m.mean+m.design(te)[:,keep]@coef,m.without(te,feature),atol=1e-6)
            residual=tr.target.to_numpy()-tr.target.mean();scale=max(1.,1.4826*np.median(abs(tr.target-tr.target.median())))
            units.append(dict(asset=asset,fold=year,target_scale_pp=scale,old_huber_threshold_pp=.9,new_huber_threshold_pp=.9*scale,
                 old_clipped_fraction=float((abs(residual)>.9).mean()),new_clipped_fraction=float((abs(residual)>.9*scale).mean()),
                 old_initial_crash_gradient=float(np.minimum(abs(residual[tr.target<=-5]),.9).mean()),
                 new_initial_crash_gradient_return_units=float(np.minimum(abs(residual[tr.target<=-5]),.9*scale).mean())))
            times.append(dict(asset=asset,fold=year,train_end=str(tr.end_date.max()),analysis_start=str(te.date.min()),analysis_end=str(te.end_date.max())))
        return records,deps,quality,units,times
    with threadpool_limits(limits=1,user_api='blas'),ThreadPoolExecutor(max_workers=4) as pool:
        jobs={pool.submit(run,a):a for a in sorted(pairs.asset.unique())}
        for i,future in enumerate(as_completed(jobs),1):
            r,d,q,u,t=future.result();rows+=r;dependence+=d;folds+=q;saturation+=u;audit+=t;print('analysis',i,len(jobs),flush=True)
    r=pd.DataFrame(rows);r.to_csv(OUT/'all_variable_conditional_analysis.csv',index=False)
    summary=r.groupby(['asset','feature']).agg(folds=('fold','nunique'),mae_value=('conditional_mae_value','mean'),crash_value=('conditional_crash_value','mean'),positive_crash_folds=('conditional_crash_value',lambda x:(x>0).sum()),
        crash_contribution=('crash_contribution','mean'),rally_contribution=('rally_contribution','mean'),max_correlation=('max_abs_correlation','max'),missing=('train_missing','mean')).reset_index()
    summary.to_csv(OUT/'variable_stability.csv',index=False);pd.DataFrame(folds).to_csv(OUT/'analysis_model_quality.csv',index=False)
    pd.DataFrame(saturation).to_csv(OUT/'gradient_saturation.csv',index=False);pd.DataFrame(audit).to_csv(OUT/'analysis_time_audit.csv',index=False)
    (OUT/'interactions.json').write_text(json.dumps(inter,indent=2));(OUT/'analysis_complete.json').write_text(json.dumps(dict(complete=True,rows=len(r),identities_verified=True)))

def train():
    assert json.loads((OUT/'analysis_complete.json').read_text())['complete']
    assert json.loads((OUT/'interaction_complete.json').read_text())['complete']
    pairs,data,_=inputs();inter=json.loads((OUT/'interactions.json').read_text())
    ref=pd.read_parquet(PREVIOUS/'predictions.parquet');ref=ref[ref.method.eq('all4_median')];records=[];components=[];times=[];scales=[]
    def run(asset):
        f=data[data.asset.eq(asset)].sort_values('date');ps=pairs[pairs.asset.eq(asset)];signs=dict(zip(ps.feature,ps.sign));rr=[];cc=[];tt=[];ss=[]
        for year in range(2023,2027):
            cut=pd.Timestamp(year,1,1);start=pd.Timestamp(year-1,1,1);tr=f[f.end_date<start-pd.Timedelta(days=20)]
            old=ref[ref.asset.eq(asset)&ref.date.dt.year.eq(year)].sort_values('date');te=f.set_index('date').loc[old.date].reset_index()
            if old.empty:continue
            assert tr.end_date.max()<te.date.min()
            scale=max(1.,1.4826*np.median(abs(tr.target-tr.target.median())))
            m=LGBMRegressor(objective='huber',alpha=.9,n_estimators=250,learning_rate=.04,max_depth=4,num_leaves=15,min_child_samples=40,random_state=20261104,n_jobs=1,verbosity=-1,
                monotone_constraints=[int(signs.get(c,0)) for c in FEATURES],monotone_constraints_method='advanced').fit(tr[FEATURES],tr.target/scale)
            predictions={'scale_corrected_huber':m.predict(te[FEATURES])*scale}
            ss.append(dict(asset=asset,year=year,scale_pp=scale,clip_threshold_pp=scale*.9))
            for name,interaction in [('joint_additive',[]),('joint_additive_interactions',inter[asset])]:
                model=Additive(interaction).fit(tr,tr.target);predictions[name]=model.predict(te)
                observed=te[FEATURES].fillna(model.median).to_numpy(float)
                outside=((observed<model.minimum)|(observed>model.maximum)).sum(1)
                parts=model.components(te)
                for feature,v in parts.items():
                    for date,y,pred,effect,count in zip(te.date,te.target,predictions[name],v,outside):
                        cc.append(dict(asset=asset,date=date,method=name,feature=feature,contribution_pp=effect,actual=y,center=pred,intercept=model.mean,outside_training_features=int(count)))
            for name,center in predictions.items():
                r=old[['asset','date','actual']+SHOCKS].copy();r['method']=name;r['center']=center;rr.append(r)
            tt.append(dict(asset=asset,year=year,train_n=len(tr),train_label_end=str(tr.end_date.max()),test_start=str(te.date.min()),n=len(te)))
        return pd.concat(rr),cc,tt,ss
    with threadpool_limits(limits=1,user_api='blas'),ThreadPoolExecutor(max_workers=4) as pool:
        jobs={pool.submit(run,a):a for a in sorted(pairs.asset.unique())}
        for i,future in enumerate(as_completed(jobs),1):
            r,c,t,s=future.result();records.append(r);components+=c;times+=t;scales+=s
            (OUT/'training_progress.json').write_text(json.dumps(dict(completed=i,total=len(jobs))));print('train',i,len(jobs),flush=True)
    p=pd.concat(records);p.to_parquet(OUT/'predictions.parquet',index=False,compression='zstd')
    pd.DataFrame(components).to_parquet(OUT/'conditional_components.parquet',index=False,compression='zstd')
    pd.DataFrame(times).to_csv(OUT/'training_time_audit.csv',index=False);pd.DataFrame(scales).to_csv(OUT/'training_scales.csv',index=False)
    (OUT/'training_progress.json').write_text(json.dumps(dict(status='complete',completed=len(jobs))))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('stage',choices=['analysis','train']);a=p.parse_args()
    analyze() if a.stage=='analysis' else train()
