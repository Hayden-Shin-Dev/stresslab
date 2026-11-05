"""Frozen-key audit: center construction, scale quality, and forward residuals."""
import json
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits
from .gold_quarterly_trial import prep, F
from .preopen_method_trial import LEVELS, metrics
from .core import SHOCKS

OUT=Path('reports/training_interval_audit_20261105')

def fit(z, t, scale_aware=False):
    # Same regularizer, target, history and inputs. Candidate only changes units
    # of shock predictors to match a volatility-normalized response.
    y=100*np.log1p(z.target.to_numpy()/100)/z.ewma.to_numpy()
    x=z[F].copy(); xt=t[F].copy()
    if scale_aware:
        x[SHOCKS]=x[SHOCKS].div(z.ewma,axis=0)
        xt[SHOCKS]=xt[SHOCKS].div(t.ewma,axis=0)
    s=StandardScaler().fit(x)
    m=Ridge(alpha=100).fit(s.transform(x),y)
    return m.predict(s.transform(xt)), y

def emit(t, loc, base, name):
    q=100*np.expm1((loc[:,None]+np.asarray(base)[None,:])*t.ewma.to_numpy()[:,None]/100)
    out=[]
    for level,i,j in [(.8,1,3),(.9,0,4)]:
        v=t[['date','asset','target']].rename(columns={'target':'actual'}).copy()
        v['model']=name;v['level']=level;v['lo']=q[:,i];v['center']=q[:,2];v['hi']=q[:,j]
        v['location']=100*np.expm1(loc*t.ewma.to_numpy()/100)
        out.append(v)
    return out

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    g=pd.read_parquet('reports/service_scope_20261105/corrected_daily_input.parquet')
    x=prep(g)
    known=pd.read_parquet('reports/service_scope_20261105/corrected_features.parquet')[['date','asset','label_known_by']]
    x=x.merge(known,on=['date','asset'],validate='one_to_one').dropna(subset=F+['target','ewma','end_date','label_known_by'])
    x['known']=pd.to_datetime(x.label_known_by,utc=True)
    dates=pd.DatetimeIndex(sorted(pd.to_datetime(g.trading_date).unique()))
    safe=[]
    for a,z in g.groupby('asset_id'):
        z=z.set_index(pd.to_datetime(z.trading_date)).reindex(dates)
        valid=z.quality_status.eq('valid')&z.close.gt(0)&z.volume.gt(0)
        r=np.log(z.close.where(valid)).diff()*100
        safe.append(pd.DataFrame(dict(date=dates,asset=a,safe_ewma=np.sqrt(r.pow(2).ewm(alpha=.06,adjust=False).mean()).clip(lower=.05)*np.sqrt(5))))
    x=x.merge(pd.concat(safe),on=['date','asset'],validate='one_to_one')
    ref=pd.read_parquet('reports/gold_quarterly_trial_20261105/predictions.parquet')
    rr=ref[ref.model.eq('corrected_quarterly')&ref.level.eq(.9)][['date','asset']]
    assets=sorted(rr.asset.unique()); minq=rr.date.min().to_period('Q')-4; maxq=rr.date.max().to_period('Q')
    results=[]; cache={}; splits=[]; diagnostics=[]
    for quarter in pd.period_range(minq,maxq,freq='Q'):
        cutoff=quarter.start_time; finish=(quarter+1).start_time
        tr=x[(x.end_date<cutoff)&(x.known<cutoff.tz_localize('UTC'))]
        te=x[(x.date>=cutoff)&(x.date<finish)&x.asset.isin(assets)]
        for a,tall in te.groupby('asset'):
            z=tr[tr.asset.eq(a)].sort_values('date').tail(2520)
            if len(z)<250:continue
            assert z.end_date.max()<cutoff and z.known.max()<cutoff.tz_localize('UTC')
            for mode in ['original','safe_scale','scale_aware']:
                zz=z.copy(); tt=tall.copy()
                if mode!='original':
                    zz['ewma']=zz.safe_ewma;tt['ewma']=tt.safe_ewma
                loc,y=fit(zz,tt,mode=='scale_aware')
                prev=cache.get((a,mode),[])
                cal=pd.concat(prev,ignore_index=True) if prev else pd.DataFrame()
                if len(cal):cal=cal[(cal.date>=cutoff-pd.DateOffset(years=1))&(cal.end_date<cutoff)&(cal.known<cutoff.tz_localize('UTC'))]
                t=rr.merge(tt,on=['date','asset'],validate='one_to_one')
                if len(t):
                    idx=pd.Index(tt.date).get_indexer(t.date); l=loc[idx]
                    base=np.quantile(np.quantile(y,LEVELS)-y.mean(),[.05,.1,.5,.9,.95])
                    results+=emit(t,l,base,mode+'_return_distribution')
                    # Isolate the fitted location from the unconditional median offset.
                    results+=emit(t,l,base-base[2],mode+'_location_only')
                    if len(cal)>=60:
                        b=np.quantile(cal.residual,[.05,.1,.5,.9,.95])
                        results+=emit(t,l,b,mode+'_forward_residual')
                    splits.append(dict(quarter=str(quarter),asset=a,mode=mode,train_n=len(z),cal_n=len(cal),cal_dates=int(cal.date.nunique()) if len(cal) else 0,train_label_end=str(z.end_date.max()),test_start=str(t.date.min())))
                    for i,row in t.iterrows():
                        diagnostics.append(dict(date=row.date,asset=a,mode=mode,actual=row.target,location=100*np.expm1(l[i]*row.ewma/100),scale=row.ewma,market_trend20=row.market_trend20,market_vol20=row.market_vol20,**{s:row[s] for s in SHOCKS}))
                c=tt[['date','end_date','known']].copy()
                c['residual']=100*np.log1p(tt.target.to_numpy()/100)/tt.ewma.to_numpy()-loc
                cache.setdefault((a,mode),[]).append(c)
        print('audited',quarter,flush=True)
    p=pd.concat(results,ignore_index=True)
    # Reproduce the previous recipe before interpreting any proposed correction.
    check=p[p.model.eq('original_return_distribution')].merge(ref[ref.model.eq('corrected_quarterly')],on=['date','asset','level'],suffixes=('_new','_old'),validate='one_to_one')
    reproduction={c:float(abs(check[c+'_new']-check[c+'_old']).max()) for c in ['center','lo','hi']}
    assert max(reproduction.values())<.01, reproduction
    # The legacy CatBoost median shift is reconstructed analytically, no refitting.
    old=prep(pd.read_parquet('reports/support_expansion_20261104/research_input.parquet')).dropna(subset=F+['target','end_date','ewma'])
    cat=ref[ref.model.eq('catboost_long2520')].copy();cat['quarter']=cat.date.dt.to_period('Q')
    corrected=[]
    for (quarter,a),t in cat.groupby(['quarter','asset']):
        z=old[(old.asset==a)&(old.end_date<quarter.start_time)].sort_values('date').tail(2520)
        y=100*np.log1p(z.target.to_numpy()/100)/z.ewma.to_numpy()
        offset=float(np.quantile(np.quantile(y,LEVELS),.5)-y.mean())
        t=t.merge(x[['date','asset','ewma']],on=['date','asset'],validate='many_to_one')
        for col in ['center','lo','hi']:t[col]=100*np.expm1(np.log1p(t[col]/100)-offset*t.ewma/100)
        t['model']='legacy_cat_median_centered';corrected.append(t)
    p=pd.concat([p,cat.assign(model='legacy_cat_original'),pd.concat(corrected)],ignore_index=True)
    shared=None
    for _,v in p.groupby('model'):
        k=set(zip(v.date,v.asset));shared=k if shared is None else shared&k
    p=p[[k in shared for k in zip(p.date,p.asset)]].copy()
    assert not p.duplicated(['model','level','date','asset']).any()
    assert np.isfinite(p[['center','lo','hi','actual']]).all().all()
    assert (p.lo<=p.center).all() and (p.center<=p.hi).all()
    p.to_parquet(OUT/'predictions.parquet',index=False)
    pd.DataFrame(splits).to_csv(OUT/'splits.csv',index=False)
    d=pd.DataFrame(diagnostics);d.to_csv(OUT/'center_failures.csv',index=False)
    rows=[]
    for period,v in [('all',p),('2025_2026',p[p.date.dt.year>=2025])]:
        for (m,l),z in v.groupby(['model','level']):rows.append(dict(period=period,model=m,level=l,**metrics(z)))
    pd.DataFrame(rows).to_csv(OUT/'metrics.csv',index=False)
    pd.DataFrame([dict(asset=a,model=m,level=l,**metrics(v)) for (a,m,l),v in p.groupby(['asset','model','level'])]).to_csv(OUT/'per_asset.csv',index=False)
    scale=x[['date','asset','ewma','safe_ewma']].merge(rr,on=['date','asset'])
    (OUT/'audit.json').write_text(json.dumps(dict(reproduction_max_pp=reproduction,shared_n=len(shared),scale_max_change=float(abs(scale.ewma-scale.safe_ewma).max()),scale_changed_rows=int(abs(scale.ewma-scale.safe_ewma).gt(1e-6).sum()),protocol='Reused development dates. Quarterly matured training labels. Previous-year forward quarterly OOS residuals, daily overlapping windows, not independent events. Alpha100 unchanged. No test tuning. Legacy Cat has unverified historical macro clocks; diagnostic only. No Gold/Azure/operating-model changes.'),indent=2),encoding='utf8')
    print(pd.DataFrame(rows).query("period=='all' and level==0.9").to_string(index=False))

if __name__=='__main__':
    with threadpool_limits(limits=2):main()
