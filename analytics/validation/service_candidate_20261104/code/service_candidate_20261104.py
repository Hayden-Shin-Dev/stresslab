"""Service-oriented anchored factor research. No cloud/contract/production writes."""
import json
import numpy as np
import pandas as pd
import joblib
from pooled_stress_core_20261104 import ROOT,OUT as PREV,FEATURES,SHOCKS,INTER,prepare,point_score,interval_score

OUT=ROOT/'reports/service_candidate_20261104'

def components(frame,pack):
    zero=frame.copy();zero[SHOCKS]=0
    for c in INTER:zero[c]=0
    f0=pack['linear'].predict(zero)*zero.scale.to_numpy()
    delta=pack['linear'].predict(frame)*frame.scale.to_numpy()-f0
    c0=np.zeros(len(frame))
    for a in frame.asset.unique():
        mask=frame.asset.eq(a).to_numpy();c0[mask]=pack['individual'][a]['catboost'].predict(zero.loc[mask,FEATURES].to_numpy())*zero.loc[mask,'scale'].to_numpy()
    gate,ratio,outside=pack['support'].inspect(frame)
    return {'factor_reference':f0,'catboost_reference':c0,'zero_reference':np.zeros(len(frame))},delta,ratio,outside

def main():
    OUT.mkdir(exist_ok=True);d,g=prepare();point=[];bounds=[]
    policies=[(ref,w) for ref in ['factor_reference','catboost_reference','zero_reference'] for w in [.25,.5,1.]]
    protocol=dict(version='service_candidate_v1',purpose='Separate unchanged-shock reference from explicit factor scenario increment. Project candidate, not institution-grade risk approval.',policies=policies,selection='2020/21 only: lowest overall MAE among policies with each-year MAE<zero and crash MAE<=1.05*development CatBoost. No stock selection on evaluation. Calibration pooled standardized residual10/90; no interval width cap.',support_rule='joint support ratio<=1 and no shock outside historical marginal range -> supported_history; otherwise exploratory. Neither label guarantees hypothetical accuracy.',evaluation='Same20 locked assets/dates; observed future shocks conditional reconstruction; research reuse, not blind',operational_changes=False)
    (OUT/'protocol.json').write_text(json.dumps(protocol,indent=2))
    for year in [2020,2021,2023,2024,2025,2026]:
        pack=joblib.load(PREV/'folds'/f'{year}_models.joblib')
        refs={s:pd.read_parquet(PREV/'folds'/f'{year}_{suffix}.parquet') for s,suffix in [('test','points'),('cal','calibration')]}
        data={};comp={}
        for split,r in refs.items():
            r=r[r.model=='catboost'];f=r[['asset','date','regime']].merge(d,on=['asset','date'],validate='one_to_one');data[split]=f;comp[split]=components(f,pack)
        for reference,w in policies:
            name=f'{reference}_w{w:g}';f=data['test'];cal=data['cal'];ref,delta,ratio,outside=comp['test'];cr,cd,_,_=comp['cal']
            center=ref[reference]+w*delta;cc=cr[reference]+w*cd
            residual=(cal.target.to_numpy()-cc)/cal.scale.to_numpy();q=np.quantile(residual,[.1,.9])
            z=f[['asset','date','end_date','sector','regime','scale','target']].rename(columns={'target':'actual'}).copy()
            z['fold']=year;z['model']=name;z['reference_center']=ref[reference];z['shock_delta']=w*delta;z['center']=center;z['lo']=center+q[0]*z.scale;z['hi']=center+q[1]*z.scale;z['support_ratio']=ratio;z['outside_marginal']=outside;z['supported_history']=(ratio<=1)&~outside
            z['cal_rows']=len(cal);z['cal_dates']=cal.date.nunique();point.append(z)
    r=pd.concat(point,ignore_index=True);dev=r[r.fold<2023];ev=r[r.fold>=2023]
    prevdev=pd.concat([pd.read_parquet(PREV/'folds'/f'{y}_points.parquet') for y in [2020,2021]]);b=point_score(prevdev[prevdev.model=='catboost'])
    metrics=lambda frame:pd.DataFrame([{'model':n,**point_score(z),**interval_score(z)} for n,z in frame.groupby('model')])
    dm=metrics(dev);dm.to_csv(OUT/'development_metrics.csv',index=False);em=metrics(ev);em.to_csv(OUT/'all_candidate_metrics.csv',index=False)
    eligible=[]
    for n,z in dev.groupby('model'):
        s=point_score(z);annual=all(point_score(x)['mae_gain_zero']>0 for _,x in z.groupby('fold'))
        if annual and s['crash_mae']<=b['crash_mae']*1.05:eligible.append((s['mae'],n))
    assert eligible,'No candidate meets development gate; do not silently choose test best.'
    chosen=min(eligible)[1];selected=ev[ev.model==chosen].copy();selected.to_parquet(OUT/'predictions.parquet',index=False)
    selection=dict(model=chosen,chosen_on=[2020,2021],production_promoted=False,project_candidate=True,scope_rule='frozen support test, all20 retained; no test-based stock selection',center_definition='reference estimate + shrunk linear factor change',limits='80% interval is historical calibration; custom/extreme scenario probability unvalidated')
    (OUT/'selection.json').write_text(json.dumps(selection,indent=2))
    rows=[]
    for group in ['asset','sector','fold','regime','supported_history']:
        for k,z in selected.groupby(group):rows.append({'dimension':group,'group':str(k),**point_score(z),**interval_score(z)})
    pd.DataFrame(rows).to_csv(OUT/'selected_slices.csv',index=False)
    old=pd.read_parquet(PREV/'predictions.parquet');old=old[old.model=='catboost'];q=selected.merge(old[['asset','date','actual','center']],on=['asset','date'],suffixes=('','_old'),validate='one_to_one');assert len(q)==2928;np.testing.assert_array_equal(q.actual,q.actual_old)
    q['gain']=abs(q.actual-q.center_old)-abs(q.actual-q.center);q['zero_gain']=abs(q.actual)-abs(q.actual-q.center);q['month']=q.date.dt.to_period('M').astype(str);rng=np.random.default_rng(20261104);cis={}
    for target in ['gain','zero_gain']:
        a=q.groupby('month')[target].agg(['sum','count']);idx=rng.integers(0,len(a),(2000,len(a)));v=a['sum'].to_numpy()[idx].sum(1)/a['count'].to_numpy()[idx].sum(1);cis[target]=dict(mean=q[target].mean(),low95=np.quantile(v,.025),high95=np.quantile(v,.975))
    (OUT/'date_block_ci.json').write_text(json.dumps(cis,indent=2))
    historical=pd.read_parquet(PREV/'interval_predictions.parquet');historical=historical[historical.model=='unconditional'][['asset','date','lo','hi']]
    iq=selected.merge(historical,on=['asset','date'],suffixes=('','_base'),validate='one_to_one');y=iq.actual
    iq['loss']=iq.hi-iq.lo+10*(iq.lo-y).clip(lower=0)+10*(y-iq.hi).clip(lower=0)
    iq['base_loss']=iq.hi_base-iq.lo_base+10*(iq.lo_base-y).clip(lower=0)+10*(y-iq.hi_base).clip(lower=0)
    iq['month']=iq.date.dt.to_period('M').astype(str);a=iq.groupby('month')[['loss','base_loss']].sum();idx=rng.integers(0,len(a),(2000,len(a)));v=1-a.loss.to_numpy()[idx].sum(1)/a.base_loss.to_numpy()[idx].sum(1)
    (OUT/'risk_date_block_ci.json').write_text(json.dumps(dict(relative_score_gain=1-iq.loss.sum()/iq.base_loss.sum(),low95=float(np.quantile(v,.025)),high95=float(np.quantile(v,.975)),calendar_blocks=len(a),same_relative_gain_for_mean_pinball=True),indent=2))
    print(chosen);print(em.to_string(index=False));print(cis)

if __name__=='__main__':main()
