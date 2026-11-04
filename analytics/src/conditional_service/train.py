"""python -m conditional_service.train --gold FILE --out DIRECTORY --research"""
import argparse
import hashlib
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits
from .core import Factor, SHOCKS, STATE, anchors, features, metrics, validate, analyze


def run(gold, out, research):
    out = Path(out); out.mkdir(parents=True, exist_ok=True)
    g = pd.read_parquet(gold); audit = validate(g, research)
    audit['source_sha256'] = hashlib.sha256(Path(gold).read_bytes()).hexdigest()
    (out/'input_audit.json').write_text(json.dumps(audit, indent=2), encoding='utf8')
    f = features(g); data = f.dropna(subset=SHOCKS+['target', 'end_date'])
    predictions=[]; slopes=[]; splits=[]
    for year in [2023, 2024, 2025, 2026]:
        cut=pd.Timestamp(year,1,1); cstart=pd.Timestamp(year-1,1,1)
        tr=data[data.end_date<cstart-pd.Timedelta(days=20)]
        ca=anchors(data[(data.date>=cstart)&(data.end_date<cut-pd.Timedelta(days=20))])
        te=anchors(data[(data.date>=cut)&(data.date<pd.Timestamp(year+1,1,1))])
        counts=tr.groupby('asset').size(); eligible=counts[counts>=250].index
        common=set(eligible)&set(ca.asset)&set(te.asset)
        tr,ca,te=[z[z.asset.isin(common)].copy() for z in [tr,ca,te]]
        if ca.empty or te.empty: continue
        assert tr.end_date.max()<ca.date.min() and ca.end_date.max()<te.date.min()
        splits.append(dict(year=year,train_end=str(tr.end_date.max()),cal_start=str(ca.date.min()),
                           cal_end=str(ca.end_date.max()),test_start=str(te.date.min()),test_n=len(te)))
        for kind in ['zero','state_only','conditional_factor']:
            model=None if kind=='zero' else Factor(kind=='conditional_factor').fit(tr)
            cp=np.zeros(len(ca)) if model is None else model.predict(ca)
            pred=np.zeros(len(te)) if model is None else model.predict(te)
            q=np.quantile((ca.target-cp)/ca.scale,[.1,.9])
            z=te[['asset','date','target']].rename(columns={'target':'actual'}).copy()
            z['center']=pred;z['lo']=pred+q[0]*te.scale;z['hi']=pred+q[1]*te.scale
            z['model']=kind;z['fold']=year;predictions.append(z)
            if kind=='conditional_factor':
                # Sensitivities are descriptive fold results, never used to select test stocks.
                probe=tr.sort_values('date').groupby('asset').tail(1).copy();probe[SHOCKS]=0
                base=model.predict(probe)
                for s in SHOCKS:
                    changed=probe.copy();changed[s]=1
                    for a,b in zip(probe.asset,model.predict(changed)-base):
                        slopes.append(dict(asset=a,fold=year,shock=s,slope_pp_per_unit=float(b)))
        print('fold',year,'assets',len(common),'test',len(te),flush=True)
    result=pd.concat(predictions,ignore_index=True);result.to_parquet(out/'predictions.parquet',index=False)
    summary=pd.DataFrame([dict(model=k,**metrics(z)) for k,z in result.groupby('model')])
    summary.to_csv(out/'metrics.csv',index=False)
    per=pd.DataFrame([dict(asset=a,model=k,**metrics(z)) for (a,k),z in result.groupby(['asset','model'])]);per.to_csv(out/'per_asset.csv',index=False)
    pd.DataFrame(slopes).to_csv(out/'factor_stability.csv',index=False)
    (out/'splits.json').write_text(json.dumps(splits,indent=2),encoding='utf8')
    # Paired date blocks preserve correlation between stocks; development evaluation only.
    paired=result.pivot(index=['date','asset'],columns='model',values=['actual','center'])
    daily=pd.DataFrame({k:abs(paired['actual'][k]-paired['center'][k]) for k in ['zero','state_only','conditional_factor']}).groupby(level='date').mean()
    blocks=[v for _,v in daily.groupby(daily.index.to_period('M'))];rng=np.random.default_rng(20261104);ci={}
    for base in ['zero','state_only']:
        gains=[]
        for _ in range(1000):
            z=pd.concat([blocks[i] for i in rng.integers(0,len(blocks),len(blocks))])
            gains.append(100*(1-z.conditional_factor.mean()/z[base].mean()))
        ci[base]=dict(mae_gain_pct=100*(1-daily.conditional_factor.mean()/daily[base].mean()),
                      date_block_95pct=np.quantile(gains,[.025,.975]).tolist())
    (out/'comparison_ci.json').write_text(json.dumps(ci,indent=2),encoding='utf8')
    latest=f.date.max();snap=f[f.date==latest].copy()
    cstart=pd.Timestamp(latest.year-1,1,1)
    tr=data[data.end_date<cstart-pd.Timedelta(days=20)]
    ca=anchors(data[(data.date>=cstart)&(data.end_date<latest-pd.Timedelta(days=20))])
    eligible=set(tr.groupby('asset').size().loc[lambda x:x>=250].index)&set(ca.asset)&set(snap.asset)
    tr,ca,snap=[z[z.asset.isin(eligible)].copy() for z in [tr,ca,snap]]
    m=Factor().fit(tr);q=np.quantile((ca.target-m.predict(ca))/ca.scale,[.1,.9])
    history=data[(data.end_date<latest-pd.Timedelta(days=20))&data.asset.isin(eligible)].copy()
    audit.update(train_end=str(tr.end_date.max()),calibration_end=str(ca.end_date.max()),
                 evaluation='Reused 2023-2026 development windows; observed future shocks supplied after the fact',
                 supported_assets=sorted(eligible))
    asset_metrics={str(r.asset):{k:(None if pd.isna(v) else v) for k,v in r._asdict().items() if k not in ['asset','model']} for r in per[per.model=='conditional_factor'].itertuples(index=False)}
    b=dict(version='gold-conditional-integration-v2',model=m,snapshot=snap,history=history,q=q,
           shock_mid=tr[SHOCKS].median(),shock_iqr=(tr[SHOCKS].quantile(.75)-tr[SHOCKS].quantile(.25)).replace(0,1),
           audit=audit,asset_metrics=asset_metrics)
    joblib.dump(b,out/'bundle.joblib')
    (out/'release_manifest.json').write_text(json.dumps(audit,indent=2),encoding='utf8')
    pos=[dict(asset_id=a,value_krw=50000000) for a in ['005930','005380'] if a in eligible]
    scenarios={}
    for name,sh in [('zero',{}),('fx5_rate100',{'fx_pct':5,'us_rate_bp':100}),('fx10_rate200',{'fx_pct':10,'us_rate_bp':200}),('oil10',{'wti_pct':10})]:
        scenarios[name]=analyze(b,pos,sh)
    (out/'actual_scenarios.json').write_text(json.dumps(scenarios,ensure_ascii=False,indent=2),encoding='utf8')
    print(summary.to_string(index=False));print(json.dumps(ci))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--gold',required=True);p.add_argument('--out',required=True);p.add_argument('--research',action='store_true');a=p.parse_args()
    with threadpool_limits(limits=2):run(a.gold,a.out,a.research)
