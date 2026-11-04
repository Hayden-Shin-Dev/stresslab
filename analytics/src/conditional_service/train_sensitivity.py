"""Frozen per-stock benchmark and auditable sensitivity service candidate."""
import argparse,json,hashlib
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import Ridge
from catboost import CatBoostRegressor
from lightgbm import LGBMRegressor
from threadpoolctl import threadpool_limits
from .core import features,anchors,validate,STATE,ASSET,SHOCKS,metrics
from .sensitivity_model import SensitivityEngine,explain

def individual(kind):
    if kind=='ridge':return make_pipeline(StandardScaler(),Ridge(alpha=300))
    if kind=='catboost':return CatBoostRegressor(iterations=150,depth=3,learning_rate=.04,loss_function='Quantile:alpha=0.5',random_seed=20261104,thread_count=2,verbose=False,allow_writing_files=False)
    return LGBMRegressor(objective='quantile',alpha=.5,n_estimators=150,max_depth=3,num_leaves=7,learning_rate=.04,min_child_samples=30,reg_lambda=10,random_state=20261104,n_jobs=2,verbosity=-1)

def run(gold,out):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    g=pd.read_parquet(gold);audit=validate(g,True);audit['source_sha256']=hashlib.sha256(Path(gold).read_bytes()).hexdigest()
    f=features(g);d=f.dropna(subset=SHOCKS+['target','end_date']);rows=[];stability=[];splits=[];scenarios=[]
    (out/'protocol.json').write_text(json.dumps(dict(prior_evaluation_reused=True,selection='Fixed training-only stability: signs agree across full and 18/12/6 month earlier expanding fits; coefficient CV<=0.75; one shock IQR contribution>=0.1pp; state coefficient requires >=30 analogous nonoverlap windows. These are research rules, not confidence guarantees.',models='Legacy individual Ridge/LGB/CatBoost normalized targets; new partial-pool Ridge raw return target, alpha300 deviation penalty10; same rows/features and temporal boundaries.',operating_resources_changed=False),indent=2),encoding='utf8')
    for year in [2023,2024,2025,2026]:
        start=pd.Timestamp(year-1,1,1);cut=pd.Timestamp(year,1,1)
        tr=d[d.end_date<start-pd.Timedelta(days=20)];ca=anchors(d[(d.date>=start)&(d.end_date<cut-pd.Timedelta(days=20))]);te=anchors(d[(d.date>=cut)&(d.date<pd.Timestamp(year+1,1,1))])
        eligible=set(tr.groupby('asset').size().loc[lambda x:x>=250].index)&set(ca.asset)&set(te.asset)
        tr,ca,te=[x[x.asset.isin(eligible)].copy() for x in [tr,ca,te]]
        assert tr.end_date.max()<ca.date.min() and ca.end_date.max()<te.date.min()
        split=dict(year=year,train_label_end=str(tr.end_date.max()),cal_start=str(ca.date.min()),cal_label_end=str(ca.end_date.max()),test_start=str(te.date.min()),assets=len(eligible),test_rows=len(te));splits.append(split)
        e=SensitivityEngine().fit(tr)
        joblib.dump(e,out/f'engine_{year}.joblib')
        predictions={'partial_global':(e.global_model.predict(ca),e.global_model.predict(te)),'partial_state_gated':(e.predict(ca),e.predict(te))}
        for kind in ['ridge','lightgbm','catboost']:
            cp=pd.Series(index=ca.index,dtype=float);tp=pd.Series(index=te.index,dtype=float)
            for a in sorted(eligible):
                training=tr[tr.asset.eq(a)];cal=ca[ca.asset.eq(a)];test=te[te.asset.eq(a)]
                m=individual(kind).fit(training[STATE+ASSET+SHOCKS].to_numpy(),training.target/training.scale)
                cp.loc[cal.index]=m.predict(cal[STATE+ASSET+SHOCKS].to_numpy())*cal.scale
                tp.loc[test.index]=m.predict(test[STATE+ASSET+SHOCKS].to_numpy())*test.scale
                if year==2026:
                    probe=test.iloc[[-1]].copy()
                    for mult in [0,1,2,4]:
                        x=probe.copy();x[SHOCKS]=[2.5*mult,50*mult,0,0]
                        scenarios.append(dict(model=kind,asset=a,multiplier=mult,center=float(m.predict(x[STATE+ASSET+SHOCKS].to_numpy())[0]*x.scale.iloc[0])))
            predictions[kind]=(cp.to_numpy(),tp.to_numpy());print('fit',year,kind,flush=True)
        for name,(cp,tp) in predictions.items():
            quant=np.quantile((ca.target-cp)/ca.scale,[.1,.9]);z=te[['date','asset','target']].rename(columns={'target':'actual'}).copy();z['center']=tp;z['lo']=tp+quant[0]*te.scale;z['hi']=tp+quant[1]*te.scale;z['model']=name;z['fold']=year;rows.append(z)
        probe=te.sort_values('date').groupby('asset').head(1);beta,stable,details=e.coefficients(probe)
        for i,r in enumerate(probe.itertuples()):
            for j,s in enumerate(SHOCKS):stability.append(dict(fold=year,asset=r.asset,shock=s,state_date=r.date,coefficient=float(beta[i,j]),stable=bool(stable[i,j]),source='state' if details['use_state'][i,j] else 'global',global_coefficient=details['global_beta'][i,j],state_coefficient=details['state_beta'][i,j],state_analogues=int(details['state_analogues'][i])))
        if year==2026:
            for mult in [0,1,2,4]:
                x=te.sort_values('date').groupby('asset').tail(1).copy();x[SHOCKS]=[2.5*mult,50*mult,0,0]
                for a,p in zip(x.asset,e.predict(x)):scenarios.append(dict(model='partial_state_gated',asset=a,multiplier=mult,center=float(p)))
        print('completed',year,flush=True)
    p=pd.concat(rows);p.to_parquet(out/'predictions.parquet',index=False)
    summary=pd.DataFrame([dict(model=k,**metrics(z)) for k,z in p.groupby('model')]);summary.to_csv(out/'metrics.csv',index=False)
    per=pd.DataFrame([dict(asset=a,model=k,**metrics(z)) for (a,k),z in p.groupby(['asset','model'])]);per.to_csv(out/'per_asset.csv',index=False)
    pd.DataFrame(stability).to_csv(out/'sensitivity_stability.csv',index=False);pd.DataFrame(scenarios).to_csv(out/'extrapolation.csv',index=False)
    audit.update(splits=splits,evaluation='Retrospective actual-shock response reconstruction; reused 2023-2026 development evaluation; not blind or causal.',production_approved=False)
    (out/'audit.json').write_text(json.dumps(audit,indent=2),encoding='utf8')
    latest=f.date.max();snap=f[(f.date==latest)&f.asset.isin(e.global_model.assets)].copy()
    # Deliberately retain last evaluated annual model; do not silently train on evaluation outcomes.
    validation={r.asset:{k:v for k,v in r._asdict().items() if k not in ['asset','model']} for r in per[per.model.eq('partial_state_gated')].itertuples(index=False)}
    bundle=dict(version='sensitivity-factor-v1-research',engine=e,snapshot=snap,validation=validation,audit=audit)
    joblib.dump(bundle,out/'bundle.joblib');examples={}
    positions=[dict(asset_id=a,value_krw=1000000) for a in ['003490','010950'] if a in set(snap.asset)]
    for name,shock in [('zero',{}),('oil10',{'wti_pct':10}),('fx5_rate100',{'fx_pct':5,'us_rate_bp':100}),('fx10_rate200',{'fx_pct':10,'us_rate_bp':200})]:examples[name]=explain(bundle,positions,shock)
    (out/'service_examples.json').write_text(json.dumps(examples,ensure_ascii=False,indent=2),encoding='utf8')
    probe=snap.copy();probe[SHOCKS]=0;b,ok,details=e.coefficients(probe);support=[]
    for i,r in enumerate(probe.itertuples()):
        for j,s in enumerate(SHOCKS):support.append(dict(asset=r.asset,shock=s,coefficient=b[i,j],training_rule_supported=bool(ok[i,j]),source='state' if details['use_state'][i,j] else 'global',state_analogues=int(details['state_analogues'][i])))
    pd.DataFrame(support).to_csv(out/'support_candidates.csv',index=False)
    print(summary.to_string(index=False),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--gold',required=True);p.add_argument('--out',required=True);a=p.parse_args()
    with threadpool_limits(limits=2):run(a.gold,a.out)
