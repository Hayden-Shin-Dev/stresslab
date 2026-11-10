"""Variable-level diagnosis, chronological partial associations and frozen model ablations."""
import json,hashlib,time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,as_completed
import numpy as np
import pandas as pd
from lightgbm import LGBMRegressor
from threadpoolctl import threadpool_limits
from train_rich_context import ALL,CROSS,INTER,ROOT,SRC
from diagnose_rich_context import derive
from asset_feature_research import SHOCKS,model
from research_shock_context import CONTEXT
from report_long_universe import metric

OUT=ROOT/'reports/variable_analysis_20261104'
RAW=[c for c in ALL if c not in INTER+CROSS]
LINKS={s+'__'+c:[s,c] for s in SHOCKS for c in CONTEXT}
LINKS.update(foreign_fx=['foreign_flow_20','shock_fx'],institution_vix=['institution_flow_20','shock_vix'],debt_rate=['debt_assets','shock_rate'],operating_fx=['operating_assets','shock_fx'])
MANDATORY=SHOCKS+['market_trend20','market_vol20','asset_trend20','asset_vol20','vix_level']

def complex_model():
    return LGBMRegressor(objective='quantile',alpha=.5,n_estimators=500,learning_rate=.025,max_depth=6,num_leaves=31,min_child_samples=60,reg_lambda=5,random_state=20261104,n_jobs=2,verbosity=-1)

def nuisance():
    return LGBMRegressor(objective='regression',n_estimators=150,learning_rate=.04,max_depth=4,num_leaves=15,min_child_samples=60,reg_lambda=5,random_state=20261104,n_jobs=2,verbosity=-1)

def partial_statistics(f,asset):
    rows=[];correlations=[]
    med=f[ALL].median().fillna(0);x=f[ALL].fillna(med).to_numpy();y=f.target.to_numpy()
    scale=x.std(axis=0);xn=(x-x.mean(axis=0))/np.maximum(scale,1e-8);yn=(y-y.mean())/max(y.std(),1e-8)
    cov=np.cov(np.column_stack([xn,yn]),rowvar=False);precision=np.linalg.inv(cov+np.eye(len(ALL)+1)*.05)
    partial=-precision[:-1,-1]/np.sqrt(precision.diagonal()[:-1]*precision[-1,-1])
    for i,c in enumerate(ALL):
        valid=f[c].notna();q=f.loc[valid,[c,'target','date']];slopes=[]
        for _,v in q.groupby(q.date.dt.year):
            if len(v)>=100 and v[c].std()>1e-9:slopes.append(v[c].corr(v.target))
        pearson=q[c].corr(q.target) if len(q)>20 and q[c].std()>1e-9 else np.nan
        rows.append(dict(asset=asset,feature=c,n=int(valid.sum()),missing_fraction=float(1-valid.mean()),distinct=int(q[c].nunique()),pearson=pearson,
            spearman=q[c].corr(q.target,method='spearman') if np.isfinite(pearson) else np.nan,regularized_partial_corr=float(partial[i]) if scale[i]>1e-8 else np.nan,
            years=len(slopes),positive_year_fraction=float(np.mean(np.array(slopes)>0)) if slopes else np.nan,negative_year_fraction=float(np.mean(np.array(slopes)<0)) if slopes else np.nan,
            derived_feature=c in LINKS,training_only=True))
    corr=f[RAW].corr()
    for i,a in enumerate(RAW):
        for b in RAW[i+1:]:
            if np.isfinite(corr.loc[a,b]) and abs(corr.loc[a,b])>=.8:correlations.append(dict(asset=asset,feature_a=a,feature_b=b,correlation=corr.loc[a,b]))
    return rows,correlations

def slope_hac(x,y):
    x=np.asarray(x);y=np.asarray(y);design=np.column_stack([np.ones(len(x)),x]);inv=np.linalg.pinv(design.T@design);beta=inv@design.T@y;e=y-design@beta;s=design*e[:,None];meat=s.T@s
    for lag in range(1,min(6,len(x))):
        gamma=s[lag:].T@s[:-lag];meat+=(1-lag/6)*(gamma+gamma.T)
    se=float(np.sqrt(max((inv@meat@inv)[1,1],0)))
    return float(beta[1]),se

def residual_associations(f,asset):
    residuals=[];summary=[];stability=[]
    for year in range(2016,2022):
        cut=pd.Timestamp(year,1,1);train=f[f.end_date<cut-pd.Timedelta(days=20)]
        test=f[(f.date>=cut)&(f.end_date<pd.Timestamp(year+1,1,1)-pd.Timedelta(days=20))].iloc[::6]
        if len(train)<500 or len(test)<20:continue
        for shock in SHOCKS:
            controls=[c for c in RAW if c!=shock]
            # Both nuisance models see earlier labels only. Other three shocks are conditioning variables.
            my=nuisance().fit(train[controls],train.target);ms=nuisance().fit(train[controls],train[shock])
            ey=test.target.to_numpy()-my.predict(test[controls]);es=test[shock].to_numpy()-ms.predict(test[controls])
            for date,end,a,b in zip(test.date,test.end_date,es,ey):residuals.append(dict(asset=asset,shock=shock,year=year,date=date,end_date=end,shock_residual=a,return_residual=b,train_end=train.end_date.max()))
            slope,se=slope_hac(es,ey);stability.append(dict(asset=asset,shock=shock,year=year,n=len(test),slope=slope,hac_se=se))
    frame=pd.DataFrame(residuals)
    if len(frame):
        for shock,z in frame.groupby('shock'):
            slope,se=slope_hac(z.shock_residual,z.return_residual);annual=[v['slope'] for v in stability if v['shock']==shock]
            summary.append(dict(asset=asset,shock=shock,n=len(z),slope=slope,hac_se=se,ci_low=slope-1.96*se,ci_high=slope+1.96*se,
                residual_correlation=z.shock_residual.corr(z.return_residual),years=len(annual),positive_year_fraction=float(np.mean(np.array(annual)>0)),
                interpretation='Conditional residual association, not independently identified causal effect'))
    return residuals,summary,stability

def permutation_analysis(train,test,m,asset):
    rng=np.random.default_rng(20261104);base=m.predict(test[ALL]);err=np.abs(base-test.target.to_numpy()).mean();rows=[]
    # Market bins are cut using training medians, never using later evaluation results.
    group=(test.market_trend20>train.market_trend20.median()).astype(int)*2+(test.market_vol20>train.market_vol20.median()).astype(int)
    for feature in RAW:
        for mode in ['unconditional','within_market_state']:
            changes=[]
            for repeat in range(3):
                x=test.copy();values=x[feature].to_numpy().copy()
                groups=[np.arange(len(x))] if mode=='unconditional' else [np.where(group.to_numpy()==g)[0] for g in sorted(group.unique())]
                for ids in groups:values[ids]=rng.permutation(values[ids])
                x[feature]=values;x=derive(x);pred=m.predict(x[ALL]);changes.append(float(np.abs(pred-test.target.to_numpy()).mean()-err))
            rows.append(dict(asset=asset,feature=feature,mode=mode,n=len(test),mae_increase_pp=float(np.mean(changes)),repeat_sd=float(np.std(changes)),period='2022_selection',causal_effect=False))
    shap=m.predict(test[ALL],pred_contrib=True);assert np.allclose(shap.sum(axis=1),base)
    shap_rows=[dict(asset=asset,feature=c,mean_abs_contribution_pp=float(np.abs(shap[:,i]).mean()),mean_signed_contribution_pp=float(shap[:,i].mean()),period='2022_selection') for i,c in enumerate(ALL)]
    rank=sorted([v for v in rows if v['mode']=='within_market_state' and v['mae_increase_pp']>0],key=lambda v:-v['mae_increase_pp'])
    selected=list(dict.fromkeys(MANDATORY+[v['feature'] for v in rank[:30]]))
    selected += [c for c,parents in LINKS.items() if all(p in selected for p in parents)]
    return rows,shap_rows,selected

def response_maps(f,m,asset):
    rows=[]
    # Non-overlapping pre-2022 observations; bin edges estimated from that historical sample.
    z=f.iloc[::6].copy()
    for shock in SHOCKS:
        edges=np.unique(z[shock].quantile([.05,.25,.5,.75,.95]).to_numpy())
        if len(edges)<3:continue
        for modifier in ['market_trend20','market_vol20','foreign_flow_20','institution_flow_20','debt_assets']:
            pivot=z[modifier].median()
            for state,mask in [('low',z[modifier]<=pivot),('high',z[modifier]>pivot)]:
                for lo,hi in zip(edges[:-1],edges[1:]):
                    q=z[mask&z[shock].between(lo,hi)].copy()
                    if len(q)<15:continue
                    left=q.copy();right=q.copy();left[shock]=lo;right[shock]=hi
                    change=m.predict(derive(right)[ALL])-m.predict(derive(left)[ALL])
                    rows.append(dict(asset=asset,shock=shock,modifier=modifier,state=state,n=len(q),shock_low=lo,shock_high=hi,
                        observed_return_median=float(q.target.median()),observed_down_fraction=float(q.target.lt(0).mean()),
                        model_local_change_pp=float(np.mean(change)),period='pre2022_training',model_in_sample=True,causal_effect=False))
    return rows

def main():
    OUT.mkdir(exist_ok=True);(OUT/'checkpoints').mkdir(exist_ok=True)
    data_path=ROOT/'reports/rich_context_20261103/learning_table.parquet';d=derive(pd.read_parquet(data_path))
    ref=pd.read_parquet(ROOT/'reports/rich_context_20261103/predictions.parquet');ref=ref[ref.method.eq('all')]
    assets=json.loads((SRC/'selected_assets.json').read_text());gold=ROOT/'exports/seongjin_gold_v1_1/gold_stress_daily.parquet'
    protocol=dict(stocks=assets,variables=ALL,raw_features=RAW,derived_links=LINKS,selection='All variable diagnostics pre2022; feature selection uses2022 only; no stock reselection',
        evaluation='2023-2026 reused research period, not blind. Fixed original asset/date keys, annual refits,20day label embargo. Baseline retrained on same annual data.',
        partial='Chronological2016-2021 OOS nuisance residualization of each shock against other3 shocks+all pre-shock raw features. HAC5 residual slopes; conditional association not causality.',
        permutation='3permutations per raw variable, unconditional and within2x2markettrend/vol bins. Derived shock interactions rebuilt. Diagnostic, not physical intervention.',
        complex_parameters=complex_model().get_params(),baseline_parameters=model('lgb').get_params(),
        models=['baseline','complex_all','analysis_selected','no_shocks']+['without_'+s for s in SHOCKS],
        gold_sha256=hashlib.sha256(gold.read_bytes()).hexdigest(),production=False)
    (OUT/'protocol.json').write_text(json.dumps(protocol,indent=2),encoding='utf8')
    fingerprint=hashlib.sha256(Path(__file__).read_bytes()+data_path.read_bytes()).hexdigest();packs=[];fail=[]
    def run(asset):
        path=OUT/'checkpoints'/f'{asset}.json'
        if path.exists():
            cached=json.loads(path.read_text(encoding='utf8'))
            if cached['fingerprint']==fingerprint:return cached['result']
        f=d[d.asset.eq(asset)].sort_values('date');before=f[f.end_date<pd.Timestamp('2022-01-01')-pd.Timedelta(days=20)]
        validation=f[(f.date>=pd.Timestamp('2022-01-01'))&(f.end_date<pd.Timestamp('2023-01-01')-pd.Timedelta(days=20))].iloc[::6]
        assert len(before)>=500 and len(validation)>=20
        variables,corr=partial_statistics(before,asset);res,partial,stability=residual_associations(before,asset)
        selection_model=complex_model().fit(before[ALL],before.target)
        importance,shap,selected=permutation_analysis(before,validation,selection_model,asset)
        maps=response_maps(before,selection_model,asset)
        predictions=[];times=[];sensitivity=[]
        for year in range(2023,2027):
            cut=pd.Timestamp(year,1,1);tr=f[f.end_date<cut-pd.Timedelta(days=20)];old=ref[(ref.asset==asset)&(ref.date.dt.year==year)].sort_values('date')
            te=f.set_index('date').loc[old.date].reset_index()
            if te.empty:continue
            assert tr.end_date.max()<te.date.min();assert (te.end_date.to_numpy()[:-1]<te.date.to_numpy()[1:]).all()
            specs={'baseline':ALL,'complex_all':ALL,'analysis_selected':selected,'no_shocks':[c for c in RAW if c not in SHOCKS]}
            for s in SHOCKS:specs['without_'+s]=[c for c in ALL if c!=s and s not in LINKS.get(c,[])]
            for name,cols in specs.items():
                m=(model('lgb') if name=='baseline' else complex_model()).fit(tr[cols],tr.target);pred=m.predict(te[cols])
                assert np.allclose(te.target,old.actual)
                for i,(_,row) in enumerate(old.iterrows()):
                    item=row.to_dict();item.update(method=name,center=float(pred[i]));predictions.append(item)
                if name=='complex_all':
                    for s,step in zip(SHOCKS,[1,25,10,5]):
                        lower=te.copy();upper=te.copy();lower[s]-=step;upper[s]+=step
                        delta=m.predict(derive(upper)[cols])-m.predict(derive(lower)[cols])
                        support=(lower[s]>=tr[s].quantile(.01))&(upper[s]<=tr[s].quantile(.99))
                        sensitivity.append(dict(asset=asset,year=year,shock=s,step_each_side=step,mean_change_pp=float(delta.mean()),positive_fraction=float((delta>0).mean()),
                            marginal_supported_n=int(support.sum()),supported_mean_change_pp=float(delta[support].mean()) if support.any() else None,n=len(te),joint_support_certified=False))
            times.append(dict(asset=asset,year=year,train_n=len(tr),train_label_end=str(tr.end_date.max()),test_start=str(te.date.min()),test_n=len(te)))
        result=dict(variables=variables,correlations=corr,partial_residuals=res,partial=partial,stability=stability,importance=importance,shap=shap,
            selected=[dict(asset=asset,feature=c) for c in selected],maps=maps,predictions=predictions,time_audit=times,sensitivity=sensitivity)
        # Timestamp serialization only; no credentials or source records.
        path.write_text(json.dumps(dict(fingerprint=fingerprint,result=result),default=str),encoding='utf8');return result
    with threadpool_limits(limits=1,user_api='blas'),ThreadPoolExecutor(max_workers=6) as pool:
        futures={pool.submit(run,a):a for a in assets}
        for i,future in enumerate(as_completed(futures),1):
            try:packs.append(future.result())
            except Exception as e:fail.append(dict(asset=futures[future],error=repr(e)))
            (OUT/'progress.json').write_text(json.dumps(dict(status='running',completed=i,total=len(assets),failed=fail),indent=2));print(i,len(assets),flush=True)
    assert not fail,fail
    for key in packs[0]:
        frame=pd.DataFrame([row for p in packs for row in p[key]])
        if key=='predictions':
            frame.date=pd.to_datetime(frame.date);frame.end_date=pd.to_datetime(frame.end_date);assert frame.groupby(['asset','date']).method.nunique().eq(8).all()
            frame.to_parquet(OUT/'predictions.parquet',index=False)
        else:frame.to_csv(OUT/(key+'.csv'),index=False)
    assert hashlib.sha256(gold.read_bytes()).hexdigest()==protocol['gold_sha256']
    (OUT/'progress.json').write_text(json.dumps(dict(status='complete',completed=len(assets),failed=[],gold_unchanged=True),indent=2))

if __name__=='__main__':main()
