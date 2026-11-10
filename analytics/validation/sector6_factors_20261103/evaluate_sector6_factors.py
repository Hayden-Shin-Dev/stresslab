"""Official six-sector extension, fixed per-asset factor ablations; no deployment."""
import json,hashlib,os,subprocess,sys
import numpy as np
import pandas as pd
from asset_feature_research import ROOT,make_data,FEATURES,EXPANDED,SHOCKS,model,record
from adaptive_residual_benchmark import weighted_q
SRC=ROOT/'data/research/sector6_20261103'
OUT=ROOT/'reports/sector6_factors_20261103'

def numeric(s):return pd.to_numeric(s.astype(str).str.replace(',',''),errors='coerce')

def prepare():
    state=json.loads((SRC/'progress.json').read_text(encoding='utf8'));assert state['status']=='complete'
    assert all(x=='krx.co.kr' or x.endswith('.krx.co.kr') for x in state['network_hosts'])
    gp=ROOT/'exports/seongjin_gold_v1_1/gold_stress_daily.parquet';g=pd.read_parquet(gp);g['trading_date']=pd.to_datetime(g.trading_date);template=g[g.asset_id=='005930'].sort_values('trading_date').copy();extras=[];qa=[];manifest=[];badrows=[]
    for a in json.loads((SRC/'universe.json').read_text(encoding='utf8'))['assets']:
        rows=[]
        for p in sorted((SRC/'stocks'/a['asset_id']).glob('*.json')):
            rows.extend(json.loads(p.read_text(encoding='utf8')));manifest.append(dict(source='KRX',asset=a['asset_id'],file=str(p.relative_to(ROOT)),sha256=hashlib.sha256(p.read_bytes()).hexdigest()))
        z=pd.DataFrame(rows);assert len(z)>0;z['trading_date']=pd.to_datetime(z.TRD_DD);assert not z.trading_date.duplicated().any();z=z.sort_values('trading_date')
        z['close']=numeric(z.TDD_CLSPRC);z['volume']=numeric(z.ACC_TRDVOL);z['reported']=numeric(z.FLUC_RT)
        change=z.close.pct_change(fill_method=None)*100;tol=.011+200/z.close.shift(1);bad=change.notna()&((change-z.reported).abs()>tol)
        for _,row in z[bad].iterrows():badrows.append(dict(asset=a['asset_id'],date=str(row.trading_date),close=row.close,reported=row.reported,reason='adjusted_close_vs_reported_return_requires_review'))
        z['bad']=bad
        x=template.drop(columns=['close','volume']).copy();x['trading_date']=pd.to_datetime(x.trading_date);x=x.merge(z[['trading_date','close','volume','bad']],on='trading_date',how='left',validate='one_to_one')
        x['asset_id']=a['asset_id'];x['sector_id']=None;x['price_basis']='adjusted';x['adjustment_version']='KRX_reference_20261030';x['source_ref']='KRX_official_sector6_20261103';x['dataset_version']='research_sector6_20261103';x['is_mock']=False
        x['quality_status']=np.where(x.close.isna(),'missing',np.where(x.bad.eq(True)|x.volume.le(0)|x.close.le(0),'quarantined','valid'));x=x.drop(columns='bad');x=x[g.columns]
        extras.append(x);qa.append(dict(asset=a['asset_id'],name=a['name'],raw_rows=len(z),first=str(z.trading_date.min()),last=str(z.trading_date.max()),zero_volume=int(z.volume.eq(0).sum()),return_disagreement=int(bad.sum()),research_valid=int(x.quality_status.eq('valid').sum()),historical_corporate_actions_certified=False))
    extended=pd.concat([g]+extras,ignore_index=True);extended.to_parquet(OUT/'research_daily_input.parquet',index=False);pd.DataFrame(qa).to_csv(OUT/'collection_quality.csv',index=False);pd.DataFrame(badrows,columns=['asset','date','close','reported','reason']).to_csv(OUT/'price_flags.csv',index=False)
    (OUT/'source_manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf8')
    d,_=make_data(extended);old=pd.read_parquet(ROOT/'reports/model_redesign_20261103/learning_table.parquet');check=d[d.asset.isin(g.asset_id.unique())].merge(old,on=['asset','date'],suffixes=('_new','_old'),validate='one_to_one');assert len(check)==len(old)
    for c in EXPANDED+['target','scale']:assert np.max(abs(check[c+'_new']-check[c+'_old']))<1e-8
    d.to_parquet(OUT/'learning_table.parquet',index=False)
    return d,g,set(a['asset_id'] for a in json.loads((SRC/'universe.json').read_text(encoding='utf8'))['assets'])

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    shard=os.environ.get('SECTOR_RESEARCH_ASSETS')
    if shard:
        d=pd.read_parquet(OUT/'learning_table.parquet');g=pd.read_parquet(OUT/'research_daily_input.parquet');newassets=set(x['asset_id'] for x in json.loads((SRC/'universe.json').read_text(encoding='utf8'))['assets'])
    else:d,g,newassets=prepare()
    price=g.groupby('trading_date').kospi_close.first().sort_index();cr=(price.shift(-5)/price-1)*100;cr.index=pd.to_datetime(cr.index)
    protocol={'new_assets':sorted(newassets),'original_gold_sha256':hashlib.sha256((ROOT/'exports/seongjin_gold_v1_1/gold_stress_daily.parquet').read_bytes()).hexdigest(),'source':'KRX direct authenticated website only; no Naver; adjusted reference20261030; existing ECOS/FRED identical','scope':'26 security research input; original20 preserved and evaluated separately; no production Gold write',
      'models':'existing Ridge alpha30 and LightGBM250trees quantile0.5 depth4; no tuning','factor_paths':'state_only, all4, each single added to state, each removed from all4','split':'same annual vintages2018-2026, evaluate2023-2026, previous-year calibration,20day label embargo,6row nonoverlap;5year vintage OOS residual bands',
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
        f=f.sort_values('date');banks={};ar=[]
        for year in range(2018,2027):
            cut=pd.Timestamp(year,1,1);cc=pd.Timestamp(year-1,1,1);tr=f[f.end_date<cc-pd.Timedelta(days=20)];ca=f[(f.date>=cc)&(f.end_date<cut-pd.Timedelta(days=20))].iloc[::6];te=f[(f.date>=cut)&(f.date<pd.Timestamp(year+1,1,1))].iloc[::6];te=te[te.end_date<pd.Timestamp(year+1,1,1)]
            if len(tr)<250 or len(ca)<30:continue
            high=tr.market_vol20.quantile(2/3)
            for kind in ['ridge','lgb']:
                full=FEATURES if kind=='ridge' else EXPANDED;state=[c for c in full if c not in SHOCKS]
                specs={'state_only':state,'all4':full};specs.update({'only_'+s:state+[s] for s in SHOCKS});specs.update({'without_'+s:[c for c in full if c!=s] for s in SHOCKS})
                for spec,features in specs.items():
                    key=(kind,spec);m=model(kind).fit(tr[features],tr.target/tr.scale);cp=m.predict(ca[features])*ca.scale.to_numpy();p=ca[['date','end_date']].copy();p['residual']=(ca.target.to_numpy()-cp)/ca.scale.to_numpy();p['ready']=p.end_date+pd.Timedelta(days=20);banks.setdefault(key,[]).append(p)
                    if year<2023 or not len(te):continue
                    pool=pd.concat(banks[key],ignore_index=True).sort_values('date');pool=pool[(pool.date>=cut-pd.DateOffset(years=5))&(pool.ready<cut)];assert tr.end_date.max()<ca.date.min() and pool.ready.max()<te.date.min()
                    for z in [pool,te]:assert (z.end_date.to_numpy()[:-1]<z.date.to_numpy()[1:]).all()
                    w=np.ones(len(pool))/len(pool);adj=weighted_q(pool.residual,w);pred=m.predict(te[features])*te.scale.to_numpy()
                    for i,(_,t) in enumerate(te.iterrows()):
                        r=record(t,pred[i],pred[i]+adj*t.scale,kind+'_'+spec,high,cr.get(t.date,np.nan),pool,w);r.update(model=kind,spec=spec,year=year,new_asset=asset in newassets);ar.append(r)
            print(asset,year,flush=True)
        pd.DataFrame(ar).to_parquet(checkpoint,index=False);rows.extend(ar)
    if shard:return
    r=pd.DataFrame(rows);r.to_parquet(OUT/'predictions.parquet',index=False)
    old=pd.read_parquet(ROOT/'reports/asset_feature_research_20261103/predictions.parquet')
    for kind,method in [('ridge','ridge_old_residual'),('lgb','lgb_expanded_residual')]:
        a=r[(~r.new_asset)&(r.model==kind)&(r.spec=='all4')];b=old[old.method==method];c=a.merge(b,on=['asset','date'],suffixes=('_a','_b'),validate='one_to_one');assert len(c)==len(a)==len(b)
        for col in ['center','q10','q90']:assert abs(c[col+'_a']-c[col+'_b']).max()<1e-8
    previous=pd.read_csv(ROOT/'reports/asset_feature_research_20261103/center_ablations.csv',dtype={'asset':str},parse_dates=['date']);previous=previous[previous.method=='lgb_no_shock']
    state=r[(~r.new_asset)&(r.model=='lgb')&(r.spec=='state_only')];check=state.merge(previous,on=['asset','date'],suffixes=('_new','_old'),validate='one_to_one');assert len(check)==len(previous)==len(state) and abs(check.center_new-check.center_old).max()<1e-8
    (OUT/'verification.json').write_text(json.dumps({'old20_input_unchanged':True,'old20_all4_predictions_exactly_reproduced':True,'old20_state_model_exactly_reproduced':True,'new_assets':len(newassets),'source_allowlist_passed':True,'production_approved':False},indent=2))

if __name__=='__main__':main()
