"""Matched center/interval ablation with forward-only factor residual targets."""
import json
import numpy as np
import pandas as pd
import joblib
from catboost import CatBoostRegressor
from pooled_stress_core_20261104 import ROOT, OUT as PREV, ASSETS, FEATURES, SHOCKS, INTER, prepare, weights, point_score, interval_score
from crash_cases_center_20261104 import inputs, DOM
from service_candidate_20261104 import components

OUT=ROOT/'reports/crash_separation_20261104'
def matrix(d,cols):
    return np.column_stack([d[cols].fillna(0).to_numpy(),np.eye(len(ASSETS))[[ASSETS.index(a) for a in d.asset]]])
def zero(d):
    z=d.copy();z[SHOCKS]=0;z[INTER]=0;return z
def scores(z):return {**point_score(z),**interval_score(z)}
def main():
    OUT.mkdir(exist_ok=True);(OUT/'folds').mkdir(exist_ok=True)
    protocol={'selection':'2020/2021 development only. No evaluation choice. All20 assets retained.',
        'experiments':['baseline','center_only_same_width','interval_only','center_and_interval'],
        'features':['Gold18','Gold18+10 backward domestic features'],
        'learning':'Fixed CatBoost MultiQuantile .1/.5/.9,150 trees depth3 lr.04. Annual forward OOF errors of neutral anchored factor, never in-sample errors.',
        'calibration':'Separate previous calendar year nonoverlap targets; endpoint residual quantiles10/90. No width cap, no crash oversampling.',
        'evaluation':'Reused 2023-2026 research, not blind. Actual future shocks retrospective conditions, not causal effects.',
        'gate':'joint-support gate applies to nonlinear quantiles; outside support remains exploratory',
        'limits':'Missing original publication timestamps/revision vintages; current20 survivorship; 19-stock breadth is not KOSPI breadth.',
        'azure_changed':False,'gold_changed':False,'production_promoted':False}
    (OUT/'protocol.json').write_text(json.dumps(protocol,indent=2))
    d,g=prepare();dom=inputs()[['asset','date']+DOM+['diagnostic_only_future_market5']]
    d=d.merge(dom,on=['asset','date'],validate='one_to_one')
    oof=[]
    for path in sorted((PREV/'factor_cache').glob('*.parquet')):
        q=pd.read_parquet(path);m=joblib.load(path.with_suffix('.joblib'))
        q['neutral_oof']=q.factor_oof-m.predict(zero(q))
        q['neutral_error']=q.target/q.scale-q.neutral_oof
        oof.append(q)
    oof=pd.concat(oof,ignore_index=True).merge(dom,on=['asset','date'],validate='one_to_one')
    audits=[];allrows=[]
    for year in [2020,2021,2023,2024,2025,2026]:
        pack=joblib.load(PREV/'folds'/f'{year}_models.joblib');data={};base={}
        for split,suffix in [('test','points'),('cal','calibration')]:
            r=pd.read_parquet(PREV/'folds'/f'{year}_{suffix}.parquet');r=r[r.model=='catboost']
            f=r[['asset','date','regime']].merge(d,on=['asset','date'],validate='one_to_one');data[split]=f
            base[split]=components(f,pack)[1]
        te=data['test'];cal=data['cal'];qbase=np.quantile((cal.target-base['cal'])/cal.scale,[.1,.9])
        b=te[['asset','date','end_date','sector','regime','scale','target']].rename(columns={'target':'actual'}).copy()
        b['fold']=year;b['model']='baseline';b['center']=base['test'];b['lo']=b.center+qbase[0]*b.scale;b['hi']=b.center+qbase[1]*b.scale
        allrows.append(b)
        cut=pd.Timestamp(year-1,1,1)-pd.Timedelta(days=20)
        train=oof[(oof.end_date<cut)&oof.asset.isin(te.asset.unique())].copy()
        assert (train.oof_train_label_end<train.date).all()
        assert train.end_date.max()<cal.date.min() and cal.end_date.max()<te.date.min()
        for feature_set,cols in [('gold',FEATURES),('domestic',FEATURES+DOM)]:
            model=CatBoostRegressor(iterations=150,depth=3,learning_rate=.04,loss_function='MultiQuantile:alpha=0.1,0.5,0.9',random_seed=20261104,thread_count=4,verbose=False,allow_writing_files=False)
            model.fit(matrix(train,cols),train.neutral_error,sample_weight=weights(train))
            qq={}
            for split,f in data.items():
                gate,_,_=pack['support'].inspect(f)
                qq[split]=np.sort(model.predict(matrix(f,cols)),axis=1)*gate[:,None]
            # Calibrate endpoints separately on held-out calibration labels.
            cr=(cal.target.to_numpy()-base['cal'])/cal.scale.to_numpy()
            adjust=np.array([np.quantile(cr-qq['cal'][:,0],.1),np.quantile(cr-qq['cal'][:,2],.9)])
            lower=base['test']+(qq['test'][:,0]+adjust[0])*te.scale.to_numpy()
            upper=base['test']+(qq['test'][:,2]+adjust[1])*te.scale.to_numpy()
            crossing=int((lower>upper).sum());lo=np.minimum(lower,upper);hi=np.maximum(lower,upper)
            for policy in ['center_only','interval_only','both']:
                z=b.copy();z['model']=feature_set+'_'+policy
                if policy!='interval_only':
                    shift=qq['test'][:,1]*te.scale.to_numpy();z['center']=b.center+shift
                    if policy=='center_only':z['lo']=b.lo+shift;z['hi']=b.hi+shift
                if policy!='center_only':z['lo']=lo;z['hi']=hi
                if policy=='center_only':np.testing.assert_allclose(z.hi-z.lo,b.hi-b.lo)
                allrows.append(z)
            model.save_model(str(OUT/'folds'/f'{year}_{feature_set}.cbm'))
            audits.append(dict(fold=year,feature_set=feature_set,train_rows=len(train),train_dates=train.date.nunique(),train_label_end=str(train.end_date.max()),cal_rows=len(cal),cal_dates=cal.date.nunique(),cal_label_end=str(cal.end_date.max()),test_start=str(te.date.min()),endpoint_crossings=crossing,lower_adjust=adjust[0],upper_adjust=adjust[1]))
        print('fold complete',year,flush=True)
    r=pd.concat(allrows,ignore_index=True);r.to_parquet(OUT/'predictions.parquet',index=False)
    pd.DataFrame(audits).to_csv(OUT/'temporal_audit.csv',index=False)
    report(r,d)

def report(r,d):
    dev=r[r.fold<2023];ev=r[r.fold>=2023]
    for name,f in [('development',dev),('evaluation',ev)]:
        pd.DataFrame([dict(model=n,**scores(z)) for n,z in f.groupby('model')]).to_csv(OUT/f'{name}_metrics.csv',index=False)
    # Development decision must improve central AND tail losses without wider intervals.
    bs=scores(dev[dev.model=='baseline']);eligible=[]
    for n,z in dev.groupby('model'):
        s=scores(z)
        if n!='baseline' and s['mae']<=bs['mae'] and s['crash_mae']<bs['crash_mae'] and s['crash_lower_breach']<bs['crash_lower_breach'] and s['width80']<=bs['width80'] and s['interval_score80']<bs['interval_score80']:
            eligible.append((s['interval_score80'],n))
    selected=min(eligible)[1] if eligible else 'baseline'
    (OUT/'selection.json').write_text(json.dumps(dict(selected=selected,eligible=eligible,production_promoted=False),indent=2))
    slices=[]
    for n,z in ev.groupby('model'):
        for dim in ['asset','sector','regime','fold']:
            for key,f in z.groupby(dim):slices.append(dict(model=n,dimension=dim,group=str(key),**scores(f)))
    pd.DataFrame(slices).to_csv(OUT/'slices.csv',index=False)
    b=ev[ev.model=='baseline'].merge(d[['asset','date']+DOM+SHOCKS+['diagnostic_only_future_market5']],on=['asset','date'],validate='one_to_one')
    c=b[b.actual<=-5].copy();c['center_underestimate']=c.center-c.actual;c['downside_allowance']=c.center-c.lo;c['breach']=c.actual<c.lo
    c.sort_values('center_underestimate',ascending=False).to_csv(OUT/'crash_cases.csv',index=False)
    (OUT/'diagnosis.json').write_text(json.dumps(dict(crash_rows=len(c),breaches=int(c.breach.sum()),wrong_sign_centers=int((c.center>=0).sum()),lower_bound_above_crash_threshold=int((c.lo>=-5).sum()),breaches_with_lower_bound_above_threshold=int((c.breach&(c.lo>=-5)).sum()),mean_actual=c.actual.mean(),mean_center=c.center.mean(),mean_lower=c.lo.mean()),indent=2))
    # Date-month blocks keep cross-stock dependence together.
    cis=[];rng=np.random.default_rng(20261104)
    def losses(z):
        a=z.actual;p=z.center;l=z.lo;h=z.hi
        return pd.DataFrame({'asset':z.asset,'date':z.date,'ae':abs(a-p),'is':h-l+10*(l-a).clip(lower=0)+10*(a-h).clip(lower=0),'breach':((a<l)&(a<=-5)).astype(int),'crash':(a<=-5).astype(int)})
    bl=losses(ev[ev.model=='baseline'])
    for n,z in ev.groupby('model'):
        if n=='baseline':continue
        v=losses(z).merge(bl,on=['asset','date'],suffixes=('','_base'),validate='one_to_one');v['month']=v.date.dt.to_period('M').astype(str)
        for metric,denom in [('ae',None),('is',None),('breach','crash')]:
            v['gain']=v[metric+'_base']-v[metric];v['denom']=1 if denom is None else v[denom]
            agg=v.groupby('month')[['gain','denom']].sum();idx=rng.integers(0,len(agg),(2000,len(agg)))
            vals=agg.gain.to_numpy()[idx].sum(1)/agg.denom.to_numpy()[idx].sum(1)
            cis.append(dict(model=n,metric=metric,gain=v.gain.sum()/v.denom.sum(),low95=np.quantile(vals,.025),high95=np.quantile(vals,.975),blocks=len(agg)))
    pd.DataFrame(cis).to_csv(OUT/'monthly_block_ci.csv',index=False)
    print('complete',selected,flush=True)
if __name__=='__main__':main()


