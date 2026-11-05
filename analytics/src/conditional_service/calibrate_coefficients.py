"""Learn additive coefficient corrections from earlier out-of-sample errors.

No outer returns select corrections. Existing source inputs and service stay frozen.
"""
import hashlib,json
from pathlib import Path
import joblib,numpy as np,pandas as pd
from sklearn.linear_model import Ridge
from threadpoolctl import threadpool_limits
from .core import SHOCKS,anchors
from .finalize_model import BoundedFactor,stats
from .rebuild_fixed_model import training
from .diagnose_recent import block_ci

ROOT=Path('reports/service_scope_20261105')
OUT=Path('reports/coefficient_calibration_20261105')
CONFIG=dict(alpha=300,dev=10,years=None)
MODES=['baseline','shocks','both']

class CoefficientCorrection:
    def __init__(self,mode,alpha):self.mode=mode;self.alpha=alpha
    def fit(self,d):
        self.cols=(['baseline_zero'] if self.mode in ['baseline','both'] else [])+(['contrib_'+s for s in SHOCKS] if self.mode in ['shocks','both'] else [])
        x=d[self.cols].to_numpy();self.mean=x.mean(0);self.scale=np.maximum(x.std(0),1e-8)
        z=np.column_stack([np.ones(len(x)),(x-self.mean)/self.scale])
        # Each date carries total weight 1, irrespective of stock count.
        w=1/d.groupby('date').date.transform('size')
        self.model=Ridge(alpha=self.alpha,fit_intercept=False).fit(z,d.actual-d.center,sample_weight=w)
        self.delta=self.model.coef_[1:]/self.scale
        self.bias=float(self.model.coef_[0]-self.mean@self.delta)
        return self
    def predict(self,d):return d.center.to_numpy()+self.bias+d[self.cols].to_numpy()@self.delta
    def parameters(self):return dict(bias_pp=self.bias,multipliers={c:float(1+v) for c,v in zip(self.cols,self.delta)})

def components(m,q):
    z=q[['date','end_date','asset','target']].rename(columns={'target':'actual'}).copy()
    zero=q.copy();zero[SHOCKS]=0;z['baseline_zero']=m.predict(zero);z['center']=m.predict(q)
    beta=m.slopes(q)
    for j,s in enumerate(SHOCKS):z['contrib_'+s]=beta[:,j]*q[s].to_numpy()
    np.testing.assert_allclose(z.baseline_zero+z[['contrib_'+s for s in SHOCKS]].sum(1),z.center,atol=1e-9)
    return z

def score(d,p):
    z=d[['date','actual']].copy();z['error']=abs(z.actual-p)
    return float(z.groupby('date').error.mean().mean())

def main():
    OUT.mkdir(exist_ok=True)
    b=joblib.load(ROOT/'final_service_bundle.joblib');cfg=json.loads((ROOT/'locked_protocol.json').read_text())
    f=pd.read_parquet(ROOT/'corrected_features.parquet');old=pd.read_parquet(ROOT/'rebuilt_predictions.parquet')
    candidates=[(m,a) for m in MODES for a in [10,100,1000]]
    hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in [ROOT/'final_service_bundle.joblib',ROOT/'corrected_features.parquet',Path('reports/support_expansion_20261104/research_input.parquet')]}
    protocol=dict(candidate_modes=MODES,alphas=[10,100,1000],calibration='Three preceding years of out-of-sample predictions from same two-year-lag fitting policy; first two select on third, then refit correction on all three',
        selection='Date-balanced MAE, >=1% improvement over unchanged center and crash underestimation <= unchanged*1.05; otherwise unchanged',
        outer_keys='Exact existing 4150 rows',shared_correction_per_cohort=True,dates_are_weight_units=True,source_hashes=hashes,independent_blind=False,azure_gold_changed=False)
    (OUT/'protocol.json').write_text(json.dumps(protocol,indent=2),encoding='utf8')
    preds=[];selections=[];validation=[];coefs=[];splits=[];oos=[]
    for group in ['primary','expanded']:
        data=f[f.asset.isin(cfg['cohorts'][group]['assets'])]
        served={a for a,t in b['tiers'].items() if t=='quantitative_candidate'}
        wanted=served&set(b['primary']['support']) if group=='primary' else served-set(b['primary']['support'])
        cache={}
        for year in range(2020,2027):
            tr=training(data,pd.Timestamp(year-1,1,1))
            m=BoundedFactor(CONFIG,b['sectors']).fit(tr)
            q=anchors(training(data[(data.date>=pd.Timestamp(year,1,1))&(data.date<pd.Timestamp(year+1,1,1))],pd.Timestamp(year+1,1,1)))
            q=q[q.asset.isin(wanted&set(m.assets))]
            assert tr.end_date.max()<q.date.min()
            z=components(m,q);z['group']=group;z['year']=year;cache[year]=(m,z);oos.append(z)
        for year in cfg['folds']:
            cal=pd.concat([cache[y][1] for y in range(year-3,year)])
            boundary=pd.Timestamp(year-1,1,1)
            early=cal[cal.end_date<boundary-pd.Timedelta(days=20)];late=cal[cal.date>=boundary]
            assert early.end_date.max()<late.date.min() and late.end_date.max()<pd.Timestamp(year,1,1)
            base_mae=score(late,late.center);base_crash=stats(late.actual,late.center)['crash_underestimate_pp'];allowed=[]
            for mode,alpha in candidates:
                corr=CoefficientCorrection(mode,alpha).fit(early);yp=corr.predict(late);s=stats(late.actual,yp)
                good=score(late,yp)<=base_mae*.99 and (base_crash is None or s['crash_underestimate_pp'] is None or s['crash_underestimate_pp']<=base_crash*1.05)
                item=dict(group=group,year=year,mode=mode,alpha=alpha,date_mae=score(late,yp),eligible=good,**s)
                validation.append(item)
                if good:allowed.append(item)
            choice=min(allowed,key=lambda v:(v['date_mae'],v['mode'],v['alpha'])) if allowed else None
            keys=old[(old.group==group)&(old.year==year)][['date','asset']]
            q=keys.merge(data,on=['date','asset'],validate='one_to_one');m=cache[year][0]
            z=components(m,q);z['baseline']=z.center;z['group']=group;z['year']=year
            ref=keys.merge(old,on=['date','asset'],validate='one_to_one')
            np.testing.assert_allclose(z.center,ref.center,atol=1e-9)
            z['zero']=0.;z['sector']=ref.sector_center.to_numpy()
            for mode,alpha in candidates:
                corr=CoefficientCorrection(mode,alpha).fit(cal);name=f'{mode}_{alpha}'
                z[name]=corr.predict(z);params=corr.parameters()
                reconstructed=np.full(len(z),params['bias_pp'])+z.baseline_zero.to_numpy()*params['multipliers'].get('baseline_zero',1.)
                for s in SHOCKS:reconstructed+=z['contrib_'+s].to_numpy()*params['multipliers'].get('contrib_'+s,1.)
                np.testing.assert_allclose(reconstructed,z[name],atol=1e-9)
                coefs.append(dict(group=group,year=year,name=name,calibration_dates=cal.date.nunique(),**params))
                if choice and mode==choice['mode'] and alpha==choice['alpha']:selected_name=name
            selected_name=selected_name if choice else 'baseline'
            z['selected']=z[selected_name];preds.append(z)
            selections.append(dict(group=group,year=year,selected=selected_name,early_dates=early.date.nunique(),validation_dates=late.date.nunique(),all_calibration_dates=cal.date.nunique()))
            splits.append(dict(group=group,year=year,early_label_end=str(early.end_date.max()),validation_start=str(late.date.min()),validation_end=str(late.end_date.max()),test_start=str(q.date.min()),test_n=len(q)))
            print('coefficient correction',group,year,selected_name,flush=True)
    p=pd.concat(preds);p.to_parquet(OUT/'predictions.parquet',index=False);pd.concat(oos).to_parquet(OUT/'calibration_oos.parquet',index=False)
    methods=['baseline','selected','zero','sector']+[f'{m}_{a}' for m,a in candidates];metrics=[];stocks=[]
    for period,z in [('all',p),('2025_2026',p[p.year>=2025])]+[(str(y),z) for y,z in p.groupby('year')]:
        for m in methods:metrics.append(dict(period=period,model=m,dates=z.date.nunique(),**stats(z.actual,z[m])))
    for (year,a),z in p.groupby(['year','asset']):
        for m in ['baseline','selected']:stocks.append(dict(year=year,asset=a,name=b['names'][a],model=m,**stats(z.actual,z[m])))
    pd.DataFrame(metrics).to_csv(OUT/'metrics.csv',index=False);pd.DataFrame(stocks).to_csv(OUT/'stock_metrics.csv',index=False);pd.DataFrame(validation).to_csv(OUT/'inner_validation.csv',index=False)
    for name,value in [('choices.json',selections),('correction_parameters.json',coefs),('splits.json',splits),('uncertainty.json',{label:block_ci(z,'selected') for label,z in [('all',p),('recent',p[p.year>=2025])]})]:
        (OUT/name).write_text(json.dumps(value,indent=2),encoding='utf8')
    assert all(hashlib.sha256(Path(k).read_bytes()).hexdigest()==v for k,v in hashes.items())
    assert set(zip(p.date,p.asset))==set(zip(old.date,old.asset)) and len(p)==len(old)
    (OUT/'verification.json').write_text(json.dumps(dict(passed=True,contribution_identity=True,unchanged_input_hashes=True,identical_outer_keys=True,selection_not_using_outer_answers=True),indent=2),encoding='utf8')
    print(pd.DataFrame(metrics).query('period in ["all", "2025_2026"] and model in ["baseline","selected","zero","sector"]').to_string(index=False),flush=True)

def scenario_with_correction(baseline,coefficients,shocks,parameters):
    """Research candidate arithmetic; never mutates a service response or model."""
    multipliers=parameters.get('multipliers',{})
    base=parameters.get('bias_pp',0.)+baseline*multipliers.get('baseline_zero',1.)
    beta={s:coefficients[s]*multipliers.get('contrib_'+s,1.) for s in SHOCKS}
    terms={s:beta[s]*shocks.get(s,0.) for s in SHOCKS}
    return dict(baseline_return_pct=base,sensitivities=beta,contributions_pp=terms,
                scenario_return_pct=base+sum(terms.values()),change_pp=sum(terms.values()))

if __name__=='__main__':
    with threadpool_limits(limits=2):main()
