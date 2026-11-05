"""Frozen corrected-data comparison. No cloud, contract or model promotion."""
import json, hashlib
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler
from sklearn.neighbors import NearestNeighbors
from catboost import CatBoostRegressor
from lightgbm import LGBMRegressor
from threadpoolctl import threadpool_limits
from .core import STATE,ASSET,SHOCKS,anchors
from .rebuild_fixed_model import training
from .conditional_loss_research import ConditionalFactor

ROOT=Path('reports/service_scope_20261105')
OUT=Path('reports/three_model_intervals_20261105')
FEATURES=STATE+ASSET+SHOCKS
MODELS=['catboost','hybrid_lightgbm','huber']

def weights(d):
    w=1/d.groupby('date').date.transform('size').to_numpy();return w/w.mean()

class Partial:
    def __init__(self,assets,alpha=300,ratio=10):self.assets=assets;self.alpha=alpha;self.ratio=ratio
    def design(self,d,fit=False):
        x=d[FEATURES].copy()
        for s in SHOCKS:
            for c in ['market_trend20','market_vol20']:x[s+'__'+c]=d[s]*d[c]
        if fit:self.scaler=StandardScaler().fit(x)
        z=self.scaler.transform(x);one=np.eye(len(self.assets))[[self.assets.index(a) for a in d.asset]]/np.sqrt(self.ratio)
        sh=z[:,[FEATURES.index(s) for s in SHOCKS]]
        return np.column_stack([z,one,(one[:,:,None]*sh[:,None,:]).reshape(len(d),-1)])
    def fit(self,d):
        self.model=Ridge(alpha=self.alpha).fit(self.design(d,True),d.target/d.scale,sample_weight=weights(d));return self
    def predict(self,d):return self.model.predict(self.design(d))

def fit_partial(data,origin,assets,audits):
    tr=training(data,pd.Timestamp(origin,1,1))
    inner=training(data,pd.Timestamp(origin-1,1,1));val=anchors(tr[tr.date>=pd.Timestamp(origin-1,1,1)])
    assert len(inner)>250 and len(val)>0 and inner.end_date.max()<val.date.min()
    trials=[]
    for alpha,ratio in [(300,10),(300,100),(3000,10),(3000,100)]:
        m=Partial(assets,alpha,ratio).fit(inner)
        loss=float(np.average(abs(val.target-m.predict(val)*val.scale),weights=weights(val)))
        trials.append((loss,alpha,ratio))
    loss,alpha,ratio=min(trials)
    audits.append(dict(origin=origin,alpha=alpha,ratio=ratio,inner_label_end=str(inner.end_date.max()),validation_start=str(val.date.min()),train_label_end=str(tr.end_date.max())))
    return Partial(assets,alpha,ratio).fit(tr),tr

class Support:
    def fit(self,tr):
        h=tr.sort_values('date').drop_duplicates('date').iloc[::6];cols=STATE+SHOCKS
        self.mid=h[cols].median();self.scale=(h[cols].quantile(.75)-h[cols].quantile(.25)).replace(0,1)
        self.nn=NearestNeighbors(n_neighbors=min(20,len(h)),n_jobs=2).fit((h[cols]-self.mid)/self.scale)
        ds,ix=self.nn.kneighbors((h[cols]-self.mid)/self.scale);dates=h.date.to_numpy();valid=[]
        for i in range(len(h)):
            far=ds[i][abs((dates[ix[i]]-dates[i])/np.timedelta64(1,'D'))>20]
            if len(far):valid.append(float(far[:3].mean()))
        self.threshold=float(np.quantile(valid,.95));return self
    def gate(self,d):
        ds,_=self.nn.kneighbors((d[STATE+SHOCKS]-self.mid)/self.scale,n_neighbors=3)
        return np.clip(2-ds.mean(axis=1)/max(self.threshold,1e-6),0,1)

def tree_x(d,assets):return np.column_stack([d[FEATURES],np.eye(len(assets))[[assets.index(a) for a in d.asset]]])

def main():
    OUT.mkdir(exist_ok=True);cfg=json.loads((ROOT/'locked_protocol.json').read_text())
    f=pd.read_parquet(ROOT/'corrected_features.parquet');old=pd.read_parquet('reports/huber_followup_20261105/predictions.parquet')
    protected=[ROOT/'corrected_features.parquet',ROOT/'final_service_bundle.joblib',Path('reports/support_expansion_20261104/research_input.parquet')]
    hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in protected}
    protocol=dict(models=MODELS,keys='Exact latest Huber 4150 stock/date rows, 50 served stocks',features=FEATURES,
        data='Corrected PIT research input; not live Fabric Gold',huber='Existing delta1.35; raw target; alpha300; no posthoc delta075',
        catboost='Per asset normalized target; quantile .5; 150 trees depth3 lr.04 seed20261104',
        hybrid='Normalized partial Ridge; train-only inner tuning alpha300/3000 ratio10/100; state x shock; annual forward OOF residual LightGBM150 depth3 leaves7 lr.04; historical joint-support taper',
        intervals='Both 80/90 from identical prior-year calibration normalized residuals; pooled served stocks primary comparison; asset calibration sensitivity; no evaluation tuning',
        direction='Actual zero excluded for ALL models',embargo='20 calendar days plus label publication before cutoff',
        evaluation='2023-2026 reused development data; historical realized future shocks supplied ex post, not causal or advance prediction',
        pooling='Existing 18/68 training cohorts and fixed served routing retained for Huber reproduction; CatBoost uses same stock rows, pooled model shares cohort rows; no row is an independent macro event',source_hashes=hashes)
    (OUT/'protocol.json').write_text(json.dumps(protocol,indent=2),encoding='utf8')
    audits=[];splits=[];pieces=[];calpieces=[]
    for group in ['primary','expanded']:
        assets=cfg['cohorts'][group]['assets'];data=f[f.asset.isin(assets)]
        oof=[];linears={}
        # Earliest complete corrected state dates begin in 2014. Two previous years for inner selection.
        for origin in range(2016,2026):
            m,tr=fit_partial(data,origin,assets,audits);linears[origin]=m
            q=training(data,pd.Timestamp(2027,1,1));q=q[(q.date>=pd.Timestamp(origin,1,1))&(q.date<pd.Timestamp(origin+1,1,1))].copy()
            q['residual']=q.target/q.scale-m.predict(q);q['oof_train_label_end']=tr.end_date.max()
            assert (q.date>q.oof_train_label_end).all();oof.append(q)
            print('OOF',group,origin,len(q),flush=True)
        oof=pd.concat(oof)
        for year in cfg['folds']:
            tr=training(data,pd.Timestamp(year-1,1,1));ref=old[(old.group==group)&(old.year==year)]
            te=ref[['date','asset']].merge(data,on=['date','asset'],validate='one_to_one');served=sorted(te.asset.unique())
            cal=anchors(training(data[data.date>=pd.Timestamp(year-1,1,1)],pd.Timestamp(year,1,1)));cal=cal[cal.asset.isin(served)]
            assert tr.end_date.max()<cal.date.min() and cal.end_date.max()<te.date.min()
            residual=training(oof,pd.Timestamp(year-1,1,1));assert residual.end_date.max()<cal.date.min()
            lin=linears[year-1];support=Support().fit(tr)
            tree=LGBMRegressor(objective='quantile',alpha=.5,n_estimators=150,max_depth=3,num_leaves=7,learning_rate=.04,min_child_samples=30,reg_lambda=10,n_jobs=2,verbosity=-1,random_state=20261104)
            tree.fit(tree_x(residual,assets),residual.residual,sample_weight=weights(residual))
            huber=ConditionalFactor(dict(loss='huber',gates=False)).fit(tr);assert huber.converged
            cats={}
            for a in served:
                z=tr[tr.asset==a];assert len(z)>=250
                cats[a]=CatBoostRegressor(iterations=150,depth=3,learning_rate=.04,loss_function='Quantile:alpha=0.5',random_seed=20261104,thread_count=2,verbose=False,allow_writing_files=False).fit(z[FEATURES].to_numpy(),z.target/z.scale)
            for split,d in [('cal',cal),('test',te)]:
                h=huber.predict(d);hy=(lin.predict(d)+tree.predict(tree_x(d,assets))*support.gate(d))*d.scale.to_numpy()
                cat=np.empty(len(d))
                for a in served:
                    ix=d.asset.eq(a).to_numpy();cat[ix]=cats[a].predict(d.loc[ix,FEATURES].to_numpy())*d.loc[ix,'scale'].to_numpy()
                if split=='test':np.testing.assert_allclose(h,ref.huber,atol=1e-9)
                for name,pred in zip(MODELS,[cat,hy,h]):
                    z=d[['date','end_date','asset','target','scale']].rename(columns={'target':'actual'}).copy()
                    z['center']=pred;z['year']=year;z['group']=group;z['model']=name;z['high_vol']=d.market_vol20>tr.market_vol20.quantile(.75)
                    (pieces if split=='test' else calpieces).append(z)
            splits.append(dict(group=group,year=year,train_rows=len(tr),cal_rows=len(cal),cal_dates=cal.date.nunique(),test_rows=len(te),train_label_end=str(tr.end_date.max()),cal_start=str(cal.date.min()),cal_label_end=str(cal.end_date.max()),test_start=str(te.date.min()),oof_rows=len(residual)))
            pd.concat(pieces).to_parquet(OUT/'points.parquet',index=False);pd.concat(calpieces).to_parquet(OUT/'calibration.parquet',index=False)
            print('FOLD COMPLETE',group,year,len(te),flush=True)
    p=pd.concat(pieces);c=pd.concat(calpieces);intervals=[]
    for (year,m),z in p.groupby(['year','model']):
        cal=c[(c.year==year)&(c.model==m)].copy();cal['residual']=(cal.actual-cal.center)/cal.scale
        for method in ['pooled','asset']:
            for level in [.8,.9]:
                alpha=1-level
                for a,t in z.groupby('asset'):
                    pool=cal if method=='pooled' else cal[cal.asset==a];assert len(pool)>0
                    q=np.quantile(pool.residual,[alpha/2,1-alpha/2]);v=t.copy();v['level']=level;v['interval']=method
                    v['lo']=v.center+q[0]*v.scale;v['hi']=v.center+q[1]*v.scale;v['cal_rows']=len(pool);v['cal_dates']=pool.date.nunique();intervals.append(v)
    pd.concat(intervals).to_parquet(OUT/'intervals.parquet',index=False)
    for name,obj in [('fit_audit.json',audits),('splits.json',splits)]: (OUT/name).write_text(json.dumps(obj,indent=2),encoding='utf8')
    assert all(hashlib.sha256(Path(k).read_bytes()).hexdigest()==v for k,v in hashes.items())
    assert all(len(z)==len(old) and set(zip(z.date,z.asset))==set(zip(old.date,old.asset)) for _,z in p.groupby('model'))
    (OUT/'verification.json').write_text(json.dumps(dict(passed=True,huber_reproduced=True,identical_keys=True,protected_hashes_unchanged=True,azure_gold_changed=False,production_promoted=False),indent=2),encoding='utf8')
    print('COMPLETE',flush=True)

if __name__=='__main__':
    with threadpool_limits(limits=2):main()
