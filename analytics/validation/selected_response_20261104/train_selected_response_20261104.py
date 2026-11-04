"""Past-only pair selection and response-constrained ablation. Research, not deployment."""
import json, hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed
import numpy as np
import pandas as pd
from lightgbm import LGBMRegressor
from threadpoolctl import threadpool_limits
from analyze_variables_20261104 import ROOT, RAW, SHOCKS
from balance_effect_atlas_20261104 import ALIASES
from report_long_universe import metric

OUT=ROOT/'reports/selected_response_20261104'
ATLAS=ROOT/'reports/effect_atlas_20261104'
STATE=[c for c in RAW if c not in ALIASES and c not in SHOCKS]
METHODS=['all4_median','selected_median','selected_mean','selected_monotone_mean']

def estimator(method, cols, signs):
    args=dict(n_estimators=250,learning_rate=.04,max_depth=4,num_leaves=15,
              min_child_samples=40,random_state=20261104,n_jobs=1,verbosity=-1)
    if method.endswith('median'):args.update(objective='quantile',alpha=.5)
    else:args.update(objective='regression')
    if method=='selected_monotone_mean':
        args.update(monotone_constraints=[int(signs.get(c,0)) for c in cols],monotone_constraints_method='advanced')
    return LGBMRegressor(**args)

def score(z):
    r=metric(z);lo=z.lower;hi=z.upper;y=z.actual
    r.update(coverage80=float(((y>=lo)&(y<=hi)).mean()),width_pp=float((hi-lo).mean()),
             interval_score=float(((hi-lo)+10*(lo-y).clip(lower=0)+10*(y-hi).clip(lower=0)).mean()),
             lower_breach=float((y<lo).mean()),crash_lower_breach=float((y[z.actual<=-5]<lo[z.actual<=-5]).mean()))
    return r

def main():
    OUT.mkdir(exist_ok=True)
    z=pd.read_csv(ATLAS/'충격별_근거통합.csv',dtype={'asset':str})
    checks=dict(balanced=z.status.eq('balanced_descriptive'),two_era_sign=z.return_stable_sign.eq(True),
       ale_balance_agree=np.sign(z.return_effect).eq(np.sign(z.return_contrast_pp)),contrast_at_least_1pp=z.return_contrast_pp.abs().ge(1),
       partial_sign_agree=np.sign(z.slope).eq(np.sign(z.return_contrast_pp)),partial_BY_q=z.exploratory_by_q.lt(.05),
       annual_sign_stable=np.maximum(z.positive_year_fraction,1-z.positive_year_fraction).ge(.8))
    keep=np.logical_and.reduce(list(checks.values()))
    audit=z[['asset','name','feature','return_contrast_pp','return_effect','slope','positive_year_fraction','exploratory_by_q']].copy()
    for name,v in checks.items():audit[name]=v
    audit['selected']=keep;audit.to_csv(OUT/'selection_audit.csv',index=False,encoding='utf-8-sig')
    pairs=z[keep].copy();pairs['sign']=np.sign(pairs.return_contrast_pp).astype(int)
    pairs.to_csv(OUT/'frozen_pairs.csv',index=False,encoding='utf-8-sig')
    protocol=dict(selection_label_end_before='2021-12-12',selection_uses_evaluation=False,
      pairs=len(pairs),assets=pairs.asset.nunique(),methods=METHODS,
      train='end_date < Jan1(previous calendar year) minus 20 days',
      calibration='previous calendar year, label end < evaluation Jan1 minus 20 days, every sixth row',
      evaluation='same preexisting baseline stock/date keys, 2023-2026; reused research period, not blind',
      interval='held-out residual 10th/90th quantiles; no artificial width cap',
      constraints='Only selected shock signs; empirical monotonicity assumption, not causal fact. State unconstrained.',
      korean_air_oil='Fails residual association sign and significance; separate prespecified diagnostic, not eligible pair',
      feature_basis='canonical nonredundant states; no future market return; realized subsequent five-session shocks',
      production_approved=False)
    (OUT/'protocol.json').write_text(json.dumps(protocol,indent=2),encoding='utf-8')
    data=pd.read_parquet(ROOT/'reports/rich_context_20261103/learning_table.parquet')
    ref=pd.read_parquet(ROOT/'reports/variable_analysis_20261104/predictions.parquet');ref=ref[ref.method.eq('baseline')]
    def run(asset):
        f=data[data.asset.eq(asset)].sort_values('date');ps=pairs[pairs.asset.eq(asset)]
        signs=dict(zip(ps.feature,ps.sign));cols=STATE+list(signs)
        records=[];responses=[];timing=[];contrasts=[]
        for year in range(2023,2027):
            cut=pd.Timestamp(year,1,1);calstart=pd.Timestamp(year-1,1,1)
            tr=f[f.end_date<calstart-pd.Timedelta(days=20)]
            ca=f[(f.date>=calstart)&(f.end_date<cut-pd.Timedelta(days=20))].iloc[::6]
            old=ref[ref.asset.eq(asset)&ref.date.dt.year.eq(year)].sort_values('date')
            if old.empty:continue
            te=f.set_index('date').loc[old.date].reset_index()
            assert tr.end_date.max()<ca.date.min() and ca.end_date.max()<te.date.min()
            timing.append(dict(asset=asset,year=year,train_n=len(tr),calibration_n=len(ca),test_n=len(te),
              train_label_end=str(tr.end_date.max()),calibration_start=str(ca.date.min()),calibration_label_end=str(ca.end_date.max()),test_start=str(te.date.min())))
            for method in METHODS+(['air_oil_diagnostic'] if asset=='003490' else []):
                local_signs=signs.copy();features=STATE+SHOCKS if method=='all4_median' else cols.copy()
                fitmethod=method
                if method=='air_oil_diagnostic':
                    features=list(dict.fromkeys(cols+['shock_oil']));local_signs['shock_oil']=-1;fitmethod='selected_monotone_mean'
                m=estimator(fitmethod,features,local_signs).fit(tr[features],tr.target)
                residual=ca.target.to_numpy()-m.predict(ca[features]);qlo,qhi=np.quantile(residual,[.1,.9]);pred=m.predict(te[features])
                r=old[['asset','date','actual']].copy();r['method']=method;r['center']=pred;r['lower']=pred+qlo;r['upper']=pred+qhi
                for s in SHOCKS:r[s]=te[s].to_numpy()
                records.append(r)
                # One-input intervention with all other observed inputs identical; not observed counterfactual truth.
                for s in list(signs)+(['shock_oil'] if asset=='003490' and 'shock_oil' not in signs else []):
                    low,high=tr[s].quantile([.25,.75]);a=te[features].copy();b=a.copy()
                    if s in features:a[s]=low;b[s]=high
                    pl=m.predict(a);ph=m.predict(b)
                    for dt,x,y in zip(te.date,pl,ph):
                        responses.append(dict(asset=asset,date=dt,method=method,shock=s,shock_low=low,shock_high=high,
                          low_prediction=x,high_prediction=y,response_pp=y-x,selected=s in signs))
                    masklo=te[s]<=low;maskhi=te[s]>=high
                    contrasts.append(dict(asset=asset,year=year,method=method,shock=s,low_n=int(masklo.sum()),high_n=int(maskhi.sum()),
                        actual_high_low_pp=float(te.target[maskhi].mean()-te.target[masklo].mean()),
                        predicted_high_low_pp=float(pred[maskhi].mean()-pred[masklo].mean()),
                        controlled_response_pp=float(np.mean(ph-pl)),selected=s in signs))
        return pd.concat(records),responses,timing,contrasts
    packs=[];resp=[];times=[];contrasts=[];fail=[]
    with threadpool_limits(limits=1,user_api='blas'),ThreadPoolExecutor(max_workers=4) as pool:
        futures={pool.submit(run,a):a for a in sorted(pairs.asset.unique())}
        for i,fu in enumerate(as_completed(futures),1):
            try:r,s,t,c=fu.result();packs.append(r);resp+=s;times+=t;contrasts+=c
            except Exception as e:fail.append(dict(asset=futures[fu],error=repr(e)))
            (OUT/'progress.json').write_text(json.dumps(dict(completed=i,total=len(futures),failed=fail)))
            print(i,len(futures),flush=True)
    assert not fail,fail
    p=pd.concat(packs);p.to_parquet(OUT/'predictions.parquet',index=False,compression='zstd')
    pd.DataFrame(resp).to_parquet(OUT/'shock_interventions.parquet',index=False,compression='zstd')
    pd.DataFrame(times).to_csv(OUT/'time_audit.csv',index=False)
    pd.DataFrame(contrasts).to_csv(OUT/'evaluation_contrasts.csv',index=False)
    pd.DataFrame([dict(asset=a,method=m,**score(v)) for (a,m),v in p.groupby(['asset','method'])]).to_csv(OUT/'asset_metrics.csv',index=False)
    pd.DataFrame([dict(method=m,**score(v)) for m,v in p[p.method.isin(METHODS)].groupby('method')]).to_csv(OUT/'aggregate.csv',index=False)
    event=[]
    for _,pair in pairs.iterrows():
        history=data[data.asset.eq(pair.asset)&(data.end_date<pd.Timestamp('2021-12-12'))]
        low,high=history[pair.feature].quantile([.25,.75]);z=p[p.asset.eq(pair.asset)]
        for m,v in z.groupby('method'):
            for scope,w in [('all',v),('shock_tail',v[(v[pair.feature]<=low)|(v[pair.feature]>=high)])]:
                event.append(dict(asset=pair.asset,shock=pair.feature,method=m,scope=scope,**score(w)))
    pd.DataFrame(event).to_csv(OUT/'pair_metrics.csv',index=False)
    # Paired quarter-block uncertainty; every stock in a quarter shares resample weight.
    base=p[p.method.eq('all4_median')];months=pd.period_range(base.date.min(),base.date.max(),freq='Q');rng=np.random.default_rng(20261104)
    draws=rng.integers(0,len(months),size=(2000,len(months)));u=[]
    for m in METHODS[1:]:
        t=p[p.method.eq(m)].merge(base,on=['asset','date'],suffixes=('_new','_base'),validate='one_to_one')
        for name,diff in [('mae',abs(t.center_new-t.actual_new)-abs(t.center_base-t.actual_base)),
              ('direction',(np.sign(t.center_new)==np.sign(t.actual_new)).astype(float)-(np.sign(t.center_base)==np.sign(t.actual_base)).astype(float))]:
            q=pd.DataFrame(dict(block=t.date.dt.to_period('Q'),delta=diff));g=q.groupby('block').delta.agg(['sum','count']).reindex(months,fill_value=0)
            boot=g['sum'].to_numpy()[draws].sum(1)/g['count'].to_numpy()[draws].sum(1)
            lo,hi=np.quantile(boot,[.025,.975]);u.append(dict(method=m,metric=name,delta=diff.mean(),ci_low=lo,ci_high=hi))
    pd.DataFrame(u).to_csv(OUT/'uncertainty.csv',index=False)
    gold=ROOT/'exports/seongjin_gold_v1_1/gold_stress_daily.parquet'
    (OUT/'verification.json').write_text(json.dumps(dict(status='complete',n_assets=pairs.asset.nunique(),n_pairs=len(pairs),
      identical_evaluation_keys=all(set(zip(p[p.method.eq(m)].asset,p[p.method.eq(m)].date))==set(zip(base.asset,base.date)) for m in METHODS),
      gold_sha256=hashlib.sha256(gold.read_bytes()).hexdigest(),azure_modified=False,production_approved=False),indent=2))
    (OUT/'progress.json').write_text(json.dumps(dict(status='complete',completed=len(futures),failed=[])))
if __name__=='__main__':main()
