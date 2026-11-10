"""Frozen-grid, chronological diagnosis of corrected-data Ridge performance.

Old unverified inputs are diagnostic controls only, never deployment candidates.
Outer evaluation dates are inherited verbatim from the previous 4,150 rows.
"""
import copy,hashlib,itertools,json,os
from pathlib import Path
import joblib,numpy as np,pandas as pd
from threadpoolctl import threadpool_limits
from .core import STATE,ASSET,SHOCKS,features,anchors
from .finalize_model import stats
from .regularized_factor import RegularizedFactor as BoundedFactor
from .rebuild_fixed_model import training

ROOT=Path('reports/service_scope_20261105')
PHASE=int(os.environ.get('STRESSLAB_DIAGNOSIS_PHASE','1'))
OUT=Path({1:'reports/recent_diagnosis_20261105',2:'reports/recent_regularization_20261105',3:'reports/recent_support_scope_20261105'}[PHASE])
BASE=dict(name='a300_d10_all',alpha=300,dev=10,years=None)
GRID=[dict(name=f'a{a}_d{d}_{y or "all"}',alpha=a,dev=d,years=y)
      for a,d,y in itertools.product([300,3000],[3,10,30],[None,5])]
if PHASE>=2:
    GRID += [dict(name=f'block_state{st}_shock{sh}',alpha=300,dev=10,years=None,state_penalty=st,shock_penalty=sh)
             for st,sh in itertools.product([10,100],[.1,1,10])]

def save(name,value):
    (OUT/name).write_text(json.dumps(value,ensure_ascii=False,indent=2,default=str),encoding='utf8')

def dated_score(d,p):
    z=d[['date','target']].copy();z['error']=abs(z.target-p)
    return float(z.groupby('date').error.mean().mean())

def block_ci(p,column,reference='baseline',seed=17):
    z=p.assign(delta=abs(p.actual-p[reference])-abs(p.actual-p[column])).groupby('date').delta.mean().sort_index().to_numpy()
    rng=np.random.default_rng(seed);v=[];n=len(z);length=4
    for _ in range(2000):
        ix=np.concatenate([(np.arange(length)+s)%n for s in rng.integers(n,size=(n+length-1)//length)])[:n]
        v.append(z[ix].mean())
    return dict(mean_mae_reduction_pp=float(z.mean()),ci95=np.quantile(v,[.025,.975]).tolist(),date_blocks=length,dates=n)

def main():
    OUT.mkdir(exist_ok=True)
    cfg=json.loads((ROOT/'locked_protocol.json').read_text())
    bundle=joblib.load(ROOT/'final_service_bundle.joblib')
    f=pd.read_parquet(ROOT/'corrected_features.parquet')
    previous=pd.read_parquet(ROOT/'rebuilt_predictions.parquet')
    gold=Path('reports/support_expansion_20261104/research_input.parquet')
    hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in [gold,ROOT/'final_service_bundle.joblib',ROOT/'corrected_features.parquet']}
    save('protocol.json',dict(configs=GRID,selection='Previous year date-balanced MAE with crash underestimation <= unchanged baseline*1.05; otherwise unchanged baseline. Outer scores never select configs.',
         evaluation='Exact previous date/asset keys, development walk-forward, not blind',
         refit_policy='Separate preregistered arm refits chosen config using all matured labels before evaluation year minus 20 days',
         validation_scope='Served stocks only; training pooling cohort unchanged' if PHASE==3 else 'Whole training cohort',
         phase=PHASE,causal_claim=False,source_hashes=hashes,changes_to_azure_gold=False))
    old=features(pd.read_parquet(gold)).dropna(subset=SHOCKS+['target','end_date'])
    rows=[];diagnosis=[];scores=[];choices=[];splits=[];coefs=[];failures=[]
    for group in ['primary','expanded']:
        assets=cfg['cohorts'][group]['assets'];data=f[f.asset.isin(assets)]
        olddata=old[old.asset.isin(assets)]
        for year in cfg['folds']:
            cutoff=pd.Timestamp(year,1,1)
            tr=training(data,pd.Timestamp(year-1,1,1))
            cal=anchors(training(data[data.date>=pd.Timestamp(year-1,1,1)],cutoff))
            if PHASE==3:
                served={a for a,t in bundle['tiers'].items() if t=='quantitative_candidate'}
                wanted=served&set(bundle['primary']['support']) if group=='primary' else served-set(bundle['primary']['support'])
                cal=cal[cal.asset.isin(wanted)]
            keys=previous[(previous.group==group)&(previous.year==year)][['date','asset']]
            te=keys.merge(data,on=['date','asset'],validate='one_to_one')
            assert len(te)==len(keys) and tr.end_date.max()<cal.date.min() and cal.end_date.max()<te.date.min()
            base=BoundedFactor(BASE,bundle['sectors']).fit(tr)
            bpred=base.predict(te);expected=keys.merge(previous,on=['date','asset'],validate='one_to_one').center
            np.testing.assert_allclose(bpred,expected,atol=1e-9)
            cp=base.predict(cal);base_crash=stats(cal.target,cp)['crash_underestimate_pp']
            models={};eligible=[]
            for config in GRID:
                m=base if config==BASE else BoundedFactor(config,bundle['sectors']).fit(tr)
                assert set(m.assets)==set(assets)
                pred=m.predict(cal);s=stats(cal.target,pred)
                allowed=base_crash is None or s['crash_underestimate_pp'] is None or s['crash_underestimate_pp']<=base_crash*1.05
                score=dict(group=group,year=year,config=config['name'],date_mae=dated_score(cal,pred),eligible=allowed,**s)
                scores.append(score);models[config['name']]=m
                if allowed:eligible.append(score)
            chosen=min(eligible,key=lambda x:(x['date_mae'],x['config']))['config']
            config=next(c for c in GRID if c['name']==chosen)
            selected=models[chosen];refitdata=training(data,cutoff)
            refit=BoundedFactor(config,bundle['sectors']).fit(refitdata)
            refreshed_base=BoundedFactor(BASE,bundle['sectors']).fit(refitdata)
            assert refit.fit_end<te.date.min()
            z=te[['date','end_date','asset','target',*STATE,*SHOCKS]].rename(columns={'target':'actual'}).copy()
            z['group']=group;z['year']=year;z['baseline']=bpred
            z['selected_fixed_train']=selected.predict(te);z['selected_refit']=refit.predict(te);z['baseline_refit']=refreshed_base.predict(te)
            z['zero']=0.;z['sector']=keys.merge(previous,on=['date','asset'],validate='one_to_one').sector_center.to_numpy()
            zero=te.copy();zero[SHOCKS]=0
            z['baseline_no_shock']=base.predict(zero);z['selected_no_shock']=refit.predict(zero)
            for j,s in enumerate(SHOCKS):
                z['base_contribution_'+s]=base.slopes(te)[:,j]*te[s].to_numpy()
                z['selected_contribution_'+s]=refit.slopes(te)[:,j]*te[s].to_numpy()
            np.testing.assert_allclose(z.baseline_no_shock+z[['base_contribution_'+s for s in SHOCKS]].sum(axis=1),z.baseline,atol=1e-8)
            rows.append(z)
            for name,m in [('baseline',base),('selected_fixed_train',selected),('selected_refit',refit),('baseline_refit',refreshed_base)]:
                for _,r in te.drop_duplicates('asset').iterrows():
                    for s in SHOCKS:coefs.append(dict(group=group,year=year,model=name,asset=r.asset,shock=s,coefficient=sum(m.slope_parts(r,s).values()),**m.slope_parts(r,s)))
            choices.append(dict(group=group,year=year,config=config,validation_dates=cal.date.nunique(),fit_label_end=str(refit.fit_end),fixed_train_label_end=str(selected.fit_end)))
            splits.append(dict(group=group,year=year,train_rows=len(tr),refit_rows=len(refitdata),cal_rows=len(cal),test_rows=len(te),train_end=str(tr.end_date.max()),cal_start=str(cal.date.min()),cal_end=str(cal.end_date.max()),test_start=str(te.date.min()),refit_end=str(refitdata.end_date.max())))
            # Sequential counterfactual decomposition on IDENTICAL evaluation rows.
            otr=olddata[olddata.end_date<pd.Timestamp(year-1,1,1)-pd.Timedelta(days=20)]
            matched=tr[['date','asset']].merge(otr,on=['date','asset'],validate='one_to_one')
            ote=te[['date','asset']].merge(olddata,on=['date','asset'],validate='one_to_one')
            assert len(matched)==len(tr) and len(ote)==len(te)
            np.testing.assert_allclose(ote.target,te.target)
            om=BoundedFactor(BASE,bundle['sectors']).fit(otr)
            mm=BoundedFactor(BASE,bundle['sectors']).fit(matched)
            states=ote.copy();states[STATE+ASSET]=te[STATE+ASSET].to_numpy()
            dz=te[['date','asset','target']].rename(columns={'target':'actual'}).copy();dz['year']=year;dz['group']=group
            dz['old_all']=om.predict(ote);dz['old_matched_rows']=mm.predict(ote)
            dz['corrected_train_old_input']=base.predict(ote)
            dz['corrected_state_old_shocks']=base.predict(states)
            dz['corrected_all']=bpred;diagnosis.append(dz)
            print('completed',group,year,chosen,flush=True)
            pd.DataFrame(scores).to_csv(OUT/'inner_validation.csv',index=False)
    p=pd.concat(rows,ignore_index=True);d=pd.concat(diagnosis,ignore_index=True);c=pd.DataFrame(coefs)
    p.to_parquet(OUT/'predictions.parquet',index=False);d.to_parquet(OUT/'data_ablation.parquet',index=False);c.to_csv(OUT/'coefficients.csv',index=False)
    save('choices.json',choices);save('splits.json',splits)
    methods=['baseline','selected_fixed_train','baseline_refit','selected_refit','zero','sector']
    metrics=[]
    for period,z in [('all',p),('2025_2026',p[p.year>=2025])]+[(str(y),z) for y,z in p.groupby('year')]:
        for method in methods:metrics.append(dict(period=period,model=method,dates=z.date.nunique(),**stats(z.actual,z[method])))
    pd.DataFrame(metrics).to_csv(OUT/'metrics.csv',index=False)
    stocks=[]
    for (year,a),z in p.groupby(['year','asset']):
        for m in methods:stocks.append(dict(year=year,asset=a,name=bundle['names'][a],model=m,**stats(z.actual,z[m])))
    pd.DataFrame(stocks).to_csv(OUT/'stock_metrics.csv',index=False)
    stages=['old_all','old_matched_rows','corrected_train_old_input','corrected_state_old_shocks','corrected_all'];effects=[]
    for (year,a),z in d.groupby(['year','asset']):
        r=dict(year=year,asset=a,name=bundle['names'][a],n=len(z))
        for s in stages:r[s+'_mae']=float(abs(z.actual-z[s]).mean())
        for left,right in zip(stages,stages[1:]):r[right+'_increment_mae']=r[right+'_mae']-r[left+'_mae']
        effects.append(r)
    pd.DataFrame(effects).to_csv(OUT/'data_effect_by_stock.csv',index=False)
    summary={s:stats(d.actual,d[s]) for s in stages}
    summary['recent']={s:stats(d[d.year>=2025].actual,d[d.year>=2025][s]) for s in stages}
    summary['interpretation']='Sequential operational decomposition; effects are path-dependent, not causal. Old inputs are uncertified diagnostic controls.'
    save('data_effect_summary.json',summary)
    stability=[]
    for (m,a,s),z in c.groupby(['model','asset','shock']):
        v=z.sort_values('year').coefficient.to_numpy();stability.append(dict(model=m,asset=a,name=bundle['names'][a],shock=s,folds=len(v),sign_changes=int((np.sign(v[1:])!=np.sign(v[:-1])).sum()),min=float(v.min()),max=float(v.max()),coefficient_cv=float(v.std()/max(abs(np.median(v)),1e-8))))
    pd.DataFrame(stability).to_csv(OUT/'coefficient_stability.csv',index=False)
    for a,z in p[p.year>=2025].groupby('asset'):
        w=z.assign(error=abs(z.actual-z.baseline)).nlargest(3,'error').copy();w['name']=bundle['names'][a];failures.append(w)
    pd.concat(failures).to_csv(OUT/'failure_cases.csv',index=False)
    save('uncertainty.json',{period:{m:block_ci(z,m) for m in methods[1:4]} for period,z in [('all',p),('recent',p[p.year>=2025])]})
    assert all(hashlib.sha256(Path(path).read_bytes()).hexdigest()==sha for path,sha in hashes.items())
    save('verification.json',dict(passed=True,identical_evaluation_keys=len(p)==len(previous) and set(zip(p.date,p.asset))==set(zip(previous.date,previous.asset)),baseline_reproduced=True,selection_uses_previous_year_only=True,labels_embargo_days=20,immutable_inputs_unchanged=True,independent_blind=False,azure_changed=False,gold_changed=False))
    print(pd.DataFrame(metrics).query('period == "2025_2026"').to_string(index=False),flush=True)

if __name__=='__main__':
    with threadpool_limits(limits=2):main()
