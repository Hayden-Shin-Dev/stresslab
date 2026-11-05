"""All four inputs accepted. Training/calibration-only shared-coefficient routing."""
import argparse,json
from pathlib import Path
import joblib,numpy as np,pandas as pd
from threadpoolctl import threadpool_limits
from .core import features,anchors,SHOCKS
from .expansion import ExpansionEngine

def shared(model):
 return np.array([model.model.coef_[model.columns.index(s)]/model.scaler.scale_[model.columns.index(s)] for s in SHOCKS])

def choose(engine,cal):
 pred=engine.global_model.predict(cal);beta=engine.global_model.slopes(cal);common=shared(engine.global_model)
 cv=np.stack([shared(m) for m,_ in engine.checks]+[common]);stable=((cv>0).all(0)|(cv<0).all(0))&(cv.std(0)/np.maximum(abs(np.median(cv,axis=0)),1e-8)<=.75)
 probe=cal.groupby('asset').head(1);_,asset_stable,_=engine.coefficients(probe);lookup=dict(zip(probe.asset,asset_stable));policies={};rows=[]
 for a in sorted(cal.asset.unique()):
  idx=cal.asset.eq(a).to_numpy();actual=cal.loc[idx,'target'].to_numpy();base=pred[idx];aslope=beta[idx][0];n=int(idx.sum());crash=actual<=-5
  chosen=[]
  for j,s in enumerate(SHOCKS):
   candidate=base+(common[j]-aslope[j])*cal.loc[idx,s].to_numpy()
   old=abs(base-actual).mean();new=abs(candidate-actual).mean()
   olddown=np.maximum(base[crash]-actual[crash],0).mean() if crash.any() else np.nan
   newdown=np.maximum(candidate[crash]-actual[crash],0).mean() if crash.any() else np.nan
   use=bool(not lookup[a][j] and stable[j] and n>=30 and crash.sum()>=3 and new<=old*.99 and newdown<=olddown)
   if use:chosen.append(s)
   rows.append(dict(asset=a,shock=s,calibration_n=n,crash_n=int(crash.sum()),asset_training_stable=bool(lookup[a][j]),common_training_stable=bool(stable[j]),asset_mae=old,common_mae=new,asset_crash_underestimate=olddown,common_crash_underestimate=newdown,common_selected=use))
  # Simultaneous changes must also improve held-out calibration, not only one-at-a-time.
  changed=base.copy()
  for s in chosen:
   j=SHOCKS.index(s);changed+=(common[j]-aslope[j])*cal.loc[idx,s].to_numpy()
  joint_ok=abs(changed-actual).mean()<=abs(base-actual).mean() and (not crash.any() or np.maximum(changed[crash]-actual[crash],0).mean()<=np.maximum(base[crash]-actual[crash],0).mean())
  policies[a]=chosen if joint_ok else []
  for r in rows:
   if r['asset']==a:r['joint_gate_passed']=bool(joint_ok);r['common_selected']=r['shock'] in policies[a]
 return policies,rows

def run(root,out):
 root=Path(root);out=Path(out);bundle=joblib.load(out/'tiered_bundle.joblib');g=pd.read_parquet(out/'research_input.parquet');d=features(g).dropna(subset=SHOCKS+['target','end_date'])
 primary=set(bundle['primary']['support']);oldcohort=set(bundle['primary']['engine'].global_model.assets)
 cohort=set(bundle['expanded']['engine'].global_model.assets);data=d[d.asset.isin(cohort)]
 primarydata=features(pd.read_parquet(root/'reports/state_link_26_20261104/research_input.parquet')).dropna(subset=SHOCKS+['target','end_date']);primarydata=primarydata[primarydata.asset.isin(oldcohort)]
 rows=[];gates=[];last={};lastengines={}
 for year in [2023,2024,2025,2026]:
  for group,frame,wanted in [('primary',primarydata,primary),('expansion',data,cohort-primary)]:
   tr=frame[frame.end_date<pd.Timestamp(year-1,1,1)-pd.Timedelta(days=20)]
   cal=anchors(frame[(frame.date>=pd.Timestamp(year-1,1,1))&(frame.end_date<pd.Timestamp(year,1,1)-pd.Timedelta(days=20))])
   te=anchors(frame[(frame.date>=pd.Timestamp(year,1,1))&(frame.date<pd.Timestamp(year+1,1,1))]);te=te[te.asset.isin(wanted)]
   e=ExpansionEngine().fit(tr);policy,gs=choose(e,cal);last[group]=policy
   for z in gs:z.update(year=year,group=group)
   gates.extend(gs);pred=e.global_model.predict(te);beta=e.global_model.slopes(te);com=shared(e.global_model);routed=pred.copy()
   for i,r in enumerate(te.itertuples()):
    for s in policy.get(r.asset,[]):
     j=SHOCKS.index(s);routed[i]+=(com[j]-beta[i,j])*getattr(r,s)
   for name,values in [('asset_partial_pool',pred),('validated_common_fallback',routed)]:
    z=te[['asset','date','target']].rename(columns={'target':'actual'}).copy();z['center']=values;z['model']=name;z['year']=year;z['group']=group;rows.append(z)
  print('four shock fallback fold',year,flush=True)
 pd.concat(rows).to_parquet(out/'fallback_predictions.parquet',index=False);pd.DataFrame(gates).to_csv(out/'fallback_calibration_gates.csv',index=False)
 # Use latest pre-test calibration decisions; never select fallback from 2026 test errors.
 bundle['common_fallback_policy']={**{a:s for a,s in last['primary'].items() if a in primary},**{a:s for a,s in last['expansion'].items() if a not in primary}}
 bundle['common_fallback_policy_basis']='2025 out-of-sample calibration from model trained before 2025; additionally current shared coefficient stability must pass'
 (out/'common_fallback_policy.json').write_text(json.dumps(bundle['common_fallback_policy'],indent=2),encoding='utf8')
 joblib.dump(bundle,out/'tiered_bundle.joblib');print('finished fallback comparison',flush=True)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--root',required=True);p.add_argument('--out',required=True);a=p.parse_args()
 with threadpool_limits(limits=2):run(a.root,a.out)
