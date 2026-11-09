"""Symmetric tail-focused point estimate; NOT an ordinary conditional median."""
import json
from concurrent.futures import ThreadPoolExecutor,as_completed
import numpy as np
import pandas as pd
from sklearn.pipeline import make_pipeline
from sklearn.impute import SimpleImputer
from crash_cases_center_20261104 import OUT,ROOT,inputs,metrics,COLS,KINDS,estimator
def main():
    d=inputs();old=pd.read_parquet(OUT/'predictions.parquet');dev=pd.read_parquet(OUT/'development_predictions.parquet');refs=pd.concat([old,dev]);refs=refs[refs.policy=='baseline'];configs=json.loads((ROOT/'reports/four_models_gold_20261104/frozen_configs.json').read_text());folder=OUT/'tail_checkpoints';folder.mkdir(exist_ok=True)
    (OUT/'tail_policy.json').write_text(json.dumps(dict(rule='Train-only abs(vol-normalized return) upper quartile receives weight2; all other rows weight1. Both positive and negative extremes treated identically.',interpretation='Tail-weighted point estimate, not original unweighted conditional median.',selection='Same development-only crash/overall/direction/false-alarm guard. Post-hoc failure-led research, not blind.'),indent=2))
    def fit(a,f):
        path=folder/f'{a}.parquet'
        if path.exists():return
        rows=[];audit=[]
        for year in [2020,2021,2023,2024,2025,2026]:
            tr=f[(f.end_date<pd.Timestamp(year,1,1)-pd.Timedelta(days=20))&f.oil_valid];te=f[f.date.isin(refs.loc[(refs.asset==a)&(refs.fold==year),'date'].unique())].sort_values('date')
            if te.empty:continue
            y=tr.target/tr.scale;threshold=y.abs().quantile(.75);w=np.where(y.abs()>=threshold,2.,1.)
            for kind in KINDS:
                m=make_pipeline(SimpleImputer(strategy='median'),estimator(kind,'median',configs[kind]));last=list(m.named_steps)[-1];key=last+('__ridge__sample_weight' if kind=='ridge' else '__sample_weight')
                m.fit(tr[COLS].to_numpy(),y,**{key:w});p=m.predict(te[COLS].to_numpy())*te.scale.to_numpy()
                rows.append(pd.DataFrame(dict(asset=a,date=te.date.to_numpy(),fold=year,model=kind,policy='tail_weighted',actual=te.target.to_numpy(),center=p)))
                audit.append(dict(asset=a,fold=year,model=kind,train_label_end=str(tr.end_date.max()),test_start=str(te.date.min()),train_n=len(tr),tail_threshold=threshold,upweighted_positive=int(((w>1)&(y>0)).sum()),upweighted_negative=int(((w>1)&(y<0)).sum())))
        pd.concat(rows).to_parquet(path,index=False);pd.DataFrame(audit).to_csv(path.with_suffix('.csv'),index=False)
    with ThreadPoolExecutor(max_workers=4) as pool:
        fs=[pool.submit(fit,a,f) for a,f in d.groupby('asset')]
        for i,f in enumerate(as_completed(fs),1):f.result();print(i,20,flush=True)
    new=pd.concat([pd.read_parquet(p) for p in folder.glob('*.parquet')]);r=pd.concat([old[old.policy!='tail_weighted'],dev[dev.policy!='tail_weighted'],new],ignore_index=True);ev=r[r.fold>=2023];dv=r[r.fold<2023]
    for name,frame in [('metrics',ev),('development_metrics',dv)]:pd.DataFrame([dict(model=k,policy=p,**metrics(z)) for (k,p),z in frame.groupby(['model','policy'])]).to_csv(OUT/f'{name}.csv',index=False)
    ev.to_parquet(OUT/'predictions.parquet',index=False);dv.to_parquet(OUT/'development_predictions.parquet',index=False)
    pd.DataFrame([dict(asset=a,model=k,policy=p,**metrics(z)) for (a,k,p),z in ev.groupby(['asset','model','policy'])]).to_csv(OUT/'per_stock.csv',index=False)
    pd.DataFrame([dict(fold=y,model=k,policy=p,**metrics(z)) for (y,k,p),z in ev.groupby(['fold','model','policy'])]).to_csv(OUT/'per_year.csv',index=False)
    selection={}
    for kind in KINDS:
        z=dv[dv.model==kind];b=metrics(z[z.policy=='baseline']);eligible=[]
        for p in ['domestic','domestic_mean','tail_weighted']:
            s=metrics(z[z.policy==p])
            if s['crash_mae']<=b['crash_mae']*.95 and s['mae']<=b['mae'] and s['direction']>=b['direction'] and s['false_crash']<=b['false_crash']+2:eligible.append((s['crash_mae'],p))
        selection[kind]=min(eligible)[1] if eligible else 'baseline'
    (OUT/'development_selection.json').write_text(json.dumps(selection,indent=2));pd.concat([pd.read_csv(p,dtype={'asset':str}) for p in folder.glob('*.csv')]).to_csv(OUT/'tail_fit_audit.csv',index=False)
    print(pd.read_csv(OUT/'metrics.csv').to_string(index=False))
if __name__=='__main__':main()
