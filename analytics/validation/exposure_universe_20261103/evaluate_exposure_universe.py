"""Official six-sector extension, fixed per-asset factor ablations; no deployment."""
import json,hashlib,os,subprocess,sys,joblib
import numpy as np
import pandas as pd
from asset_feature_research import ROOT,make_data,FEATURES,EXPANDED,SHOCKS,model,record
from adaptive_residual_benchmark import weighted_q
SRC=ROOT/'data/research/exposure_universe_20261103'
OUT=ROOT/'reports/exposure_universe_20261103'

def prepare():
    from select_exposure_universe import assemble
    selected=json.loads((OUT/'selected_assets.json').read_text(encoding='utf8'))
    assert selected, 'No candidates passed the frozen screen'
    status=json.loads((SRC/'selected_progress.json').read_text(encoding='utf8'))
    assert status['status']=='complete', 'Selected history not complete'
    original=pd.read_parquet(ROOT/'reports/sector6_factors_20261103/research_daily_input.parquet')
    assets=sorted(set(original.asset_id)|set(selected))
    g,quality=assemble(assets)
    g.to_parquet(OUT/'research_daily_input.parquet',index=False)
    quality.to_csv(OUT/'full_source_quality.csv',index=False)
    d,_=make_data(g)
    old=pd.read_parquet(ROOT/'reports/sector6_factors_20261103/learning_table.parquet')
    c=d[d.asset.isin(original.asset_id)].merge(old,on=['asset','date'],suffixes=('_a','_b'),validate='one_to_one')
    assert len(c)==len(old)
    for col in EXPANDED+['target','scale']:assert abs(c[col+'_a']-c[col+'_b']).max()<1e-8
    d.to_parquet(OUT/'learning_table.parquet',index=False)
    return d,g,set(selected)

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    shard=os.environ.get('SECTOR_RESEARCH_ASSETS')
    if shard:
        d=pd.read_parquet(OUT/'learning_table.parquet');g=pd.read_parquet(OUT/'research_daily_input.parquet');newassets=set(json.loads((OUT/'selected_assets.json').read_text(encoding='utf8')))
    else:d,g,newassets=prepare()
    price=g.groupby('trading_date').kospi_close.first().sort_index();cr=(price.shift(-5)/price-1)*100;cr.index=pd.to_datetime(cr.index)
    protocol={'new_assets':sorted(newassets),'original_gold_sha256':hashlib.sha256((ROOT/'exports/seongjin_gold_v1_1/gold_stress_daily.parquet').read_bytes()).hexdigest(),'source':'KRX direct authenticated website only; no Naver; adjusted reference20261030; existing ECOS/FRED identical','scope':'training-selected stocks plus original26 controls; no production Gold write',
      'models':'existing Ridge alpha30 and LightGBM250trees quantile0.5 depth4; no tuning','factor_paths':'state_only and all4, selection frozen before evaluation','split':'same annual vintages2018-2026, evaluate2023-2026, previous-year calibration,20day label embargo,6row nonoverlap;5year vintage OOS residual bands',
      'evaluation':'actual future5day shocks entered retrospectively; not causal identification or independent blind test','oil':'preserve previous definition for matched baseline; nonpositive WTI limitation retained','availability':'historical available_at absent; point-in-time publication not certified','approved':False,'azure_changes':False,'contract_changes':False}
    if not shard:(OUT/'protocol.json').write_text(json.dumps(protocol,ensure_ascii=False,indent=2),encoding='utf8')
    if not shard:
        # Separate per-security jobs, deterministic settings and distinct checkpoints.
        pending=[a for a in sorted(d.asset.unique()) if not (OUT/'checkpoints'/f'{a}.parquet').exists()]
        jobs=[]
        for i in range(4):
            batch=pending[i::4]
            if not batch:continue
            env=os.environ.copy();env['SECTOR_RESEARCH_ASSETS']=','.join(batch)
            log=open(OUT/f'worker_{i}.log','w',encoding='utf8')
            jobs.append((subprocess.Popen([sys.executable,__file__],env=env,stdout=log,stderr=log),log))
        for proc,log in jobs:
            code=proc.wait();log.close()
            if code:raise RuntimeError('local_factor_worker_failed')
    rows=[];folds=[]
    for asset,f in d.groupby('asset'):
        if shard and asset not in shard.split(','):continue
        checkpoint=OUT/'checkpoints'/f'{asset}.parquet';checkpoint.parent.mkdir(exist_ok=True)
        if checkpoint.exists():rows.extend(pd.read_parquet(checkpoint).to_dict('records'));print('cached',asset,flush=True);continue
        f=f.sort_values('date');banks={};ar=[];responses=[]
        for year in range(2018,2027):
            cut=pd.Timestamp(year,1,1);cc=pd.Timestamp(year-1,1,1);tr=f[f.end_date<cc-pd.Timedelta(days=20)];ca=f[(f.date>=cc)&(f.end_date<cut-pd.Timedelta(days=20))].iloc[::6];te=f[(f.date>=cut)&(f.date<pd.Timestamp(year+1,1,1))].iloc[::6];te=te[te.end_date<pd.Timestamp(year+1,1,1)]
            if len(tr)<250 or len(ca)<30:continue
            high=tr.market_vol20.quantile(2/3)
            for kind in ['ridge','lgb']:
                full=FEATURES if kind=='ridge' else EXPANDED;state=[c for c in full if c not in SHOCKS]
                specs={'state_only':state,'all4':full}
                for spec,features in specs.items():
                    key=(kind,spec);m=model(kind).fit(tr[features],tr.target/tr.scale);cp=m.predict(ca[features])*ca.scale.to_numpy();p=ca[['date','end_date']].copy();p['residual']=(ca.target.to_numpy()-cp)/ca.scale.to_numpy();p['ready']=p.end_date+pd.Timedelta(days=20);banks.setdefault(key,[]).append(p)
                    if year<2023 or not len(te):continue
                    if year==2026:
                        path=OUT/'models'/asset;path.mkdir(parents=True,exist_ok=True)
                        joblib.dump({'model':m,'features':features,'train_end':str(tr.end_date.max()),'scale_definition':'same frozen 20/60 day scale','approved':False},path/f'{kind}_{spec}.joblib')
                    if spec=='all4':
                        for shock in SHOCKS:
                            low,high_support=tr[shock].quantile([.05,.95]);step=float((high_support-low)/10)
                            z=te[(te[shock]>=low)&(te[shock]+step<=high_support)][features].copy()
                            if len(z) and step>0:
                                before=m.predict(z);z[shock]+=step;change=(m.predict(z)-before)*te.loc[z.index,'scale'].to_numpy()
                                responses.append(dict(asset=asset,model=kind,year=year,shock=shock,step=step,n=len(z),median_change_pp=float(np.median(change)),positive_fraction=float((change>1e-8).mean()),negative_fraction=float((change < -1e-8).mean()),support_low=low,support_high=high_support))
                    pool=pd.concat(banks[key],ignore_index=True).sort_values('date');pool=pool[(pool.date>=cut-pd.DateOffset(years=5))&(pool.ready<cut)];assert tr.end_date.max()<ca.date.min() and pool.ready.max()<te.date.min()
                    for z in [pool,te]:assert (z.end_date.to_numpy()[:-1]<z.date.to_numpy()[1:]).all()
                    w=np.ones(len(pool))/len(pool);adj=weighted_q(pool.residual,w);pred=m.predict(te[features])*te.scale.to_numpy()
                    for i,(_,t) in enumerate(te.iterrows()):
                        r=record(t,pred[i],pred[i]+adj*t.scale,kind+'_'+spec,high,cr.get(t.date,np.nan),pool,w);r.update(model=kind,spec=spec,year=year,new_asset=asset in newassets);ar.append(r)
            print(asset,year,flush=True)
        pd.DataFrame(responses).to_csv(OUT/'checkpoints'/f'{asset}_responses.csv',index=False)
        pd.DataFrame(ar).to_parquet(checkpoint,index=False);rows.extend(ar)
    if shard:return
    r=pd.DataFrame(rows);r.to_parquet(OUT/'predictions.parquet',index=False)
    old=pd.read_parquet(ROOT/'reports/sector6_factors_20261103/predictions.parquet')
    old=old[old.spec.isin(['state_only','all4'])]
    check=r.merge(old,on=['asset','date','model','spec'],suffixes=('_a','_b'),validate='one_to_one')
    assert len(check)==len(old)
    for col in ['center','q10','q90']:assert abs(check[col+'_a']-check[col+'_b']).max()<1e-8
    (OUT/'verification.json').write_text(json.dumps({'original26_inputs_and_predictions_reproduced':True,'selected_stocks':len(newassets),'production_approved':False},indent=2))

if __name__=='__main__':main()
