"""Time-separated local response curves and matched observational contrasts. No causal claim."""
import json,hashlib,os
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,as_completed
import numpy as np
import pandas as pd
from lightgbm import LGBMRegressor,LGBMClassifier
from sklearn.neighbors import NearestNeighbors
from threadpoolctl import threadpool_limits
from analyze_variables_20261104 import ROOT,RAW,SHOCKS,SRC
from variable_labels_20261104 import labels
OUT=ROOT/'reports/effect_atlas_20261104/coordinates'
OUTCOMES=['return','up_score','crash_score']

from balance_effect_atlas_20261104 import ALIASES
MODEL_FEATURES=[c for c in RAW if c not in ALIASES]
def coherent(x,feature):
    x=x.copy()
    if feature.startswith('relative_market'):
        h=feature.replace('relative_market','');x['asset_trend'+h]=x[feature]+x['market_trend'+h]
    elif feature=='equity_assets':x['debt_assets']=1-x[feature]
    elif feature=='asset_vol_ratio':x['asset_vol5']=x[feature]*x.asset_vol60
    elif feature=='market_vol_ratio':x['market_vol5']=x[feature]*x.market_vol60
    elif feature=='asset_acceleration':x['asset_trend5']=x[feature]+x.asset_trend20/4
    elif feature=='market_acceleration':x['market_trend5']=x[feature]+x.market_trend20/4
    elif feature=='foreign_flow_accel':x['foreign_flow_5']=x[feature]+x.foreign_flow_20
    elif feature=='institution_flow_accel':x['institution_flow_5']=x[feature]+x.institution_flow_20
    return x[MODEL_FEATURES]


def learner(kind):
    args=dict(n_estimators=180,max_depth=5,num_leaves=23,min_child_samples=60,learning_rate=.035,reg_lambda=8,n_jobs=1,verbosity=-1,random_state=20261104)
    return LGBMRegressor(objective='quantile',alpha=.5,**args) if kind=='return' else LGBMClassifier(**args)

def predict(m,x,kind):
    return m.predict(x) if kind=='return' else m.predict_proba(x)[:,1]*100

def block_ci(values,dates,seed=4):
    z=pd.DataFrame({'v':values,'block':pd.DatetimeIndex(dates).to_period('Q')}).groupby('block').v.agg(['sum','count'])
    if len(z)<4:return np.nan,np.nan
    rng=np.random.default_rng(seed);draw=rng.integers(0,len(z),(300,len(z)))
    v=z['sum'].to_numpy()[draw].sum(1)/z['count'].to_numpy()[draw].sum(1)
    return tuple(np.quantile(v,[.025,.975]))

def match_contrasts(f,asset):
    # Every six eligible dates, all before 2022. Selection and controls never use outcomes.
    z=f.iloc[::6].reset_index(drop=True);rows=[]
    for feature in RAW:
        valid=z[feature].notna();v=z.loc[valid,feature];lo,hi=v.quantile([.25,.75]) if len(v) else (np.nan,np.nan)
        base=dict(asset=asset,feature=feature,method='matched_observational_association',causal=False)
        if len(v)<80 or not hi>lo:
            rows.append(dict(**base,status='insufficient_variation',n=0));continue
        high=np.where(valid&(z[feature]>=hi))[0];low=np.where(valid&(z[feature]<=lo))[0]
        controls=[c for c in RAW if c!=feature and z[c].notna().mean()>=.5 and z[c].std()>1e-8]
        x=z[controls].fillna(z[controls].median()).to_numpy();sd=x.std(0);x=(x-x.mean(0))/np.maximum(sd,1e-8)
        # Shrinkage whitening reduces duplicate correlated controls dominating distance.
        cov=x.T@x/max(len(x),1);e,u=np.linalg.eigh(.8*cov+.2*np.eye(len(controls)));w=x@(u/np.sqrt(np.maximum(e,.2)))
        same=NearestNeighbors(n_neighbors=2).fit(w);caliper=float(np.quantile(same.kneighbors(w)[0][:,1],.95))
        nn=NearestNeighbors(n_neighbors=1).fit(w[low]);dist,ids=nn.kneighbors(w[high]);keep=dist[:,0]<=caliper
        a=high[keep];b=low[ids[keep,0]]
        if len(a)<10:
            rows.append(dict(**base,status='no_comparable_controls',n=len(a),controls=len(controls)));continue
        balance=np.abs(x[a].mean(0)-x[b].mean(0));diff=z.target.iloc[a].to_numpy()-z.target.iloc[b].to_numpy();lower,upper=block_ci(diff,z.date.iloc[a])
        unique=len(np.unique(b));passed=bool(balance.max()<=.25 and unique>=20 and len(a)>=30)
        rows.append(dict(**base,status='balanced_descriptive' if passed else 'remaining_imbalance',n=len(a),unique_reference_n=unique,controls=len(controls),
            max_control_smd=float(balance.max()),median_control_smd=float(np.median(balance)),worst_control=controls[int(balance.argmax())],
            feature_high=float(z[feature].iloc[a].median()),feature_low=float(z[feature].iloc[b].median()),
            return_contrast_pp=float(diff.mean()),median_return_contrast_pp=float(np.median(diff)),ci_low=lower,ci_high=upper,
            up_frequency_contrast_pp=float((z.target.iloc[a].gt(0).to_numpy().astype(float)-z.target.iloc[b].gt(0).to_numpy()).mean()*100),
            crash_frequency_contrast_pp=float((z.target.iloc[a].le(-5).to_numpy().astype(float)-z.target.iloc[b].le(-5).to_numpy()).mean()*100),
            uncertainty='Exploratory quarter-cluster by exposed date, fixed matching; reference reuse and matching uncertainty not fully covered'))
    return rows

def analyze(asset,f):
    file=OUT/'checkpoints'/f'{asset}.json'
    if file.exists():return json.loads(file.read_text())
    curves=[];effects=[];hetero=[];audits=[];quality=[]
    for year in [2018,2020]:
        cut=pd.Timestamp(year,1,1);tr=f[f.end_date<cut-pd.Timedelta(days=20)]
        te=f[(f.date>=cut)&(f.end_date<pd.Timestamp(year+2,1,1)-pd.Timedelta(days=20))].iloc[::6].copy()
        if len(tr)<500 or len(te)<40:continue
        assert tr.end_date.max()<te.date.min()
        assert (te.end_date.to_numpy()[:-1]<te.date.to_numpy()[1:]).all()
        audits.append(dict(asset=asset,fold=year,train_end=str(tr.end_date.max()),test_start=str(te.date.min()),test_end=str(te.end_date.max()),n=len(te)))
        models={}
        for kind in OUTCOMES:
            y=tr.target if kind=='return' else (tr.target.gt(0) if kind=='up_score' else tr.target.le(-5)).astype(int)
            if y.nunique()<2:continue
            m=learner(kind).fit(tr[MODEL_FEATURES],y);models[kind]=m
            pred=predict(m,te[MODEL_FEATURES],kind);actual=te.target.to_numpy() if kind=='return' else ((te.target>0) if kind=='up_score' else (te.target<=-5)).astype(float).to_numpy()*100
            quality.append(dict(asset=asset,fold=year,outcome=kind,n=len(te),mae_or_score_brier=float(np.abs(pred-actual).mean()) if kind=='return' else float(np.mean(((pred-actual)/100)**2)),
                constant_reference=float(np.abs(tr.target.median()-actual).mean()) if kind=='return' else float(np.mean((y.mean()-actual/100)**2)),calibrated_probability=False))
        # Batched local endpoint predictions for every variable; no arbitrary large perturbations.
        lows=[];highs=[];meta=[];offset=0
        for feature in RAW:
            edges=np.unique(tr[feature].dropna().quantile(np.linspace(.02,.98,7)).to_numpy())
            if len(edges)<3:continue
            valid=te[feature].between(edges[0],edges[-1]);q=te[valid].copy()
            if len(q)<20:continue
            bins=np.clip(np.searchsorted(edges,q[feature],side='right')-1,0,len(edges)-2)
            a=q[RAW].copy();b=a.copy();a[feature]=edges[bins];b[feature]=edges[bins+1]
            lows.append(coherent(a,feature));highs.append(coherent(b,feature));meta.append((feature,edges,bins,q,offset));offset+=len(q)
        if not lows:continue
        low=pd.concat(lows);high=pd.concat(highs)
        for kind,m in models.items():
            delta=predict(m,high,kind)-predict(m,low,kind)
            for feature,edges,bins,q,start in meta:
                change=delta[start:start+len(q)];local=[];counts=[]
                for k in range(len(edges)-1):
                    mask=bins==k;counts.append(int(mask.sum()));local.append(float(change[mask].mean()) if mask.any() else np.nan)
                if not all(n>=5 for n in counts):continue
                # ALE at bin midpoints; centered over observed bin frequencies.
                local=np.array(local);ale=np.cumsum(local)-.5*local;ale-=np.average(ale,weights=counts)
                for k in range(len(local)):
                    mask=bins==k;ci=block_ci(change[mask],q.date[mask])
                    curves.append(dict(asset=asset,feature=feature,label=labels()[feature],fold=year,outcome=kind,bin=k,low=float(edges[k]),high=float(edges[k+1]),n=counts[k],
                        local_change=float(local[k]),local_ci_low=ci[0],local_ci_high=ci[1],ale=float(ale[k]),observed_return=float(q.target[mask].mean()),observed_down_fraction=float(q.target[mask].lt(0).mean()),
                        observed_crash_fraction=float(q.target[mask].le(-5).mean()),interpretation='Fixed-model local response, not causal effect; scores uncalibrated'))
                effects.append(dict(asset=asset,feature=feature,fold=year,outcome=kind,n=len(q),net_effect=float(local.sum()),range_effect=float(ale.max()-ale.min()),
                    positive_local_fraction=float(np.mean(local>0)),negative_local_fraction=float(np.mean(local<0)),missing_fraction=float(f[feature].isna().mean())))
                if feature in SHOCKS:
                    # Shared shock-local changes, split by state. Not a purified second-order ALE.
                    for state in RAW:
                        if state in SHOCKS:continue
                        pivot=tr[state].median();left=q[state]<=pivot;right=q[state]>pivot
                        if left.sum()<20 or right.sum()<20:continue
                        hetero.append(dict(asset=asset,shock=feature,state=state,fold=year,outcome=kind,low_state_n=int(left.sum()),high_state_n=int(right.sum()),
                            low_state_response=float(change[left].mean()),high_state_response=float(change[right].mean()),
                            response_difference=float(change[right].mean()-change[left].mean()),
                            sign_reversal=bool(change[left].mean()*change[right].mean()<0),
                            note='Descriptive heterogeneity of local shock response; shock-bin mixtures and other states can differ'))
    match=[]
    result=dict(curves=curves,effects=effects,heterogeneity=hetero,matching=match,time_audit=audits,explanation_model_quality=quality)
    file.write_text(json.dumps(result,allow_nan=True));return result

def main():
    OUT.mkdir(parents=True,exist_ok=True);(OUT/'checkpoints').mkdir(exist_ok=True)
    source=ROOT/'reports/rich_context_20261103/learning_table.parquet';d=pd.read_parquet(source);d=d[d.end_date<pd.Timestamp('2022-01-01')-pd.Timedelta(days=20)]
    assets=json.loads((SRC/'selected_assets.json').read_text());gold=ROOT/'exports/seongjin_gold_v1_1/gold_stress_daily.parquet';digest=hashlib.sha256(gold.read_bytes()).hexdigest()
    protocol=dict(features=RAW,model_features=MODEL_FEATURES,aliases=ALIASES,coordinate_definition='Derived feature replaces its primitive; other nonredundant coordinates held fixed. State responses are coordinate dependent, not independent causal effects.',cohort=assets,analysis_label_end=str(d.end_date.max()),folds=[2018,2020],future_test_used=False,
        targets=OUTCOMES,crash_threshold=-5,ALE='6 quantile bins in earlier training 2%-98%; endpoints only inside local bins; >=5 observations/bin; independent 5session outcomes',
        matching='Pre2022 non-overlapping observations, high vs low quartiles, all eligible other raw controls including other shocks; shrinkage whitening; nearest-neighbour historical95% caliper; SMD .25,30 pairs,20 unique references',
        limitations=['Observational conditional association, not causal effect','ALE interprets fitted models, not true mechanism','Logical dependencies among state features remain','Quarter bootstrap fixes model/matches, not full uncertainty','Classifier scores are not calibrated probabilities'],
        reference='https://doi.org/10.1111/rssb.12377',gold_sha256=digest,production=False)
    (OUT/'protocol.json').write_text(json.dumps(protocol,indent=2))
    packs=[];failed=[]
    with threadpool_limits(limits=1,user_api='blas'),ThreadPoolExecutor(max_workers=4) as pool:
        futures={pool.submit(analyze,a,d[d.asset==a].sort_values('date')):a for a in assets}
        for i,fu in enumerate(as_completed(futures),1):
            try:packs.append(fu.result())
            except Exception as e:failed.append(dict(asset=futures[fu],error=repr(e)))
            (OUT/'progress.json').write_text(json.dumps(dict(status='running',completed=i,total=len(assets),failed=failed)));print(i,len(assets),flush=True)
    assert not failed,failed
    for key in packs[0]:pd.DataFrame([r for pack in packs for r in pack[key]]).to_parquet(OUT/(key+'.parquet'),index=False)
    assert hashlib.sha256(gold.read_bytes()).hexdigest()==digest
    (OUT/'progress.json').write_text(json.dumps(dict(status='complete',completed=len(assets),failed=[],gold_unchanged=True)))
if __name__=='__main__':main()

