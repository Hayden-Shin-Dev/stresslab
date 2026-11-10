"""Per-stock quarterly training, frozen candidate set and source-quality gates."""
import json,hashlib,joblib,os
from concurrent.futures import ThreadPoolExecutor,as_completed
import numpy as np
import pandas as pd
from asset_feature_research import ROOT,EXPANDED,SHOCKS,make_data,model
from select_exposure_universe import assemble
from reselect_shock_direction import fit
from select_long_universe import OUT

def main():
    status=json.loads((OUT/'collection_progress.json').read_text());assert status['status']=='complete' and not status['failed']
    selected=set(json.loads((OUT/'selected_assets.json').read_text()));controls=json.loads((ROOT/'reports/exposure_universe_20261103/selected_assets.json').read_text());assets=sorted(selected|set(controls))
    gold=ROOT/'exports/seongjin_gold_v1_1/gold_stress_daily.parquet';goldhash=hashlib.sha256(gold.read_bytes()).hexdigest()
    g,quality=assemble(assets);g=g[g.trading_date>=pd.Timestamp('2000-01-01')].copy();assert not g.duplicated(['asset_id','trading_date']).any();quality.to_csv(OUT/'training_source_quality.csv',index=False)
    g.to_parquet(OUT/'research_daily_input.parquet',index=False);d,_=make_data(g);d=d[d.asset.isin(assets)];d.to_parquet(OUT/'learning_table.parquet',index=False)
    oil=g.groupby('trading_date').wti.first().sort_index();bad=set(pd.to_datetime(oil.index[oil.le(0).rolling(6).max().shift(-5).eq(1)]))
    state=[c for c in EXPANDED if c not in SHOCKS];raw_audit=[]
    for asset,z in g[g.asset_id.isin(assets)].groupby('asset_id'):
        raw_audit.append(dict(asset=asset,calendar_rows=len(z),observed_close_rows=int(z.close.notna().sum()),valid_rows=int(z.quality_status.eq('valid').sum()),quarantined_rows=int(z.quality_status.eq('quarantined').sum()),missing_rows=int(z.quality_status.eq('missing').sum()),nonpositive_price=int(z.close.le(0).sum()),zero_volume=int(z.volume.eq(0).sum()),available_at_missing=int(z.available_at.isna().sum()) if 'available_at' in z else len(z),learning_rows=int(d.asset.eq(asset).sum())))
    pd.DataFrame(raw_audit).to_csv(OUT/'data_quality.csv',index=False)
    checkpoints=OUT/'checkpoints';checkpoints.mkdir(exist_ok=True);allrows=[];allaud=[];fail=[]
    def run(asset):
        f=d[d.asset.eq(asset)].sort_values('date');teparts=[]
        for yr in range(2023,2027):
            z=f[(f.date>=pd.Timestamp(yr,1,1))&(f.date<pd.Timestamp(yr+1,1,1))].iloc[::6];teparts.append(z[z.end_date<pd.Timestamp(yr+1,1,1)])
        te=pd.concat(teparts);rows=[];audit=[];responses=[]
        if not len(te):return [],[],dict(asset=asset,reason='no_valid_evaluation_rows')
        for period,test in te.groupby(te.date.dt.to_period('Q')):
            cut=period.start_time;train=f[(f.end_date<cut-pd.Timedelta(days=20))&~f.date.isin(bad)]
            if len(train)<500:raise RuntimeError('insufficient_training_rows:'+asset)
            assert train.end_date.max()<test.date.min()
            nz=train[train.target.ne(0)];ys=nz.target.gt(0);neg=nz.loc[~ys,'target'].median();pos=nz.loc[ys,'target'].median()
            thresholds={s:float(train[s].abs().quantile(.75)) for s in SHOCKS}
            configurations=[('state_lgb',state,'lgb'),('all4_lgb',EXPANDED,'lgb'),('all4_lgb_2016plus',EXPANDED,'lgb'),('all4_ridge',EXPANDED,'ridge'),('state_direction',state,'direction'),('all4_direction',EXPANDED,'direction')]
            for name,cols,kind in configurations:
                if kind=='direction':
                    m=fit(nz[cols],ys);prob=m.predict_proba(test[cols])[:,1];pred=np.where(prob>=.5,pos,neg)
                else:
                    training=train[train.date>=pd.Timestamp('2016-01-01')] if name=='all4_lgb_2016plus' else train
                    m=model(kind);m.fit(training[cols],training.target/training.scale);pred=m.predict(test[cols])*test.scale.to_numpy();prob=np.full(len(test),np.nan)
                if name=='all4_lgb':
                    for shock in SHOCKS:
                        lo,hi=train[shock].quantile([.05,.95]);step=float(train[shock].std()*.25)
                        valid=test[shock].between(lo,hi-step)
                        if step>0 and valid.any():
                            alt=test.loc[valid,cols].copy();before=m.predict(alt);alt[shock]+=step
                            changes=(m.predict(alt)-before)*test.loc[valid,'scale'].to_numpy()
                            responses.append(dict(asset=asset,quarter=str(period),shock=shock,step=step,n=len(changes),mean_change_pp=float(changes.mean()),positive_fraction=float((changes>1e-8).mean()),negative_fraction=float((changes< -1e-8).mean())))
                for i,(_,t) in enumerate(test.iterrows()):
                    rows.append(dict(asset=asset,selected=asset in selected,date=t.date,end_date=t.end_date,method=name,actual=t.target,center=float(pred[i]),up_score=float(prob[i]),**{s:float(t[s]) for s in SHOCKS},**{s+'_event':bool(abs(t[s])>=thresholds[s]) for s in SHOCKS}))
                if period==te.date.dt.to_period('Q').max() and name in ['all4_lgb','all4_ridge','all4_direction']:
                    folder=OUT/'models'/asset;folder.mkdir(parents=True,exist_ok=True);joblib.dump(dict(model=m,features=cols,fit_time=str(cut),train_label_end=str(train.end_date.max()),normalized_target=kind!='direction',negative_median=neg,positive_median=pos,approved=False),folder/(name+'.joblib'))
            audit.append(dict(asset=asset,quarter=str(period),train_n=len(train),train_label_end=str(train.end_date.max()),test_start=str(test.date.min()),test_n=len(test),**thresholds))
        pd.DataFrame(rows).to_parquet(checkpoints/(asset+'.parquet'),index=False);pd.DataFrame(audit).to_csv(checkpoints/(asset+'_audit.csv'),index=False)
        pd.DataFrame(responses).to_csv(checkpoints/(asset+'_responses.csv'),index=False)
        return rows,audit,None
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures={pool.submit(run,a):a for a in assets}
        for i,future in enumerate(as_completed(futures),1):
            a=futures[future]
            try:
                rows,audit,error=future.result();allrows.extend(rows);allaud.extend(audit)
                if error:fail.append(error)
            except Exception as e:fail.append(dict(asset=a,reason=type(e).__name__,detail=str(e)[:180]))
            (OUT/'training_progress.json').write_text(json.dumps(dict(completed=i,total=len(assets),failed=fail,last_asset=a,status='running'),indent=2))
            print(i,len(assets),a,flush=True)
    r=pd.DataFrame(allrows);r.to_parquet(OUT/'predictions.parquet',index=False);pd.DataFrame(allaud).to_csv(OUT/'time_audit.csv',index=False)
    response_files=list(checkpoints.glob('*_responses.csv'))
    if response_files:pd.concat([pd.read_csv(p,dtype={'asset':str}) for p in response_files],ignore_index=True).to_csv(OUT/'response_sensitivity.csv',index=False)
    assert not r.duplicated(['asset','date','method']).any();assert r.groupby(['asset','date']).size().eq(6).all()
    assert hashlib.sha256(gold.read_bytes()).hexdigest()==goldhash
    (OUT/'training_progress.json').write_text(json.dumps(dict(completed=len(assets),total=len(assets),failed=fail,status='complete' if not fail else 'partial'),indent=2))
    (OUT/'verification.json').write_text(json.dumps(dict(assets_evaluated=int(r.asset.nunique()),all_methods_same_asset_date_keys=True,train_labels_precede_quarter=True,gold_unchanged=True,gold_sha256=goldhash,failed_assets=fail,production=False),indent=2))
if __name__=='__main__':main()
