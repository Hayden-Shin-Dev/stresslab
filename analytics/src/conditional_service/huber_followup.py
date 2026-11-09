"""Fixed follow-up of Huber failures with chronological validation."""
import hashlib,json
from pathlib import Path
import joblib,numpy as np,pandas as pd
from sklearn.linear_model import Ridge
from threadpoolctl import threadpool_limits
from .conditional_loss_research import ConditionalFactor
from .core import STATE,ASSET,SHOCKS,anchors
from .finalize_model import stats
from .rebuild_fixed_model import training
from .diagnose_recent import block_ci

ROOT=Path('reports/service_scope_20261105');OUT=Path('reports/huber_followup_20261105')
CONFIGS=[dict(name='huber',delta=1.35,normalize=False,stock_states=False),
 dict(name='delta075',delta=.75,normalize=False,stock_states=False),
 dict(name='delta2',delta=2.,normalize=False,stock_states=False),
 dict(name='stock_states',delta=1.35,normalize=False,stock_states=True),
 dict(name='vol_normalized',delta=1.35,normalize=True,stock_states=False),
 dict(name='vol_stock_states',delta=1.35,normalize=True,stock_states=True),
 dict(name='vol_norm_alpha30',delta=1.35,normalize=True,stock_states=False,alpha=30)]

class HuberFollowup(ConditionalFactor):
    def __init__(self,config):super().__init__(dict(config,gates=False,loss='huber'))
    def design(self,d,fit=False):
        z=super().design(d,fit)
        if self.config['stock_states']:
            one=np.eye(len(self.assets))[[self.assets.index(a) for a in d.asset]]/np.sqrt(30)
            state=z[:,[self.columns.index(c) for c in ['asset_trend5','asset_trend20','drawdown60']]]
            z=np.column_stack([z,(one[:,:,None]*state[:,None,:]).reshape(len(d),-1)])
        return z
    def fit(self,d):
        x=self.design(d,True);scale=d.scale.to_numpy() if self.config['normalize'] else np.ones(len(d));y=d.target.to_numpy()/scale
        w=(1/d.groupby('date').date.transform('size')).to_numpy();w/=w.mean();alpha=self.config.get('alpha',300)
        self.model=Ridge(alpha=alpha).fit(x,y,sample_weight=w)
        initial=y-self.model.predict(x);self.huber_scale=max(float(np.median(abs(initial-np.median(initial)))/.67448975),.1)
        delta=self.config['delta']*self.huber_scale;self.converged=False
        for i in range(40):
            residual=y-self.model.predict(x);robust=np.minimum(1.,delta/np.maximum(abs(residual),1e-12));previous=self.model.predict(x)
            self.model=Ridge(alpha=alpha).fit(x,y,sample_weight=w*robust);self.iterations=i+1
            if np.max(abs(self.model.predict(x)-previous))<1e-4:self.converged=True;break
        self.fit_end=d.end_date.max()
        assert np.isfinite(self.model.coef_).all()
        return self
    def predict(self,d):
        v=self.model.predict(self.design(d))
        return v*d.scale.to_numpy() if self.config['normalize'] else v
    def slope_parts(self,row,shock):
        p=super().slope_parts(row,shock)
        return {k:v*row.scale for k,v in p.items()} if self.config['normalize'] else p

def date_mae(d,p):
    z=d[['date','target']].copy();z['error']=abs(z.target-p);return float(z.groupby('date').error.mean().mean())

def date_direction(d,p):
    z=d[['date','target']].copy();z['correct']=np.sign(z.target)==np.sign(p);return float(z.groupby('date').correct.mean().mean())

def main():
    OUT.mkdir(exist_ok=True)
    b=joblib.load(ROOT/'final_service_bundle.joblib');cfg=json.loads((ROOT/'locked_protocol.json').read_text())
    f=pd.read_parquet(ROOT/'corrected_features.parquet');old=pd.read_parquet('reports/conditional_loss_20261105/predictions.parquet')
    paths=[ROOT/'final_service_bundle.joblib',ROOT/'corrected_features.parquet',Path('reports/robust_candidate_20261105/final_service_bundle.joblib'),Path('reports/support_expansion_20261104/research_input.parquet')]
    hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    protocol=dict(configs=CONFIGS,selection='Previous calendar year on served stocks: date MAE >=1% improvement, crash underestimate not worse than Huber, direction no worse by >1pp; otherwise Huber. Only converged fits eligible.',
        normalized_target='target / pre-shock scale (20/60d volatility); predicted units multiplied back. No future volatility and no interval expansion.',
        stock_state_features=['asset_trend5','asset_trend20','drawdown60'],stock_state_deviation_penalty=30,
        evaluation='Identical 4150 rows; development not blind. Embargo20 calendar days.',source_hashes=hashes)
    (OUT/'protocol.json').write_text(json.dumps(protocol,indent=2),encoding='utf8')
    rows=[];scores=[];choices=[];checks=[];splits=[];states=[]
    for group in ['primary','expanded']:
        data=f[f.asset.isin(cfg['cohorts'][group]['assets'])]
        served={a for a,t in b['tiers'].items() if t=='quantitative_candidate'}
        wanted=served&set(b['primary']['support']) if group=='primary' else served-set(b['primary']['support'])
        for year in cfg['folds']:
            tr=training(data,pd.Timestamp(year-1,1,1));cal=anchors(training(data[data.date>=pd.Timestamp(year-1,1,1)],pd.Timestamp(year,1,1)));cal=cal[cal.asset.isin(wanted)]
            ref=old[(old.group==group)&(old.year==year)];te=ref[['date','asset']].merge(data,on=['date','asset'],validate='one_to_one')
            assert tr.end_date.max()<cal.date.min() and cal.end_date.max()<te.date.min()
            z=te[['date','end_date','asset','target','market_trend20','market_vol20','scale']].rename(columns={'target':'actual'}).copy()
            z['high_vol']=te.market_vol20>tr.market_vol20.quantile(.75);z['year']=year;z['group']=group;z['ridge']=ref.baseline.to_numpy();z['zero']=0.;z['sector']=ref.sector.to_numpy()
            eligible=[]
            for config in CONFIGS:
                m=HuberFollowup(config).fit(tr);cp=m.predict(cal);yp=m.predict(te);name=config['name']
                z[name]=yp;s=stats(cal.target,cp);mae=date_mae(cal,cp);direction=date_direction(cal,cp)
                if name=='huber':
                    np.testing.assert_allclose(yp,ref.huber,atol=1e-9);baseline=(mae,s['crash_underestimate_pp'],direction)
                ok=m.converged and (name=='huber' or (mae<=baseline[0]*.99 and (baseline[1] is None or s['crash_underestimate_pp'] is None or s['crash_underestimate_pp']<=baseline[1]) and direction>=baseline[2]-.01))
                record=dict(group=group,year=year,model=name,date_mae=mae,date_direction=direction,eligible=ok,**s);scores.append(record)
                if ok:eligible.append(record)
                q=te.drop_duplicates('asset').copy();q[SHOCKS]=0;beta=m.slopes(q);x=q.copy();x[SHOCKS]=[5,100,10,5]
                np.testing.assert_allclose(m.predict(q)+(beta*np.array([5,100,10,5])).sum(1),m.predict(x),atol=1e-8)
                for i,(_,r) in enumerate(q.iterrows()):
                    for j,shock in enumerate(SHOCKS):np.testing.assert_allclose(sum(m.slope_parts(r,shock).values()),beta[i,j],atol=1e-8)
                checks.append(dict(group=group,year=year,model=name,iterations=m.iterations,converged=m.converged,train_rows=len(tr)))
                print('Huber followup',group,year,name,m.iterations,flush=True)
            selected=min(eligible,key=lambda r:(r['date_mae'],r['model']))['model'];z['selected']=z[selected];z['baseline']=z.huber;rows.append(z)
            choices.append(dict(group=group,year=year,selected=selected,validation_dates=cal.date.nunique()))
            splits.append(dict(group=group,year=year,train_end=str(tr.end_date.max()),cal_start=str(cal.date.min()),cal_end=str(cal.end_date.max()),test_start=str(te.date.min())))
            pd.DataFrame(scores).to_csv(OUT/'inner_validation.csv',index=False)
    p=pd.concat(rows);p.to_parquet(OUT/'predictions.parquet',index=False);metrics=[];stocks=[]
    methods=['ridge','huber','selected']+[c['name'] for c in CONFIGS[1:]]+['zero','sector']
    for period,z in [('all',p),('2025_2026',p[p.year>=2025])]+[(str(y),z) for y,z in p.groupby('year')]:
        for name in methods:metrics.append(dict(period=period,model=name,dates=z.date.nunique(),**stats(z.actual,z[name])))
    for (year,a),z in p.groupby(['year','asset']):
        for name in methods:stocks.append(dict(year=year,asset=a,name=b['names'][a],model=name,**stats(z.actual,z[name])))
    for label,z in [('high_vol',p[p.high_vol]),('normal_vol',p[~p.high_vol]),('prior_uptrend',p[p.market_trend20>=0]),('prior_downtrend',p[p.market_trend20<0])]:
        for name in methods:states.append(dict(state=label,model=name,dates=z.date.nunique(),**stats(z.actual,z[name])))
    pd.DataFrame(metrics).to_csv(OUT/'metrics.csv',index=False);pd.DataFrame(stocks).to_csv(OUT/'stock_metrics.csv',index=False);pd.DataFrame(states).to_csv(OUT/'state_metrics.csv',index=False)
    for name,v in [('choices.json',choices),('fit_checks.json',checks),('splits.json',splits),('uncertainty.json',{period:{m:block_ci(z,m) for m in methods if m not in ['huber','zero','sector','ridge']} for period,z in [('all',p),('recent',p[p.year>=2025])]})]:
        (OUT/name).write_text(json.dumps(v,indent=2),encoding='utf8')
    assert len(p)==len(old) and set(zip(p.date,p.asset))==set(zip(old.date,old.asset))
    assert all(hashlib.sha256(Path(k).read_bytes()).hexdigest()==v for k,v in hashes.items())
    (OUT/'verification.json').write_text(json.dumps(dict(passed=True,huber_reproduced=True,additive_contributions_match=True,outer_rows_unchanged=True,source_hashes_unchanged=True,azure_gold_changed=False),indent=2),encoding='utf8')
    print(pd.DataFrame(metrics).query('period in ["all","2025_2026"]').to_string(index=False),flush=True)

if __name__=='__main__':
    with threadpool_limits(limits=2):main()
