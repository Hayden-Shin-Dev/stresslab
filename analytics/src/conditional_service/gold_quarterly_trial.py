"""Gold-preserving B134 transfer with explicit chronology/provenance ablations."""
import json,hashlib
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler
from catboost import CatBoostRegressor
from threadpoolctl import threadpool_limits
from .core import features,STATE,ASSET,SHOCKS
from .preopen_method_trial import SOURCE,LEVELS,metrics

OUT=Path('reports/gold_quarterly_trial_20261105');F=STATE+ASSET+SHOCKS

def prep(g):
    x=features(g);sc=[]
    for a,z in g.groupby('asset_id'):
        z=z.sort_values('trading_date');r=np.log(z.close.where(z.close>0)).diff()*100
        sc.append(pd.DataFrame(dict(date=pd.to_datetime(z.trading_date),asset=a,ewma=np.sqrt(r.pow(2).ewm(alpha=.06,adjust=False).mean()).clip(lower=.05)*np.sqrt(5))))
    return x.merge(pd.concat(sc),on=['date','asset'],validate='one_to_one')

def fit_predict(tr,te,cols,cat=False):
    y=100*np.log1p(tr.target.to_numpy()/100)/tr.ewma.to_numpy()
    base=np.quantile(y,LEVELS)-y.mean()
    scaler=StandardScaler().fit(tr[cols]);x=scaler.transform(tr[cols]);xt=scaler.transform(te[cols])
    if cat:m=CatBoostRegressor(iterations=150,depth=3,learning_rate=.04,loss_function='Quantile:alpha=0.5',random_seed=20261104,thread_count=2,verbose=False,allow_writing_files=False).fit(x,y)
    else:m=Ridge(alpha=100).fit(x,y)
    loc=m.predict(xt);v=100*np.expm1((loc[:,None]+base)*te.ewma.to_numpy()[:,None]/100)
    return np.quantile(v,[.05,.1,.5,.9,.95],axis=1).T

def main():
    OUT.mkdir(exist_ok=True)
    paths=[Path('reports/support_expansion_20261104/research_input.parquet'),Path('reports/service_scope_20261105/corrected_daily_input.parquet'),Path('reports/service_scope_20261105/final_service_bundle.joblib')]
    hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    old=prep(pd.read_parquet(paths[0]));new=prep(pd.read_parquet(paths[1]))
    known=pd.read_parquet('reports/service_scope_20261105/corrected_features.parquet')[['date','asset','label_known_by']]
    new=new.merge(known,on=['date','asset'],validate='one_to_one')
    # Supplemental US observations are shifted to information available by KRX close,
    # never use the next morning's US move to explain the previous close.
    ew= pd.read_csv(SOURCE/'research/results/project_b_ewy_inputs_v123/features.csv')
    us= pd.read_csv(SOURCE/'research/results/project_c_preopen_v9/preopen_features.csv')
    ex=ew[['origin','decision_utc','ewy_move_log_pct','assumed_available_utc']].merge(us[['origin','us_move_log_pct','market_close_assumed_available_utc']],on='origin',validate='one_to_one')
    ex['available']=pd.to_datetime(ex.decision_utc,utc=True)
    assert (pd.to_datetime(ex.assumed_available_utc,utc=True)<=ex.available).all()
    assert (pd.to_datetime(ex.market_close_assumed_available_utc,utc=True)<=ex.available).all()
    days=pd.DataFrame(dict(date=sorted(old.date.unique())));days['cutoff']=pd.to_datetime(days.date,utc=True)+pd.Timedelta(hours=6,minutes=30)
    ext=pd.merge_asof(days.sort_values('cutoff'),ex.sort_values('available'),left_on='cutoff',right_on='available',direction='backward',tolerance=pd.Timedelta(days=4))
    assert (ext.available.dropna()<=ext.loc[ext.available.notna(),'cutoff']).all()
    old=old.merge(ext[['date','ewy_move_log_pct','us_move_log_pct']],on='date',validate='many_to_one')
    old['ewy_z']=old.ewy_move_log_pct/(old.ewma/np.sqrt(5));old['us_z']=old.us_move_log_pct/(old.ewma/np.sqrt(5))
    ref=pd.read_parquet('reports/three_model_intervals_20261105/points.parquet');ref=ref[ref.model.eq('catboost')]
    new=new.dropna(subset=F+['target','end_date','ewma','label_known_by']);old=old.dropna(subset=F+['target','end_date','ewma'])
    keys=set(zip(new.date,new.asset));commonold=old[[k in keys for k in zip(old.date,old.asset)]]
    rows=[];audit=[]
    ref=ref.copy();ref['quarter']=ref.date.dt.to_period('Q').astype(str)
    variants=['corrected_quarterly','legacy_common_rows','legacy_long2520','legacy_all_history','legacy_plus_us','legacy_plus_us_ewy','catboost_long2520']
    for quarter,rr in ref.groupby('quarter'):
        cutoff=pd.Period(quarter).start_time
        for name in variants:
            source=new if name=='corrected_quarterly' else commonold if name=='legacy_common_rows' else old
            tr=source[source.end_date<cutoff].copy()
            # For matched legacy-value control use exactly corrected eligible train keys.
            eligible=new[(new.end_date<cutoff)&(pd.to_datetime(new.label_known_by,utc=True)<cutoff.tz_localize('UTC'))]
            if name=='corrected_quarterly':tr=eligible
            if name=='legacy_common_rows':tr=tr.merge(eligible[['date','asset']],on=['date','asset'],validate='one_to_one')
            # Always evaluate corrected state/targets; add exogenous values only in ablations.
            te=rr[['date','asset']].merge(new,on=['date','asset'],validate='one_to_one')
            te=te.merge(old[['date','asset','ewy_z','us_z']],on=['date','asset'],how='left',validate='one_to_one')
            cols=F+(['us_z'] if name=='legacy_plus_us' else ['us_z','ewy_z'] if name=='legacy_plus_us_ewy' else [])
            for a,t in te.groupby('asset'):
                z=tr[tr.asset.eq(a)].dropna(subset=cols).sort_values('date');z=z if name=='legacy_all_history' else z.tail(2520)
                t=t.dropna(subset=cols)
                if len(z)<250 or t.empty:continue
                assert z.end_date.max()<cutoff and cutoff<=t.date.min()
                q=fit_predict(z,t,cols,name=='catboost_long2520')
                for level,lo,hi in [(.8,1,3),(.9,0,4)]:
                    v=t[['date','asset','target']].rename(columns={'target':'actual'}).copy();v['model']=name;v['level']=level;v['center']=q[:,2];v['lo']=q[:,lo];v['hi']=q[:,hi];v['year']=v.date.dt.year;rows.append(v)
                audit.append(dict(quarter=quarter,model=name,asset=a,train_n=len(z),train_start=str(z.date.min()),train_end=str(z.end_date.max()),test_n=len(t),publication_verified=name=='corrected_quarterly'))
        print('complete',quarter,flush=True)
    pred=pd.concat(rows,ignore_index=True);pred.to_parquet(OUT/'predictions.parquet',index=False)
    baseline=pd.read_parquet('reports/three_model_intervals_20261105/intervals.parquet');baseline=baseline[baseline.interval.eq('pooled')].copy();baseline['model']='saved_'+baseline.model
    allp=pd.concat([pred,baseline],ignore_index=True)
    # Restrict every reported variant to exact shared evaluation keys, including missing external dates.
    shared=None
    for _,v in allp.groupby('model'):
        k=set(zip(v.date,v.asset));shared=k if shared is None else shared&k
    allp=allp[[k in shared for k in zip(allp.date,allp.asset)]]
    ms=[]
    for period,z in [('all',allp),('2025_2026',allp[allp.year>=2025])]:
        for (m,l),v in z.groupby(['model','level']):ms.append(dict(period=period,model=m,level=l,**metrics(v)))
    pd.DataFrame(ms).to_csv(OUT/'metrics.csv',index=False)
    pd.DataFrame(audit).to_csv(OUT/'splits.csv',index=False)
    pd.DataFrame([dict(asset=a,model=m,level=l,**metrics(v)) for (a,m,l),v in allp.groupby(['asset','model','level'])]).to_csv(OUT/'per_asset.csv',index=False)
    ext.to_csv(OUT/'external_alignment.csv',index=False)
    assert np.isfinite(pred[['center','lo','hi','actual']]).all().all()
    assert all(hashlib.sha256(Path(k).read_bytes()).hexdigest()==v for k,v in hashes.items())
    (OUT/'protocol.json').write_text(json.dumps(dict(features=F,train='Quarter start; strictly matured targets; maximum2520; no zero fill',gold_contract_changed=False,azure_changed=False,production_promoted=False,legacy_data='Official research Gold history since2000, historical macro publication clocks unverified; research only',external='Existing source EWY/Nasdaq historical data; assumed market clocks, not actual receipt certification; available by KRX close',original_difference='Gold18 inputs retained; own-stock target/scale; quarterly; no future preopen values',shared_test_n=len(shared),excluded_original_keys=len(ref)-len(shared),source_hashes=hashes),indent=2))
    print(pd.DataFrame(ms).query("period=='all'").to_string(index=False))

if __name__=='__main__':
    with threadpool_limits(limits=2):main()
