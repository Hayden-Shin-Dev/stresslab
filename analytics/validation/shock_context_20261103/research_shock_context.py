"""Shock-context and temporal stability study. Fixed cohort, frozen validation choice."""
import json,hashlib
from concurrent.futures import ThreadPoolExecutor,as_completed
import numpy as np
import pandas as pd
from asset_feature_research import ROOT,EXPANDED,SHOCKS,model
from report_long_universe import metric
SRC=ROOT/'reports/long_universe_20261103'
OUT=ROOT/'reports/shock_context_20261103'
STATE_EXTRA=['beta60','corr60','downside_vol20','oil_trend20','vix_change20','rate_change20','asset_vol_ratio','market_vol_ratio','asset_acceleration','market_acceleration']
CONTEXT=['market_trend20','market_vol20','vix_level','beta60','asset_trend20','relative_market20']
INTER=[s+'__'+c for s in SHOCKS for c in CONTEXT]
COLS=EXPANDED+STATE_EXTRA+INTER
SPECS=['baseline','context','recent5','ridge_context']

def interactions(f):
    f=f.copy()
    for s in SHOCKS:
        for c in CONTEXT:f[s+'__'+c]=f[s]*f[c]
    return f

def fit_predict(kind,tr,te,cut):
    train=tr[tr.date>=cut-pd.DateOffset(years=5)] if kind=='recent5' else tr
    cols=EXPANDED if kind=='baseline' else COLS
    m=model('ridge' if kind=='ridge_context' else 'lgb').fit(train[cols],train.target)
    return m,m.predict(te[cols]),cols

def main():
    OUT.mkdir(exist_ok=True);(OUT/'checkpoints').mkdir(exist_ok=True)
    gold=ROOT/'exports/seongjin_gold_v1_1/gold_stress_daily.parquet';digest=hashlib.sha256(gold.read_bytes()).hexdigest()
    protocol=dict(cohort='Previous101 fixed, no test-score stock filtering',selection='Train labels before2021-12-12, validation2022 disjoint5day rows. Candidate must match or improve baseline MAE,direction and crash MAE. Choose lowest validation MAE among qualifying; otherwise baseline. Freeze before2023 evaluation.',evaluation='Same prior cleaned evaluation asset/date pairs, restricted to finite extra past-only features; quarterly train label end<quarter start minus20days.2023-2026 reused research period, not independent blind',specs=SPECS,state_features=STATE_EXTRA,interactions=INTER,parameters='Existing LightGBM250depth4; Ridgealpha30; no hyperparameter search',importance='2022 validation permutation of each shock with derived interactions recomputed; predictive reliance, not causal effect',approved=False,gold_sha256=digest)
    (OUT/'protocol.json').write_text(json.dumps(protocol,indent=2),encoding='utf8')
    assets=json.loads((SRC/'selected_assets.json').read_text());g=pd.read_parquet(SRC/'research_daily_input.parquet').sort_values(['asset_id','trading_date']);d=pd.read_parquet(SRC/'learning_table.parquet');parts=[]
    for a,z in g.groupby('asset_id'):
        z=z.copy();p=z.close;r=p.pct_change(fill_method=None)*100;mr=z.kospi_close.pct_change(fill_method=None)*100
        ok=z.quality_status.eq('valid')&p.gt(0)&z.is_mock.eq(False)
        x=pd.DataFrame(dict(asset=a,date=z.trading_date,clean=ok.rolling(61).sum().eq(61)))
        x['beta60']=r.rolling(60).cov(mr)/mr.rolling(60).var();x['corr60']=r.rolling(60).corr(mr)
        x['downside_vol20']=np.sqrt(r.clip(upper=0).pow(2).rolling(20).mean())
        x['oil_trend20']=(z.wti.pct_change(20,fill_method=None)*100).where(z.wti.gt(0)&z.wti.shift(20).gt(0));x['vix_change20']=z.vix-z.vix.shift(20);x['rate_change20']=(z.us_treasury_10y-z.us_treasury_10y.shift(20))*100
        parts.append(x)
    d=d.merge(pd.concat(parts),on=['asset','date'],validate='one_to_one')
    d['asset_vol_ratio']=d.asset_vol5/d.asset_vol60.clip(lower=.1);d['market_vol_ratio']=d.market_vol5/d.market_vol60.clip(lower=.1)
    d['asset_acceleration']=d.asset_trend5-d.asset_trend20/4;d['market_acceleration']=d.market_trend5-d.market_trend20/4
    d=interactions(d).replace([np.inf,-np.inf],np.nan).dropna(subset=COLS);d=d[d.clean & d.asset.isin(assets)]
    oil=g.groupby('trading_date').wti.first().sort_index();bad=set(oil.index[oil.le(0).rolling(6).max().shift(-5).eq(1)])
    d=d[~d.date.isin(bad)];d.to_parquet(OUT/'learning_table.parquet',index=False)
    reference=pd.read_parquet(ROOT/'reports/center_audit_20261103/predictions.parquet');reference=reference[reference.method.eq('clean_raw')]
    allrows=[];choices=[];importance=[];folds=[];failed=[]

    def run(a):
        f=d[d.asset.eq(a)].sort_values('date');tr=f[f.end_date<pd.Timestamp('2021-12-12')];va=f[(f.date>=pd.Timestamp('2022-01-01'))&(f.end_date<pd.Timestamp('2023-01-01'))].iloc[::6]
        scores={};valimportance=[]
        assert len(tr)>500 and len(va)>=20 and tr.end_date.max()<va.date.min()
        for kind in SPECS:
            m,p,cols=fit_predict(kind,tr,va,pd.Timestamp('2022-01-01'));scores[kind]=metric(pd.DataFrame(dict(actual=va.target.to_numpy(),center=p)))
            scores[kind]['crash_mae']=float(np.abs(va.target.to_numpy()[va.target<=-5]-p[va.target<=-5]).mean()) if va.target.le(-5).any() else np.nan
            if kind=='context':
                rng=np.random.default_rng(20261103)
                for shock in SHOCKS:
                    changes=[]
                    for repeat in range(10):
                        alt=va.copy();alt[shock]=rng.permutation(alt[shock].to_numpy());alt=interactions(alt);pred=m.predict(alt[cols]);changes.append(float(np.abs(va.target-pred).mean()-scores[kind]['mae']))
                    valimportance.append(dict(asset=a,shock=shock,validation_n=len(va),mae_increase_mean=np.mean(changes),mae_increase_std=np.std(changes)))
        b=scores['baseline'];eligible=[k for k,s in scores.items() if s['mae']<=b['mae'] and s['direction_accuracy']>=b['direction_accuracy'] and (np.isnan(b['crash_mae']) or s['crash_mae']<=b['crash_mae'])]
        choice=min(eligible,key=lambda k:(scores[k]['mae'],k))
        choice_rows=[dict(asset=a,method=k,chosen=k==choice,**s) for k,s in scores.items()]
        base=reference[reference.asset.eq(a)].sort_values('date');base=base[base.date.isin(f.date)];rows=[];audit=[]
        for quarter,z in base.groupby(base.date.dt.to_period('Q')):
            cut=quarter.start_time;train=f[f.end_date<cut-pd.Timedelta(days=20)];te=f.set_index('date').loc[z.date].reset_index()
            assert train.end_date.max()<te.date.min() and np.allclose(te.target,z.actual)
            for kind in SPECS:
                m,p,cols=fit_predict(kind,train,te,cut);o=z.copy();o['method']=kind;o['center']=p;rows.append(o)
                if kind==choice:
                    q=o.copy();q['method']='validation_selected';rows.append(q)
            audit.append(dict(asset=a,quarter=str(quarter),train_end=str(train.end_date.max()),test_start=str(te.date.min()),n=len(train),selected_method=choice))
        result=pd.concat(rows,ignore_index=True);result.to_parquet(OUT/'checkpoints'/f'{a}.parquet',index=False)
        return result,choice_rows,valimportance,audit

    with ThreadPoolExecutor(max_workers=3) as pool:
        futures={pool.submit(run,a):a for a in assets}
        for i,fu in enumerate(as_completed(futures),1):
            try:
                r,c,v,t=fu.result();allrows.append(r);choices.extend(c);importance.extend(v);folds.extend(t)
            except Exception as e:failed.append(dict(asset=futures[fu],error=repr(e)))
            (OUT/'progress.json').write_text(json.dumps(dict(completed=i,total=len(assets),failed=failed,status='running'),indent=2));print(i,len(assets),flush=True)
    assert not failed,failed
    r=pd.concat(allrows,ignore_index=True);assert r.groupby(['asset','date']).size().eq(5).all();r.to_parquet(OUT/'predictions.parquet',index=False)
    pd.DataFrame(choices).to_csv(OUT/'validation_choices.csv',index=False);pd.DataFrame(importance).to_csv(OUT/'shock_importance.csv',index=False);pd.DataFrame(folds).to_csv(OUT/'time_audit.csv',index=False)
    rows=[];pairs=pd.read_csv(SRC/'eligible_pairs.csv',dtype={'asset':str});event=pd.Series(False,index=r.index)
    for _,p in pairs.iterrows():event|=r.asset.eq(p.asset)&r[p.shock+'_event']
    for scope,mask in [('all',pd.Series(True,index=r.index)),('selected_shock_events',event),('crash',r.actual<=-5),('rally',r.actual>=5)]:
        for kind,z in r[mask].groupby('method'):rows.append(dict(scope=scope,method=kind,**metric(z)))
    pd.DataFrame(rows).to_csv(OUT/'metrics.csv',index=False)
    pd.DataFrame([dict(asset=a,method=k,**metric(z)) for (a,k),z in r.groupby(['asset','method'])]).to_csv(OUT/'asset_metrics.csv',index=False)
    assert hashlib.sha256(gold.read_bytes()).hexdigest()==digest
    (OUT/'progress.json').write_text(json.dumps(dict(status='complete',completed=len(assets),failed=[],gold_unchanged=True),indent=2))

if __name__=='__main__':main()
