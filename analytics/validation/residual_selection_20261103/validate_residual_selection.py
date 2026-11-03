"""Fixed-center residual-weight ablation. Research only; no service mutation."""
import sys, json, os
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler
ROOT=Path(os.environ.get('STRESSLAB_AUDIT_ROOT',Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(ROOT))
if (Path(__file__).parent/'reference').exists():sys.path.insert(0,str(Path(__file__).parent/'reference'))
from stresslab.config import STATES, SHOCKS
from stresslab.point_in_time_daily import windows, PerAssetRidge
from stresslab.models import pct
OUT=ROOT/'reports/residual_selection_20261103'
S=['s_'+s for s in SHOCKS];E=['kr3y_level','kr3y_change20_bp'];FEATURES=S+STATES+E

def select(frame):
    chosen=[];end=pd.Timestamp.min
    for i,row in frame.iterrows():
        if row.date>end:chosen.append(i);end=row.end_date
    return frame.loc[chosen]

def weights(distance,strength):
    n=len(distance);u=np.full(n,1/n)
    if strength==0:return u
    bandwidth=max(np.partition(distance,min(39,n-1))[min(39,n-1)],1e-8)
    local=np.exp(-.5*distance/bandwidth);local/=local.sum()
    w=(1-strength)*u+strength*local
    while 1/(w@w)<min(60,n) or w.max()>.05:
        strength*=.5;w=(1-strength)*u+strength*local
    return w

def measure(y,values,w):
    order=np.argsort(values);v=values[order];a=w[order]
    pos=np.cumsum(a)-.5*a;pos=(pos-pos[0])/(pos[-1]-pos[0])
    lo,med,hi=np.interp([.05,.5,.95],pos,v)
    # Exact weighted lower-tail mass, with a fractional boundary observation.
    mass=np.clip(.05-(np.cumsum(a)-a),0,a);es=float((mass*v).sum()/.05)
    return dict(actual=y,median=med,q05=lo,q95=hi,es05=es,mae=abs(y-med),
        squared_error=(y-med)**2,coverage=float(lo<=y<=hi),width=hi-lo,
        interval_score=hi-lo+20*max(lo-y,0)+20*max(y-hi,0),
        pinball05=max(.05*(y-lo),-.95*(y-lo)),var_breach=float(y<lo),
        shortfall_beyond_var=max(lo-y,0),ess=1/(w@w),max_weight=w.max())

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    protocol={'center':'state_ecos_ridge unchanged; train before 2020; calibration 2020-2022',
        'variants':['uniform','state_blend50','state_blend75','state_shock_blend50'],
        'weights':'Gaussian distance bandwidth = 40th calibration neighbor; mix with uniform; ESS>=60 and max weight<=5%; no test tuning',
        'state_search':'6 states only, training-fitted scaler; shock weighting separate diagnostic',
        'joint':'same calibration dates and weights for both portfolio stocks',
        'overlap':'calibration outcome windows disjoint, not independent economic crises',
        'blind':False,'limits':'Previously examined test dates; publication proxies, current universe survivorship; not causal; no intraday input or Azure writes'}
    (OUT/'protocol.json').write_text(json.dumps(protocol,ensure_ascii=False,indent=2),encoding='utf8')
    p=pd.read_parquet(ROOT/'reports/official20_20261102/official_panel.parquet').sort_values('date').reset_index(drop=True)
    g=pd.read_parquet(ROOT/'exports/seongjin_gold_v1_1/gold_stress_daily.parquet')
    w=windows(p,True);w[E[0]]=p.kr3y;w[E[1]]=(p.kr3y-p.kr3y.shift(20))*100
    assets=sorted(g.asset_id.unique())
    for a in assets:
        price=p[a];r=100*np.log(price/price.shift(1));w['scale_'+a]=np.sqrt((r.rolling(20).var()+r.rolling(60).var())/2*5)
        q=g[g.asset_id.eq(a)].set_index('trading_date').quality_status;q.index=pd.to_datetime(q.index)
        good=price.gt(0)&pd.Series(q.reindex(p.date).eq('valid').to_numpy())
        if 'bad_'+a in p:good &= ~p['bad_'+a].fillna(True)
        w['y_'+a]=(100*np.log(price.shift(-5)/price)).where(good.rolling(6).sum().shift(-5).eq(6))
    cal_dates=set(select(w[(w.date>='2020-01-01')&(w.label_schedule_not_before<pd.Timestamp('2023-01-01',tz='Asia/Seoul'))]).date)
    test_dates=pd.to_datetime(pd.read_parquet(ROOT/'reports/official20_20261102/predictions.parquet').date.unique())
    common=w.dropna(subset=FEATURES+['scale_kospi']);rows=[];audit=[]
    for asset in assets+['portfolio']:
        aa=['005930','005380'] if asset=='portfolio' else [asset]
        good=common.dropna(subset=['scale_'+a for a in aa]+['y_'+a for a in aa])
        train=good[good.label_schedule_not_before<pd.Timestamp('2020-01-01',tz='Asia/Seoul')]
        cal=good[good.date.isin(cal_dates)];test=good[good.date.isin(test_dates)]
        if len(train)<250 or len(cal)<30 or len(test)<30:continue
        model=PerAssetRidge(aa,FEATURES).fit({a:train for a in aa}).calibrate(cal)
        draws=pct(model.draws(test)).mean(axis=2);actual=pct(test[['y_'+a for a in aa]].to_numpy()).mean(axis=1)
        centers=np.column_stack([model.models[a].location_scale(model.inputs(test))[0][:,0] for a in aa])
        state=StandardScaler().fit(train[STATES]);cx=state.transform(cal[STATES]);tx=state.transform(test[STATES])
        shock=StandardScaler().fit(train[S].div(train.scale_kospi.clip(lower=.05),axis=0))
        cs=shock.transform(cal[S].div(cal.scale_kospi.clip(lower=.05),axis=0));ts=shock.transform(test[S].div(test.scale_kospi.clip(lower=.05),axis=0))
        assert draws.shape[1]==len(cal)
        for i,(_,query) in enumerate(test.iterrows()):
            ds=((cx-tx[i])**2).mean(axis=1);dc=((cs-ts[i])**2).mean(axis=1)
            variants={'uniform':weights(ds,0),'state_blend50':weights(ds,.5),'state_blend75':weights(ds,.75),'state_shock_blend50':weights((ds+dc)/2,.5)}
            for name,ww in variants.items():
                rec=measure(actual[i],draws[i],ww);rec.update(date=query.date,asset=asset,model=name,center_normalized=float(centers[i].mean()),cal_n=len(cal))
                rows.append(rec)
                if asset=='portfolio':
                    yearmass=pd.Series(ww).groupby(cal.date.dt.year.to_numpy()).sum()
                    audit.append(dict(date=query.date,model=name,largest_year_weight=yearmass.max(),**{str(k):v for k,v in yearmass.items()}))
        print(asset,len(test),flush=True)
    result=pd.DataFrame(rows);result.to_parquet(OUT/'predictions.parquet',index=False)
    assert result.groupby(['date','asset']).center_normalized.nunique().max()==1
    old=pd.read_parquet(ROOT/'reports/search_stress_validation_20261103/predictions.parquet')
    paired=result[result.model.eq('uniform')].merge(old[old.model.eq('state_ecos_ridge')],on=['date','asset'],suffixes=('_new','_old'))
    error=max((paired[k+'_new']-paired[k+'_old']).abs().max() for k in ['median','q05','q95','interval_score'])
    assert error<1e-9,error
    pd.DataFrame(audit).to_csv(OUT/'weight_audit.csv',index=False)
    metrics=[];comparisons=[]
    for scope,part in [('portfolio',result[result.asset.eq('portfolio')]),('stocks',result[~result.asset.eq('portfolio')])]:
        for period,z in [('all',part),('recent3m',part[part.date>='2026-07-16'])]:
            for name,x in z.groupby('model'):
                rec=x[['mae','coverage','width','interval_score','pinball05','var_breach','ess','max_weight','shortfall_beyond_var']].mean().to_dict();rec.update(scope=scope,period=period,model=name,rows=len(x),dates=x.date.nunique(),rmse=np.sqrt(x.squared_error.mean()));metrics.append(rec)
                if name=='uniform':continue
                pair=x.merge(z[z.model.eq('uniform')],on=['date','asset'],suffixes=('_a','_b'))
                for metric in ['mae','interval_score','pinball05']:
                    d=pair.assign(delta=pair[metric+'_a']-pair[metric+'_b']).groupby('date').delta.mean().sort_index().to_numpy();n=len(d);block=min(10,n);rng=np.random.default_rng(20261103)
                    boot=[d[np.concatenate([(s+np.arange(block))%n for s in rng.integers(n,size=int(np.ceil(n/block)))])[:n]].mean() for _ in range(1000)]
                    comparisons.append(dict(scope=scope,period=period,model=name,metric=metric,delta=d.mean(),ci_low=np.quantile(boot,.025),ci_high=np.quantile(boot,.975)))
    pd.DataFrame(metrics).to_csv(OUT/'metrics.csv',index=False);pd.DataFrame(comparisons).to_csv(OUT/'paired_comparisons.csv',index=False)
    flags=old[old.model.eq('state_ecos_ridge')][['date','asset','high_vol']]
    flagged=result.merge(flags,on=['date','asset'],validate='many_to_one')
    # Outcome-selected loss group is a failure diagnostic, never a selection/training feature.
    for label,z in [('high_vol',flagged[flagged.high_vol]),('actual_loss_5pct',flagged[flagged.actual < -5])]:
        summary=z.groupby(['asset','model']).agg(n=('date','size'),coverage=('coverage','mean'),width=('width','mean'),interval_score=('interval_score','mean'),var_breach=('var_breach','mean'),shortfall_beyond_var=('shortfall_beyond_var','mean')).reset_index()
        summary.to_csv(OUT/(label+'.csv'),index=False)
    (OUT/'verification.json').write_text(json.dumps({'fixed_center':True,'uniform_matches_previous_max_error':error,'rows':len(result),'assets':int(result[~result.asset.eq('portfolio')].asset.nunique())},indent=2),encoding='utf8')
    print(pd.DataFrame(metrics).to_string(index=False),flush=True)

if __name__=='__main__':main()
