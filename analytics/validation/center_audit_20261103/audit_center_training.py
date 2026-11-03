"""Frozen-cohort data/learning ablation. No cloud, Gold or production changes."""
import json, hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed
import numpy as np
import pandas as pd
from asset_feature_research import ROOT, EXPANDED, SHOCKS, model
from reselect_shock_direction import fit
from report_long_universe import metric

SRC=ROOT/'reports/long_universe_20261103'
OUT=ROOT/'reports/center_audit_20261103'

def save(name,obj):
    (OUT/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf8')

def main():
    OUT.mkdir(exist_ok=True)
    gold=ROOT/'exports/seongjin_gold_v1_1/gold_stress_daily.parquet'
    digest=hashlib.sha256(gold.read_bytes()).hexdigest()
    pairs=pd.read_csv(SRC/'eligible_pairs.csv',dtype={'asset':str})
    assets=sorted(pairs.asset.unique())
    selected=pairs.groupby('asset').shock.apply(list).to_dict()
    save('protocol.json',dict(cohort='Frozen101; no reselection',evaluation='Exact previous asset/date rows restricted by historical feature quality only; all methods same keys',split='Quarterly2023-2026, train label end < quarter start minus20days',methods=['legacy_normalized','clean_normalized','clean_raw','clean_weighted_normalized','selected_shocks_raw','prior_us_state_raw','state_raw','selected_direction'],changes={'quality':'Exclude rows whose preceding61 price observations contain invalid quality, nonpositive price or mock; no actual return threshold', 'raw':'Same median LightGBM, unscaled return objective', 'weighted':'Normalized return objective weighted by pre-state scale; equivalent absolute-error units', 'selected':'Only pre2022 selected shocks for stock plus same state', 'timing':'US rate/WTI/VIX STATE levels lag one KRX trading row; retrospective5day shocks and target unchanged; sensitivity not certified release availability'},no_test_tuning=True,independent_blind=False,production=False,gold_sha256=digest))
    g=pd.read_parquet(SRC/'research_daily_input.parquet').sort_values(['asset_id','trading_date'])
    d=pd.read_parquet(SRC/'learning_table.parquet');d=d[d.asset.isin(assets)].copy()
    old=pd.read_parquet(SRC/'predictions.parquet');old=old[old.selected & old.method.eq('all4_lgb')].copy()
    flags=[];audit=[];checks=[]
    for a,z in g[g.asset_id.isin(assets)].groupby('asset_id'):
        z=z.sort_values('trading_date').reset_index(drop=True)
        ok=z.quality_status.eq('valid') & z.close.gt(0) & z.is_mock.eq(False)
        clean=ok.rolling(61,min_periods=61).sum().eq(61)
        v=pd.DataFrame({'asset':a,'date':z.trading_date,'clean_history':clean})
        for dest,col in [('rate_level','us_treasury_10y'),('oil_level','wti'),('vix_level','vix')]:v[dest+'_prior']=z[col].shift(1)
        flags.append(v)
        exact=(z.close.shift(-5)/z.close-1)*100
        x=d[d.asset.eq(a)].merge(pd.DataFrame({'date':z.trading_date,'recomputed_target':exact,'recomputed_end':z.trading_date.shift(-5)}),on='date',validate='one_to_one')
        assert np.allclose(x.target,x.recomputed_target,atol=1e-10)
        assert x.end_date.eq(x.recomputed_end).all()
        audit.append(dict(asset=a,rows=len(z),duplicate_dates=int(z.trading_date.duplicated().sum()),invalid_history_rows=int((~clean).sum()),missing_publication_times=int(z.price_available_at.isna().sum()),learning_rows=len(x),target_error_max=float((x.target-x.recomputed_target).abs().max())))
    d=d.merge(pd.concat(flags),on=['asset','date'],validate='one_to_one')
    assert np.isfinite(d[EXPANDED+['scale','target']]).all().all() and d.scale.gt(0).all()
    pd.DataFrame(audit).to_csv(OUT/'data_audit.csv',index=False)
    joined=old.merge(d[['asset','date','clean_history']],on=['asset','date'],validate='one_to_one')
    joined[~joined.clean_history].to_csv(OUT/'excluded_evaluation_rows.csv',index=False)
    old=joined[joined.clean_history].drop(columns='clean_history')
    old['method']='legacy_normalized'
    oil=g.groupby('trading_date').wti.first().sort_index()
    bad=set(oil.index[oil.le(0).rolling(6).max().shift(-5).eq(1)])
    state=[c for c in EXPANDED if c not in SHOCKS]
    allrows=[old];fail=[];allfolds=[]
    (OUT/'checkpoints').mkdir(exist_ok=True)

    def run(a):
        f=d[d.asset.eq(a)].sort_values('date');base=old[old.asset.eq(a)].sort_values('date');rows=[];folds=[]
        for quarter,b in base.groupby(base.date.dt.to_period('Q')):
            cut=quarter.start_time
            original=f[(f.end_date<cut-pd.Timedelta(days=20)) & ~f.date.isin(bad)]
            tr=original[original.clean_history].copy()
            te=f.set_index('date').loc[b.date].reset_index()
            assert len(tr)>=500 and tr.end_date.max()<te.date.min()
            assert np.allclose(te.target,b.actual)
            fold=dict(asset=a,quarter=str(quarter),original_train_n=len(original),clean_train_n=len(tr),train_end=str(tr.end_date.max()),test_start=str(te.date.min()),test_n=len(te),low_scale_mean=float(tr.loc[tr.scale<=tr.scale.median(),'scale'].mean()),high_scale_mean=float(tr.loc[tr.scale>tr.scale.median(),'scale'].mean()))
            folds.append(fold)
            for name in ['clean_normalized','clean_raw','clean_weighted_normalized','selected_shocks_raw','prior_us_state_raw','state_raw','selected_direction']:
                cols=state+selected[a] if name in ['selected_shocks_raw','selected_direction'] else state if name=='state_raw' else EXPANDED
                tx=tr[cols].copy();ex=te[cols].copy()
                if name=='prior_us_state_raw':
                    for c in ['rate_level','oil_level','vix_level']:
                        tx[c]=tr[c+'_prior'].to_numpy();ex[c]=te[c+'_prior'].to_numpy()
                if name=='selected_direction':
                    nz=tr.target.ne(0);m=fit(tx[nz],tr.loc[nz,'target'].gt(0));up=m.predict(ex)
                    pred=np.where(up,tr.loc[tr.target>0,'target'].median(),tr.loc[tr.target<0,'target'].median())
                else:
                    normalized=name in ['clean_normalized','clean_weighted_normalized']
                    y=tr.target/tr.scale if normalized else tr.target
                    m=model('lgb');kwargs={'sample_weight':tr.scale.to_numpy()} if name=='clean_weighted_normalized' else {}
                    m.fit(tx,y,**kwargs);pred=m.predict(ex)*(te.scale.to_numpy() if normalized else 1)
                out=b.copy();out['method']=name;out['center']=pred;rows.append(out)
        result=pd.concat(rows,ignore_index=True);result.to_parquet(OUT/'checkpoints'/f'{a}.parquet',index=False)
        return result,folds

    with ThreadPoolExecutor(max_workers=3) as pool:
        futures={pool.submit(run,a):a for a in assets}
        for i,fut in enumerate(as_completed(futures),1):
            try:
                result,folds=fut.result();allrows.append(result);allfolds.extend(folds)
            except Exception as e:fail.append(dict(asset=futures[fut],error=repr(e)))
            save('progress.json',dict(completed=i,total=len(assets),failed=fail,status='running'))
            print(i,len(assets),futures[fut],flush=True)
    if fail:raise RuntimeError(str(fail))
    r=pd.concat(allrows,ignore_index=True);r.to_parquet(OUT/'predictions.parquet',index=False)
    assert r.groupby(['asset','date']).size().eq(8).all()
    pd.DataFrame(allfolds).to_csv(OUT/'time_audit.csv',index=False)
    event=pd.Series(False,index=r.index)
    for _,p in pairs.iterrows():event |= r.asset.eq(p.asset) & r[p.shock+'_event']
    summaries=[];individual=[]
    for scope,mask in [('all',pd.Series(True,index=r.index)),('selected_shock_events',event),('crash',r.actual<=-5),('rally',r.actual>=5)]:
        for method,z in r[mask].groupby('method'):summaries.append(dict(scope=scope,method=method,**metric(z)))
    for (asset,method),z in r.groupby(['asset','method']):individual.append(dict(asset=asset,method=method,**metric(z)))
    pd.DataFrame(summaries).to_csv(OUT/'metrics.csv',index=False);pd.DataFrame(individual).to_csv(OUT/'asset_metrics.csv',index=False)
    assert hashlib.sha256(gold.read_bytes()).hexdigest()==digest
    save('verification.json',dict(targets_recomputed=True,finite_features=True,same_evaluation_keys=True,training_labels_precede_evaluation=True,gold_unchanged=True,publication_times_certified=False,selection_frozen=True,evaluation_reused=True,production=False))
    save('progress.json',dict(completed=len(assets),total=len(assets),failed=[],status='complete'))

if __name__=='__main__':main()

