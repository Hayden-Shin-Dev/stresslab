"""Compare bounded state interactions and training losses on frozen PIT data."""
import hashlib,json
from pathlib import Path
import joblib,numpy as np,pandas as pd
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits
from .core import STATE,ASSET,SHOCKS,anchors
from .rebuild_fixed_model import training
from .finalize_model import stats
from .diagnose_recent import block_ci

ROOT=Path('reports/service_scope_20261105');OUT=Path('reports/conditional_loss_20261105')
CONFIGS=[dict(name='baseline',loss='squared',gates=False),
         dict(name='huber',loss='huber',gates=False),
         dict(name='tail',loss='tail',gates=False),
         dict(name='gated',loss='squared',gates=True),
         dict(name='gated_huber',loss='huber',gates=True),
         dict(name='gated_tail',loss='tail',gates=True)]

class ConditionalFactor:
    def __init__(self,config):self.config=config
    def design(self,d,fit=False):
        x=d[STATE+ASSET+SHOCKS].copy()
        if self.config['gates']:
            if fit:
                self.gate_mean=d[['market_trend20','market_vol20']].mean()
                self.gate_scale=d[['market_trend20','market_vol20']].std().clip(lower=1e-8)
            for c in ['market_trend20','market_vol20']:
                gate=np.tanh((d[c]-self.gate_mean[c])/self.gate_scale[c])
                for s in SHOCKS:x[s+'__'+c]=d[s]*gate
        if fit:
            self.assets=sorted(d.asset.unique());self.columns=list(x);self.scaler=StandardScaler().fit(x)
        z=self.scaler.transform(x)
        one=np.eye(len(self.assets))[[self.assets.index(a) for a in d.asset]]/np.sqrt(10)
        sh=z[:,[self.columns.index(s) for s in SHOCKS]]
        return np.column_stack([z,one,(one[:,:,None]*sh[:,None,:]).reshape(len(d),-1)])
    def fit(self,d):
        x=self.design(d,True);y=d.target.to_numpy();w=(1/d.groupby('date').date.transform('size')).to_numpy();w/=w.mean()
        self.tail_cut=np.quantile(y,[.1,.9]).tolist();self.fit_end=d.end_date.max()
        if self.config['loss']=='tail':w=w*(1+2*((y<=self.tail_cut[0])|(y>=self.tail_cut[1])));w/=w.mean()
        self.model=Ridge(alpha=300).fit(x,y,sample_weight=w);self.iterations=0;self.converged=True
        if self.config['loss']=='huber':
            initial=y-self.model.predict(x);self.huber_scale=max(float(np.median(abs(initial-np.median(initial)))/.67448975),.1)
            delta=1.35*self.huber_scale;self.converged=False
            for i in range(30):
                residual=y-self.model.predict(x);robust=np.minimum(1.,delta/np.maximum(abs(residual),1e-12))
                previous=self.model.predict(x);m=Ridge(alpha=300).fit(x,y,sample_weight=w*robust)
                change=float(np.max(abs(m.predict(x)-previous)));self.model=m;self.iterations=i+1
                if change<1e-4:self.converged=True;break
        assert np.isfinite(self.model.coef_).all()
        return self
    def predict(self,d):return self.model.predict(self.design(d))
    def slopes(self,d):
        z=d.copy();z[SHOCKS]=0;b=self.predict(z);slopes=[]
        for s in SHOCKS:
            q=z.copy();q[s]=1;slopes.append(self.predict(q)-b)
        return np.column_stack(slopes)
    def slope_parts(self,row,shock):
        j=self.columns.index(shock);k=SHOCKS.index(shock);a=self.assets.index(row.asset)
        common=float(self.model.coef_[j]/self.scaler.scale_[j])
        offset=len(self.columns)+len(self.assets)+a*len(SHOCKS)+k
        deviation=float(self.model.coef_[offset]/np.sqrt(10)/self.scaler.scale_[j]);state=0.
        if self.config['gates']:
            for c in ['market_trend20','market_vol20']:
                gate=np.tanh((row[c]-self.gate_mean[c])/self.gate_scale[c]);ix=self.columns.index(shock+'__'+c)
                state+=float(self.model.coef_[ix]*gate/self.scaler.scale_[ix])
        return dict(shared_coefficient=common,asset_deviation=deviation,state_interaction=state)

def score(d,p):
    z=d[['date','target']].copy();z['error']=abs(z.target-p)
    return float(z.groupby('date').error.mean().mean())

def main():
    OUT.mkdir(exist_ok=True)
    cfg=json.loads((ROOT/'locked_protocol.json').read_text());b=joblib.load(ROOT/'final_service_bundle.joblib')
    data=pd.read_parquet(ROOT/'corrected_features.parquet');previous=pd.read_parquet(ROOT/'rebuilt_predictions.parquet')
    protected=[ROOT/'final_service_bundle.joblib',ROOT/'corrected_features.parquet',Path('reports/support_expansion_20261104/research_input.parquet')]
    hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in protected}
    protocol=dict(configs=CONFIGS,alpha=300,deviation_scale=10,loss_notes='Tail weights are 3x on training-only 10/90% target tails. Huber scale fixed from training residual MAD. No test target used for weights or gates.',
        gates='tanh of training-standardized confirmed trend/volatility; shock response remains additive and linear in shock at a fixed state',
        selection='Previous year served-stock date MAE at least 1% better and crash underestimation <= baseline*1.05; otherwise baseline. Nonconverged Huber cannot be selected.',
        outer_evaluation='Same 4150 rows, 20-day boundary; repeatedly used development data, not blind',source_hashes=hashes,production_changed=False)
    (OUT/'protocol.json').write_text(json.dumps(protocol,indent=2),encoding='utf8')
    rows=[];scores=[];choices=[];coef=[];checks=[];splits=[]
    for group in ['primary','expanded']:
        f=data[data.asset.isin(cfg['cohorts'][group]['assets'])]
        served={a for a,t in b['tiers'].items() if t=='quantitative_candidate'}
        wanted=served&set(b['primary']['support']) if group=='primary' else served-set(b['primary']['support'])
        for year in cfg['folds']:
            tr=training(f,pd.Timestamp(year-1,1,1));cal=anchors(training(f[f.date>=pd.Timestamp(year-1,1,1)],pd.Timestamp(year,1,1)));cal=cal[cal.asset.isin(wanted)]
            old=previous[(previous.group==group)&(previous.year==year)]
            te=old[['date','asset']].merge(f,on=['date','asset'],validate='one_to_one')
            assert tr.end_date.max()<cal.date.min() and cal.end_date.max()<te.date.min()
            z=te[['date','end_date','asset','target']].rename(columns={'target':'actual'}).copy();z['group']=group;z['year']=year;z['zero']=0.;z['sector']=old.sector_center.to_numpy()
            eligible=[];models={}
            for config in CONFIGS:
                m=ConditionalFactor(config).fit(tr);yp=m.predict(te);cp=m.predict(cal);name=config['name'];models[name]=m
                if name=='baseline':
                    np.testing.assert_allclose(yp,old.center,atol=1e-9)
                    base_mae=score(cal,cp);base_crash=stats(cal.target,cp)['crash_underestimate_pp']
                z[name]=yp;s=stats(cal.target,cp)
                ok=m.converged and (name=='baseline' or (score(cal,cp)<=base_mae*.99 and (base_crash is None or s['crash_underestimate_pp'] is None or s['crash_underestimate_pp']<=base_crash*1.05)))
                item=dict(group=group,year=year,model=name,date_mae=score(cal,cp),eligible=ok,**s);scores.append(item)
                if ok:eligible.append(item)
                q=te.drop_duplicates('asset').copy();q[SHOCKS]=0;beta=m.slopes(q)
                extreme=q.copy();extreme[SHOCKS]=[10,200,30,20]
                np.testing.assert_allclose(m.predict(q)+(beta*np.array([10,200,30,20])).sum(1),m.predict(extreme),atol=1e-8)
                for i,(_,r) in enumerate(q.iterrows()):
                    for j,sname in enumerate(SHOCKS):coef.append(dict(group=group,year=year,model=name,asset=r.asset,shock=sname,coefficient=beta[i,j],state_date=str(r.date)))
                checks.append(dict(group=group,year=year,model=name,iterations=m.iterations,converged=m.converged,training_rows=len(tr),tail_cut=m.tail_cut))
                print('loss fold',group,year,name,'iterations',m.iterations,flush=True)
            selected=min(eligible,key=lambda r:(r['date_mae'],r['model']))['model'];z['selected']=z[selected];rows.append(z)
            choices.append(dict(group=group,year=year,selected=selected,calibration_dates=cal.date.nunique()))
            splits.append(dict(group=group,year=year,training_label_end=str(tr.end_date.max()),validation_start=str(cal.date.min()),validation_end=str(cal.end_date.max()),test_start=str(te.date.min())))
            pd.DataFrame(scores).to_csv(OUT/'inner_validation.csv',index=False)
    p=pd.concat(rows);p.to_parquet(OUT/'predictions.parquet',index=False);methods=['baseline','selected','huber','tail','gated','gated_huber','gated_tail','zero','sector'];metrics=[];stock=[]
    for period,z in [('all',p),('2025_2026',p[p.year>=2025])]+[(str(y),z) for y,z in p.groupby('year')]:
        for m in methods:metrics.append(dict(period=period,model=m,dates=z.date.nunique(),**stats(z.actual,z[m])))
    for (year,a),z in p.groupby(['year','asset']):
        for m in methods:stock.append(dict(year=year,asset=a,name=b['names'][a],model=m,**stats(z.actual,z[m])))
    pd.DataFrame(metrics).to_csv(OUT/'metrics.csv',index=False);pd.DataFrame(stock).to_csv(OUT/'stock_metrics.csv',index=False);pd.DataFrame(coef).to_csv(OUT/'coefficients.csv',index=False)
    for name,value in [('choices.json',choices),('fit_checks.json',checks),('splits.json',splits),('uncertainty.json',{label:{m:block_ci(z,m) for m in methods[1:7]} for label,z in [('all',p),('recent',p[p.year>=2025])]})]:
        (OUT/name).write_text(json.dumps(value,indent=2),encoding='utf8')
    assert len(p)==len(previous) and set(zip(p.date,p.asset))==set(zip(previous.date,previous.asset))
    assert all(hashlib.sha256(Path(k).read_bytes()).hexdigest()==v for k,v in hashes.items())
    (OUT/'verification.json').write_text(json.dumps(dict(passed=True,baseline_reproduced=True,identical_test_rows=True,inputs_unchanged=True,additive_shock_identity=True,selection_not_using_outer_answers=True),indent=2),encoding='utf8')
    print(pd.DataFrame(metrics).query('period in ["all","2025_2026"]').to_string(index=False),flush=True)

if __name__=='__main__':
    with threadpool_limits(limits=2):main()
