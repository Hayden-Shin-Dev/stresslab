"""Outcome-blind entropy balancing for high/low input observational contrasts."""
import json
import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.special import logsumexp
from concurrent.futures import ThreadPoolExecutor,as_completed
from threadpoolctl import threadpool_limits
from analyze_effect_atlas_20261104 import ROOT,OUT,RAW,SRC
ALIASES={'relative_market5':'asset_trend5','relative_market20':'asset_trend20','relative_market60':'asset_trend60','equity_assets':'debt_assets','asset_vol_ratio':'asset_vol5','market_vol_ratio':'market_vol5','asset_acceleration':'asset_trend5','market_acceleration':'market_trend5','foreign_flow_accel':'foreign_flow_5','institution_flow_accel':'institution_flow_5'}

def controls_for(feature):
    # Equivalent parameterizations: derived input replaces its redundant primitive.
    # Never condition on both an input and the identities that deterministically fix it.
    return [c for c in RAW if c not in ALIASES and c!=feature and c!=ALIASES.get(feature)]

def weights(x,target):
    e,u=np.linalg.eigh(np.cov(x,rowvar=False)+.001*np.eye(x.shape[1]));t=u/np.sqrt(np.maximum(e,.001));xt=x@t;tt=t.T@t;target_t=target@t
    def objective(b):
        v=xt@b;w=np.exp(v-logsumexp(v));return logsumexp(v)-b@target_t+.001*(b@tt@b)/2,xt.T@w-target_t+.001*(tt@b)
    fit=minimize(objective,np.zeros(x.shape[1]),jac=True,method='L-BFGS-B',options={'maxiter':150,'ftol':1e-10})
    v=xt@fit.x;return np.exp(v-logsumexp(v)),bool(fit.success)

def run(asset,f):
    path=OUT/'balance_coordinates_checkpoints'/f'{asset}.json'
    if path.exists():return json.loads(path.read_text())
    z=f.iloc[::6].copy();rows=[]
    for feature in RAW:
        v=z[feature].dropna();low,high=v.quantile([.25,.75]) if len(v) else (np.nan,np.nan);base=dict(asset=asset,feature=feature)
        if len(v)<80 or not high>low:rows.append(dict(**base,status='insufficient_variation'));continue
        ia=np.where(z[feature]>=high)[0];ib=np.where(z[feature]<=low)[0]
        controls=[c for c in controls_for(feature) if z[c].notna().mean()>=.5 and z[c].std()>1e-8]
        raw=z[controls];x=raw.fillna(raw.median()).to_numpy();sd=x.std(0);x=(x-x.mean(0))/np.maximum(sd,1e-8)
        # Include missingness flags where needed; unobserved values are not real zeros.
        missing=raw.isna().to_numpy().astype(float);vary=missing.std(0)>.01
        if vary.any():x=np.column_stack([x,missing[:,vary]])
        target=np.vstack([x[ia],x[ib]]).mean(0);wa,oka=weights(x[ia],target);wb,okb=weights(x[ib],target)
        smd=np.abs(wa@x[ia]-wb@x[ib]);essa=1/(wa@wa);essb=1/(wb@wb);passed=bool(oka and okb and smd.max()<=.1 and min(essa,essb)>=30 and max(wa.max(),wb.max())<=.1)
        a=z.iloc[ia];b=z.iloc[ib];ret=float(wa@a.target.to_numpy()-wb@b.target.to_numpy())
        rows.append(dict(**base,status='balanced_descriptive' if passed else 'unsupported_balance_or_overlap',high_n=len(a),low_n=len(b),high_ess=essa,low_ess=essb,
            high_max_weight=float(wa.max()),low_max_weight=float(wb.max()),max_control_smd=float(smd.max()),optimizer_converged=oka and okb,controls=len(controls),
            feature_high=float(wa@a[feature].to_numpy()),feature_low=float(wb@b[feature].to_numpy()),return_contrast_pp=ret,
            up_frequency_contrast_pp=float((wa@a.target.gt(0).to_numpy()-wb@b.target.gt(0).to_numpy())*100),
            crash_frequency_contrast_pp=float((wa@a.target.le(-5).to_numpy()-wb@b.target.le(-5).to_numpy())*100),
            outcome_used_for_weights=False,causal_effect=False,controls_list='|'.join(controls),parameterization='Remove exact algebraic aliases; derived feature replaces primitive',interpretation='Mean-balanced association only; higher moments, nonlinear confounding and calendar differences remain'))
    path.write_text(json.dumps(rows));return rows

def main():
    OUT.mkdir(exist_ok=True);(OUT/'balance_coordinates_checkpoints').mkdir(exist_ok=True)
    d=pd.read_parquet(ROOT/'reports/rich_context_20261103/learning_table.parquet');d=d[d.end_date<pd.Timestamp('2022-01-01')-pd.Timedelta(days=20)];assets=json.loads((SRC/'selected_assets.json').read_text());allrows=[];failed=[]
    with threadpool_limits(limits=1,user_api='blas'),ThreadPoolExecutor(max_workers=2) as pool:
        fs={pool.submit(run,a,d[d.asset==a].sort_values('date')):a for a in assets}
        for i,fu in enumerate(as_completed(fs),1):
            try:allrows+=fu.result()
            except Exception as e:failed.append(dict(asset=fs[fu],error=repr(e)))
            (OUT/'balance_progress.json').write_text(json.dumps(dict(status='running',completed=i,total=len(fs),failed=failed)))
    assert not failed,failed
    pd.DataFrame(allrows).to_csv(OUT/'entropy_balanced_contrasts.csv',index=False)
    (OUT/'balance_protocol.json').write_text(json.dumps(dict(features=RAW,aliases=ALIASES,data_end=str(d.end_date.max()),penalty=.001,high_low='training quartiles',balance='nonredundant coordinate first moments, missingness flags',gates=dict(max_smd=.1,min_ess=30,max_weight=.1,convergence=True),outcome_used_for_weights=False,production=False),indent=2))
    (OUT/'balance_progress.json').write_text(json.dumps(dict(status='complete',completed=len(fs),failed=[])))
if __name__=='__main__':main()
