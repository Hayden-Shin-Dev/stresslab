"""Refit a transparent JSON coefficient bundle; no pickle needed for serving."""
import json,hashlib
import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits
from pooled_stress_core_20261104 import ROOT,FEATURES,STATE,SHOCKS,FACTORS,ASSETS,SECTORS,prepare,fit_factor,JointSupport,chronological_anchors
from gold_quantile_benchmark import build
from service_candidate_20261104 import OUT

def main():
    selection=json.loads((OUT/'selection.json').read_text());assert selection['model']=='zero_reference_w1'
    d,g=prepare();m,tr,tuning=fit_factor(d,2026)
    # All outcomes here are mature before the current source snapshot; no holdout claim.
    cal=chronological_anchors(d[(d.date>=pd.Timestamp('2026-01-01'))&d.oil_valid])
    zero=cal.copy();zero[SHOCKS]=0
    for s in SHOCKS:
        for c in ['market_trend20','market_vol20']:zero[s+'__'+c]=0
    delta=m.predict(cal)-m.predict(zero);res=cal.target/cal.scale-delta;q=np.quantile(res,[.1,.9])
    snap=build(g,require_outcome=False);snap=snap[snap.asset.isin(ASSETS)]
    complete=snap.groupby('date').asset.nunique();date=complete[complete==len(ASSETS)].index.max();snap=snap[snap.date==date].sort_values('asset')
    support=JointSupport().fit(tr);hist=tr.sort_values('date').drop_duplicates('date').iloc[::6];scols=STATE+SHOCKS
    coef=m.model.coef_;coefficients={}
    for ai,a in enumerate(ASSETS):
        coefficients[a]={}
        for si,s in enumerate(SHOCKS):
            j=FACTORS.index(s);tj=FACTORS.index(s+'__market_trend20');vj=FACTORS.index(s+'__market_vol20')
            coefficients[a][s]=dict(common=float(coef[j]/m.scaler.scale_[j]),asset_deviation=float(coef[len(FACTORS)+len(ASSETS)+ai*4+si]/np.sqrt(m.ratio)/m.scaler.scale_[j]),trend_interaction=float(coef[tj]/m.scaler.scale_[tj]),vol_interaction=float(coef[vj]/m.scaler.scale_[vj]))
    # This export must exactly reproduce the trained model's scenario differences.
    samples=cal.iloc[::11]
    expected=[]
    for _,r in samples.iterrows():
        terms=coefficients[r.asset];expected.append(sum((terms[s]['common']+terms[s]['asset_deviation']+terms[s]['trend_interaction']*r.market_trend20+terms[s]['vol_interaction']*r.market_vol20)*r[s] for s in SHOCKS))
    z=samples.copy();z[SHOCKS]=0
    for s in SHOCKS:
        for c in ['market_trend20','market_vol20']:z[s+'__'+c]=0
    np.testing.assert_allclose(expected,m.predict(samples)-m.predict(z),atol=1e-10)
    states={};analogues={}
    for _,r in snap.iterrows():
        states[r.asset]={k:float(r[k]) for k in STATE+['scale']}
        h=chronological_anchors(d[(d.asset==r.asset)&(d.end_date<date-pd.Timedelta(days=20))&d.oil_valid]).copy()
        hs=(h[STATE].quantile(.75)-h[STATE].quantile(.25)).replace(0,1);h['distance']=((h[STATE]-r[STATE].astype(float))/hs).pow(2).mean(axis=1)
        analogues[r.asset]=[dict(start=str(n.date.date()),end=str(n.end_date.date()),observed_return_pct=float(n.target),observed_shocks={s:float(n[s]) for s in SHOCKS},state_distance=float(n.distance),kind='historical_observation_not_user_shock_forecast') for _,n in h.nsmallest(5,'distance').iterrows()]
    metric=pd.read_csv(OUT/'all_candidate_metrics.csv');metric=metric[metric.model==selection['model']].iloc[0].to_dict()
    bundle=dict(version='stresslab-neutral-factor-demo-v1',status='project_demo_candidate',reference_return_pct=0,reference_assumption='No-shock reference is set to0%; center is model factor change relative to unchanged macro levels, not identified causal effect.',state_date=str(date.date()),train_label_end=str(tr.end_date.max().date()),calibration_end=str(cal.end_date.max().date()),calibration_rows=len(cal),calibration_dates=cal.date.nunique(),publication_timestamps_verified=False,source_gold_sha256=hashlib.sha256((ROOT/'exports/seongjin_gold_v1_1/gold_stress_daily.parquet').read_bytes()).hexdigest(),coefficients=coefficients,states=states,sector_groups=SECTORS,analogues=analogues,residual_q10=float(q[0]),residual_q90=float(q[1]),support=dict(columns=scols,median=[float(support.mid[c]) for c in scols],iqr=[float(support.scale[c]) for c in scols],reference_vectors=((hist[scols]-support.mid)/support.scale).to_numpy().tolist(),threshold=support.threshold,marginal_bounds=support.bounds),research_metrics=metric,lockbox_validated=False)
    dest=OUT/'service';dest.mkdir(exist_ok=True);(dest/'model.json').write_text(json.dumps(bundle,ensure_ascii=False,indent=2),encoding='utf8')
    pd.DataFrame(tuning).to_csv(OUT/'release_inner_tuning.csv',index=False)
    (OUT/'bundle_verification.json').write_text(json.dumps(dict(export_matches_trained_factor=True,checked_rows=len(samples),train_before_calibration=bool(tr.end_date.max()<cal.date.min()),state_date=bundle['state_date'],train_label_end=bundle['train_label_end'],calibration_end=bundle['calibration_end'],calibration_rows=len(cal),calibration_dates=cal.date.nunique(),status='research_performance_is_from_prior_walk_forward_not_release_calibration'),indent=2))
    print(json.dumps({k:bundle[k] for k in ['version','state_date','train_label_end','calibration_end','calibration_rows','calibration_dates']}))

if __name__=='__main__':
    with threadpool_limits(limits=2):main()
