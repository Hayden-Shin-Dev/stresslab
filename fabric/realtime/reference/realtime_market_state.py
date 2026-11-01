"""Cumulative and recent market analysis. Closed minute bars, never daily ML input."""
import hashlib,json
import numpy as np,pandas as pd
from .market_breadth import aggregate_market
VERSION='market-state-completed-minute-v2'
def value(x):return float(x) if pd.notna(x) and np.isfinite(x) else None
def utc(t):return pd.Timestamp(t).tz_convert('UTC').isoformat().replace('+00:00','Z')
def analyze_market(bars,as_of,assets,previous_close=None,sectors=None,baselines=None,source='historical_replay',session_verified=False,connection_status='unknown',computed_at=None,daily_state_date=None):
    at=pd.Timestamp(as_of)
    if at.tzinfo is None:raise ValueError('timezone required')
    if computed_at is not None and pd.Timestamp(computed_at)<at:raise ValueError('computed_at precedes as_of')
    at=at.tz_convert('UTC');local=at.tz_convert('Asia/Seoul');start=local.normalize()+pd.Timedelta(hours=9)
    end=min(at.floor('min'),local.normalize()+pd.Timedelta(hours=15,minutes=20))
    grid=pd.date_range(start.tz_convert('UTC'),end.tz_convert('UTC')-pd.Timedelta(minutes=1),freq='min') if end>start else pd.DatetimeIndex([],tz='UTC')
    if not assets or len(set(assets))!=len(assets):raise ValueError('unique nonempty universe required')
    b=bars[bars.asset_id.isin(assets)&bars.bar_at.isin(grid)].copy()
    if b.duplicated(['asset_id','bar_at']).any():raise ValueError('duplicate bar key')
    if ((b.price<=0)|~np.isfinite(b.price)).any():raise ValueError('invalid price')
    if (b.volume.dropna()<0).any():raise ValueError('negative volume')
    p=b.pivot(index='bar_at',columns='asset_id',values='price').reindex(index=grid,columns=assets)
    v=b.pivot(index='bar_at',columns='asset_id',values='volume').reindex(index=grid,columns=assets)
    previous_close=previous_close or {};sectors=sectors or {};baselines=baselines or {};rows=[]
    for a in assets:
        q=p[a];vol=v[a];complete=len(q)>0 and q.notna().all();last=q.iloc[-1] if len(q) else np.nan
        ret=np.log(q/q.shift(1))*100
        r5=100*(last/q.iloc[-6]-1) if len(q)>=6 and q.iloc[-6:].notna().all() else np.nan
        std=ret.iloc[-30:].std(ddof=1) if len(q)>=31 and ret.iloc[-30:].notna().all() else np.nan
        rv=np.sqrt(np.square(ret.iloc[1:]).sum()) if complete and len(q)>=2 else np.nan
        opening=b.loc[(b.asset_id==a)&(b.bar_at==start.tz_convert('UTC')),'open'] if 'open' in b else pd.Series(dtype=float)
        op=opening.iloc[0] if len(opening) and pd.notna(opening.iloc[0]) and opening.iloc[0]>0 else np.nan
        prev=previous_close.get(a,np.nan)
        daily=100*(last/prev-1) if pd.notna(prev) and prev>0 else np.nan
        cumvol=vol.sum() if complete and vol.notna().all() else np.nan
        base=baselines.get(a,{})
        def ratio(x,key):
            history=base.get(key)
            return value(x/history) if base.get('prior_days',0)>=15 and history and history>0 else None
        rows.append({'asset_id':a,'return_since_previous_close_pct':value(daily),'return_since_open_pct':value(100*(last/op-1)),
            'return_since_first_minute_pct':value(100*(last/q.iloc[0]-1)) if complete else None,
            'return_5m_pct':value(r5),'volatility_30m_pct':value(std),'realized_volatility_since_open_pct':value(rv),
            'volume_since_open':value(cumvol),'observed_volume':value(vol.sum(min_count=1)),
            'volume_vs_same_time_ratio':ratio(cumvol,'volume'),'volatility_vs_same_time_ratio':ratio(std,'volatility_30m_pct'),
            'minutes_expected':len(grid),'minutes_observed':int(q.notna().sum()),'complete_since_open':bool(complete),
            'baseline_days':int(base.get('prior_days',0)),'sector_id':sectors.get(a)})
    def summary(sub):
        rr=[r['return_5m_pct'] for r in sub if r['return_5m_pct'] is not None];dd=[r['return_since_previous_close_pct'] for r in sub if r['return_since_previous_close_pct'] is not None];oo=[r['return_since_open_pct'] for r in sub if r['return_since_open_pct'] is not None]
        coverage=len(rr)/len(sub) if sub else 0
        mean=float(np.mean(rr)) if coverage>=.8 and rr else None
        return {'expected_asset_count':len(sub),'valid_asset_count':len(rr),'declining_asset_count':sum(x<0 for x in rr),'declining_ratio':sum(x<0 for x in rr)/len(rr) if rr and coverage>=.8 else None,
            'mean_return_5m_pct':mean,'mean_return_since_previous_close_pct':float(np.mean(dd)) if sub and len(dd)/len(sub)>=.8 else None,'previous_close_coverage':len(dd)/len(sub) if sub else 0,
            'mean_return_since_open_pct':float(np.mean(oo)) if sub and len(oo)/len(sub)>=.8 else None,'open_price_coverage':len(oo)/len(sub) if sub else 0,
            'recent_direction':'unavailable' if mean is None else ('up' if mean>0 else 'down' if mean<0 else 'flat')}
    aggregate=summary(rows);sector_rows=[]
    for sector in sorted(set(sectors.values())):
        subset=[r for r in rows if r['sector_id']==sector]
        if subset:sector_rows.append({'sector_id':sector,**summary(subset)})
    recent_grid=pd.date_range(end.tz_convert('UTC')-pd.Timedelta(minutes=61),periods=61,freq='min')
    corr=aggregate_market(p.reindex(recent_grid)) if len(assets)>=2 else {}
    aggregate.update(mean_correlation_60m=corr.get('mean_correlation_60m'),correlation_asset_count=corr.get('correlation_stocks',0),joint_down_ratio_60m=corr.get('joint_down_share_60m'),joint_down_valid_minutes=corr.get('joint_down_valid_minutes',0),sector_classification_coverage=sum(r['sector_id'] is not None for r in rows)/len(rows))
    thresholds={'rapid_drop_5m_pct':-1.0,'declining_ratio':.8,'volatility_vs_same_time_ratio':2.0,'minimum_coverage':.8}
    alerts=[]
    for name,observed,threshold,trigger in [('rapid_drop',aggregate['mean_return_5m_pct'],-1.,lambda x:x<=-1.),('broad_decline',aggregate['declining_ratio'],.8,lambda x:x>=.8)]:
        alerts.append({'kind':name,'value':observed,'threshold':threshold,'triggered':bool(observed is not None and trigger(observed)) if observed is not None else None,'status':'research_rule_not_validated'})
    ratios=[r['volatility_vs_same_time_ratio'] for r in rows if r['volatility_vs_same_time_ratio'] is not None]
    x=float(np.median(ratios)) if len(ratios)/len(rows)>=.8 else None
    alerts.append({'kind':'volatility_expansion','value':x,'threshold':2.,'triggered':bool(x>=2) if x is not None else None,'status':'research_rule_not_validated'})
    last=b.bar_at.max() if len(b) else pd.NaT
    age=(pd.Timestamp(computed_at or at)-(last+pd.Timedelta(minutes=1))).total_seconds() if pd.notna(last) else None
    phase='continuous_session_clock' if local.weekday()<5 and start<=local<local.normalize()+pd.Timedelta(hours=15,minutes=20) else 'outside_continuous_session'
    quality='partial' if aggregate['valid_asset_count']<len(assets) or not all(r['complete_since_open'] for r in rows) else 'valid'
    if age is None or age>120 or connection_status in ['disconnected','reconnecting']:quality='stale'
    if not session_verified and quality=='valid':quality='unverified'
    result={'record_type':'market_state_snapshot','schema_version':'2.0','as_of':utc(at),'computed_at':utc(computed_at or at),'window_start':utc(start),'last_event_time':None,'last_completed_bar_end':utc(last+pd.Timedelta(minutes=1)) if pd.notna(last) else None,
        'universe_id':'stocks-'+hashlib.sha256('|'.join(sorted(assets)).encode()).hexdigest()[:16],'whole_kospi':False,'quality_status':quality,'session_verified':session_verified,'market_phase':phase,'connection_status':connection_status,'source':source,'feature_version':VERSION,'is_mock':False,
        'expected_asset_count':aggregate['expected_asset_count'],'valid_asset_count':aggregate['valid_asset_count'],'declining_asset_count':aggregate['declining_asset_count'],'declining_ratio':aggregate['declining_ratio'],
        'market':aggregate,'assets':rows,'sectors':sector_rows,'signals':alerts,'signal_policy':thresholds,'applied_to_daily_ml':False,'daily_state_date':daily_state_date,
        'limitations':['세션과 공급자 날짜 인증은 별도입니다.','수익률 집계는 관측 종목 동일가중이며 코스피 지수가 아닙니다.','위험 신호 임계값은 연구용 규칙이며 예측 성능이 승인되지 않았습니다.','누적 실현변동성은 첫 완료 분 종가 이후 수익률 기준이며 첫 분 내부 변동을 포함하지 않습니다.']}
    result['snapshot_id']=hashlib.sha256(json.dumps(result,sort_keys=True,allow_nan=False).encode()).hexdigest()[:24]
    return result


def same_clock_baselines(bars,as_of,assets):
    """Prior completed sessions only; no daily-volume proxy or future sessions."""
    at=pd.Timestamp(as_of).tz_convert('Asia/Seoul');minutes=min(380,int((at-at.normalize()).total_seconds()/60)-540)
    if minutes<31:return {}
    b=bars[bars.asset_id.isin(assets)&(bars.bar_at<at.normalize())].copy()
    local=b.bar_at.dt.tz_convert('Asia/Seoul');b['day']=local.dt.strftime('%Y-%m-%d');b['minute']=local.dt.hour*60+local.dt.minute-540
    b=b[(b.minute>=0)&(b.minute<minutes)]
    result={}
    for asset,g in b.groupby('asset_id'):
        observations=[]
        for day,h in g.groupby('day'):
            h=h.sort_values('minute')
            if len(h)!=minutes or h.minute.nunique()!=minutes or h.volume.isna().any():continue
            log=np.diff(np.log(h.price.to_numpy()))*100
            observations.append((day,float(h.volume.sum()),float(np.std(log[-30:],ddof=1))))
        observations=sorted(observations)[-20:]
        if observations:result[asset]={'prior_days':len(observations),'volume':float(np.median([x[1] for x in observations])),'volatility_30m_pct':float(np.median([x[2] for x in observations]))}
    return result
