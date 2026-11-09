"""Common temporal/data/feature improvements across four frozen algorithm configurations."""
import json,hashlib,os
from concurrent.futures import ThreadPoolExecutor,as_completed
import numpy as np
import pandas as pd
from gold_quantile_benchmark import ROOT,FEATURES,SHOCKS,build
from four_models_gold_20261104 import model,score,KINDS
OUT=ROOT/'reports/shared_improvement_20261104';OLD=ROOT/'reports/four_models_gold_20261104'
POLICIES=['quality_only','refresh','recent8','stationary','raw_target','interactions']
def prepare():
    g=pd.read_parquet(ROOT/'exports/seongjin_gold_v1_1/gold_stress_daily.parquet');dates=pd.DatetimeIndex(sorted(pd.to_datetime(g.trading_date).unique()));extra=[]
    for asset,z in g.groupby('asset_id'):
        z=z.copy();z.index=pd.to_datetime(z.trading_date);z=z.reindex(dates)
        extra.append(pd.DataFrame(dict(asset=asset,date=dates,oil_pct_valid=z.wti.gt(0)&z.wti.shift(-5).gt(0),oil_change20=(z.wti.pct_change(20,fill_method=None)*100).where(z.wti.gt(0)&z.wti.shift(20).gt(0)),rate_change20=z.us_treasury_10y.diff(20)*100,kr_us_spread=(z.korea_3y-z.us_treasury_10y)*100)))
    d=build(g);d=d[d.asset!='portfolio'].merge(pd.concat(extra),on=['asset','date'],validate='one_to_one')
    for shock in SHOCKS:
        for state in ['market_trend20','market_vol20','asset_trend20']:d[shock+'__'+state]=d[shock]*d[state]
    assert len(d)==100871 and d.asset.nunique()==20
    OUT.mkdir(exist_ok=True)
    d[~d.oil_pct_valid][['asset','date','end_date','oil_level','shock_oil','target']].to_csv(OUT/'invalid_oil_percentage_training_rows.csv',index=False)
    checks=dict(rows=len(g),stocks=int(g.asset_id.nunique()),duplicate_keys=int(g.duplicated(['dataset_version','trading_date','asset_id']).sum()),quality_counts=g.quality_status.value_counts().to_dict(),mock_rows=int(g.is_mock.sum()),missing_available_at={c:float(g[c].isna().mean()) for c in g if c.endswith('_available_at')},invalid_oil_training_rows=int((~d.oil_pct_valid).sum()),note='Training/calibration rows with nonpositive oil endpoints excluded in new policies. Stationary oil percentage feature also requires positive endpoints. Evaluation keys unchanged; unavailable features fall back to baseline. Missing publication times not guessed.')
    (OUT/'data_audit.json').write_text(json.dumps(checks,indent=2),encoding='utf8')
    return d
def columns(policy):
    cols=list(FEATURES)
    if policy=='stationary':cols=[{'oil_level':'oil_change20','rate_level':'rate_change20','kr3y_level':'kr_us_spread'}.get(c,c) for c in cols]
    if policy=='interactions':cols += [s+'__'+c for s in SHOCKS for c in ['market_trend20','market_vol20','asset_trend20']]
    return cols
def asset_job(asset,f,configs,locked):
    folder=OUT/'checkpoints';path=folder/f'{asset}.parquet'
    rebuild=set(filter(None,os.environ.get('STRESSLAB_REBUILD_POLICIES','').split(',')))
    if path.exists() and not rebuild:return
    preserved=[];saved_audits=[];saved_scenarios=[]
    if path.exists():
        old=pd.read_parquet(path);preserved=[old[~old.policy.isin(rebuild)]]
        olda=pd.read_csv(folder/f'{asset}_audit.csv',dtype={'asset':str});saved_audits=olda[~olda.policy.isin(rebuild)].to_dict('records')
        olds=pd.read_csv(folder/f'{asset}_scenarios.csv',dtype={'asset':str});saved_scenarios=olds[~olds.policy.isin(rebuild)].to_dict('records')
    f=f.sort_values('date');allrows=[];audits=[];scenarios=[]
    base=pd.read_parquet(OLD/'predictions.parquet');base=base[base.asset==asset]
    dev=pd.concat([pd.read_parquet(p) for p in (OLD/'development').glob(f'{asset}_*.parquet')],ignore_index=True) if list((OLD/'development').glob(f'{asset}_*.parquet')) else pd.DataFrame()
    years=[2020,2021,2023,2024,2025,2026]
    for kind in KINDS:
        k=configs[kind]
        for policy in (list(rebuild) if rebuild else POLICIES):
            cols=columns(policy);cache={};recent=policy not in ['refresh','quality_only'];normalize=policy!='raw_target'
            def fit(year):
                if year in cache:return cache[year]
                cutoff=pd.Timestamp(year-1 if policy=='quality_only' else year,1,1)-pd.Timedelta(days=20)
                tr=f[(f.end_date<cutoff)&f.oil_pct_valid].dropna(subset=cols)
                if recent:tr=tr[tr.date>=pd.Timestamp(year,1,1)-pd.DateOffset(years=8)]
                if len(tr)<250:cache[year]=None;return None
                scale=tr.scale if normalize else 1
                m=model(kind,k).fit(tr[cols].to_numpy(),tr.target/scale)
                cache[year]=(m,tr);return cache[year]
            for year in years:
                ref=(base[(base.fold==year)&(base.model==kind)] if year>=2023 else dev[(dev.fold==year)&(dev.model==kind)&(dev.config==k)] if not dev.empty else pd.DataFrame())
                if ref.empty:continue
                te=f[f.date.isin(ref.date)];assert len(te)==len(ref)
                current=fit(year);calrows=[];cal_fit_ends=[]
                for prev in ([year-1] if policy=='quality_only' else [year-2,year-1]):
                    fitted=current if policy=='quality_only' else fit(prev)
                    if fitted is None:continue
                    cm,ct=fitted;cal=f[(f.date>=pd.Timestamp(prev,1,1))&(f.date<pd.Timestamp(prev+1,1,1))&(f.end_date<pd.Timestamp(year,1,1)-pd.Timedelta(days=20))&f.oil_pct_valid].dropna(subset=cols).iloc[::6]
                    if cal.empty:continue
                    assert ct.end_date.max()<cal.date.min()
                    cs=cal.scale.to_numpy() if normalize else np.ones(len(cal))
                    q=cal[['date','end_date']].copy();q['residual']=cal.target.to_numpy()/cs-cm.predict(cal[cols].to_numpy());calrows.append(q);cal_fit_ends.append(str(ct.end_date.max()))
                cal=pd.concat(calrows,ignore_index=True).sort_values('date') if calrows else pd.DataFrame()
                if not cal.empty:
                    keep=[];end=pd.Timestamp.min
                    for idx,row in cal.iterrows():
                        if row.date>end:keep.append(idx);end=row.end_date
                    cal=cal.loc[keep]
                fallback=current is None or len(cal)<30 or te[cols].isna().any().any()
                if fallback:
                    z=ref.copy();z['policy']=policy;z['fallback']=True;allrows.append(z)
                    audits.append(dict(asset=asset,model=kind,policy=policy,fold=year,fallback=True,cal_n=len(cal),reason='insufficient_historical_crossfit_or_features'))
                    continue
                m,tr=current;res=cal.residual.to_numpy();quant=np.quantile(res,[.05,.1,.9]);tail=res[res<=quant[0]];es=float(tail.mean());s=te.scale.to_numpy() if normalize else np.ones(len(te));center=m.predict(te[cols].to_numpy());volcut=tr.market_vol20.quantile(2/3)
                assert cal.end_date.max()<te.date.min() and tr.end_date.max()<te.date.min()
                # Cross-fitted residual windows must not overlap each other within each year.
                assert (cal.end_date.iloc[:-1].to_numpy()<cal.date.iloc[1:].to_numpy()).all()
                z=pd.DataFrame(dict(asset=asset,date=te.date.to_numpy(),fold=year,model=kind,policy=policy,config=k,actual=te.target.to_numpy(),center=center*s,lo=(center+quant[1])*s,hi=(center+quant[2])*s,q05=(center+quant[0])*s,es=(center+es)*s,high_vol=te.market_vol20.to_numpy()>volcut,cal_n=len(cal),es_tail_n=len(tail),fallback=False));allrows.append(z)
                audits.append(dict(asset=asset,model=kind,policy=policy,fold=year,fallback=False,cal_n=len(cal),train_n=len(tr),train_label_end=str(tr.end_date.max()),test_start=str(te.date.min()),cal_label_end=str(cal.end_date.max()),cal_model_label_ends=';'.join(cal_fit_ends),es_tail_n=len(tail),features=len(cols)))
                if year==2026:
                    row=te.iloc[[-1]].copy()
                    for name,fx,rate in [('zero',0,0),('moderate',2.5,50),('large',5,100),('extreme',10,200)]:
                        x=row.copy();x[SHOCKS]=[fx,rate,0,0]
                        for shock in SHOCKS:
                            for state in ['market_trend20','market_vol20','asset_trend20']:x[shock+'__'+state]=x[shock]*x[state]
                        val=float(m.predict(x[cols].to_numpy())[0]*(x.scale.iloc[0] if normalize else 1));scenarios.append(dict(asset=asset,model=kind,policy=policy,state_date=str(x.date.iloc[0].date()),scenario=name,center=val,validated=False))
    pd.concat(preserved+allrows,ignore_index=True).to_parquet(path,index=False);pd.DataFrame(saved_audits+audits).to_csv(folder/f'{asset}_audit.csv',index=False);pd.DataFrame(saved_scenarios+scenarios).to_csv(folder/f'{asset}_scenarios.csv',index=False)
def main():
    OUT.mkdir(exist_ok=True);(OUT/'checkpoints').mkdir(exist_ok=True);d=prepare();configs=json.loads((OLD/'frozen_configs.json').read_text());locked=pd.read_parquet(ROOT/'reports/gold20_locked_20261104/locked_baseline.parquet')
    protocol=dict(policies=POLICIES,features={p:columns(p) for p in POLICIES},configs=configs,baseline='four_models_gold_20261104, original split',selection='For each algorithm choose lowest dev MAE among policies with >=1% MAE improvement, nondecreasing direction, nonworsening crash MAE, nonworsening MAE in both2020/2021. Otherwise baseline. Applied to all20, no per-stock evaluation selection.',risk_guard='Report intervals independently. No production acceptance if coverage, interval score or crash protection deteriorate. No width forcing.',new_split='Fit through label_end < Jan1(year)-20days; residuals from two prior annual out-of-time models on disjoint6-trading-day anchors. Recent8 policies cap training age. Raw-target changes normalization only relative recent8.',blind=False,leakage_limit='All evaluation periods previously researched; Gold actual publication times missing. No guessed timestamps.',operational_changes=False)
    (OUT/'protocol.json').write_text(json.dumps(protocol,indent=2),encoding='utf8')
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures=[pool.submit(asset_job,a,f,configs,locked) for a,f in d.groupby('asset')]
        for i,f in enumerate(as_completed(futures),1):f.result();(OUT/'progress.json').write_text(json.dumps(dict(stage='training',completed=i,total=20)));print('stocks',i,20,flush=True)
    r=pd.concat([pd.read_parquet(p) for p in (OUT/'checkpoints').glob('*.parquet')],ignore_index=True)
    bd=pd.concat([pd.read_parquet(p) for p in (OLD/'development').glob('*.parquet')]);bd=bd[bd.apply(lambda x:x.config==configs[x.model],axis=1)].copy();bd['policy']='baseline';bd['fallback']=False
    be=pd.read_parquet(OLD/'predictions.parquet');be['policy']='baseline';be['fallback']=False;r=pd.concat([r,bd,be],ignore_index=True)
    dev=r[r.fold<2023];dm=pd.DataFrame([dict(model=m,policy=p,**score(z)) for (m,p),z in dev.groupby(['model','policy'])]);dm.to_csv(OUT/'development_metrics.csv',index=False);selected={}
    for kind in KINDS:
        b=dm[(dm.model==kind)&(dm.policy=='baseline')].iloc[0];candidates=[]
        for p in POLICIES:
            s=dm[(dm.model==kind)&(dm.policy==p)].iloc[0]
            yearly=all(score(dev[(dev.model==kind)&(dev.policy==p)&(dev.fold==yr)])['mae']<=score(dev[(dev.model==kind)&(dev.policy=='baseline')&(dev.fold==yr)])['mae'] for yr in [2020,2021])
            if s.mae<=b.mae*.99 and s.direction>=b.direction and s.crash_mae<=b.crash_mae and yearly:candidates.append((s.mae,p))
        selected[kind]=min(candidates)[1] if candidates else 'baseline'
    (OUT/'development_selection.json').write_text(json.dumps(selected,indent=2))
    ev=r[r.fold>=2023].copy()
    for (kind,p),z in ev.groupby(['model','policy']):
        assert len(z)==2928 and z.asset.nunique()==20
        a=z.merge(locked[['asset','date','actual']],on=['asset','date'],validate='one_to_one',suffixes=('','_old'));assert len(a)==2928 and np.array_equal(a.actual,a.actual_old)
    ev.to_parquet(OUT/'predictions.parquet',index=False);dev.to_parquet(OUT/'development_predictions.parquet',index=False)
    pd.DataFrame([dict(model=m,policy=p,**score(z)) for (m,p),z in ev.groupby(['model','policy'])]).to_csv(OUT/'metrics.csv',index=False)
    pd.DataFrame([dict(asset=a,model=m,policy=p,**score(z)) for (a,m,p),z in ev.groupby(['asset','model','policy'])]).to_csv(OUT/'per_stock.csv',index=False)
    pd.DataFrame([dict(fold=y,model=m,policy=p,**score(z)) for (y,m,p),z in ev.groupby(['fold','model','policy'])]).to_csv(OUT/'per_year.csv',index=False)
    pd.concat([pd.read_csv(p,dtype={'asset':str}) for p in (OUT/'checkpoints').glob('*_audit.csv')]).to_csv(OUT/'fit_audit.csv',index=False)
    pd.concat([pd.read_csv(p,dtype={'asset':str}) for p in (OUT/'checkpoints').glob('*_scenarios.csv')]).to_csv(OUT/'scenario_sensitivity.csv',index=False)
    (OUT/'progress.json').write_text(json.dumps(dict(stage='complete',selected=selected)))
    print(pd.read_csv(OUT/'metrics.csv').to_string(index=False))
if __name__=='__main__':main()
