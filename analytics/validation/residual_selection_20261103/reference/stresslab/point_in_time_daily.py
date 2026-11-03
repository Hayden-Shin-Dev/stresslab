"""Per-asset samples and explicit observation/publication boundaries.
Schedule estimates are diagnostic proxies, never historical release evidence.
"""
import numpy as np,pandas as pd
from pandas.tseries.holiday import USFederalHolidayCalendar
from pandas.tseries.offsets import CustomBusinessDay
from .config import ASSETS,SHOCKS,STATES
from .models_v2 import add_scales
from .models import DistributionModel
BUS=CustomBusinessDay(calendar=USFederalHolidayCalendar())

def scheduled_available(dates,factor):
    values=[]
    for d in pd.to_datetime(dates):
        if pd.isna(d):values.append(pd.NaT);continue
        if factor=='usdkrw':
            # Weekly H10 since 2009; earlier years deliberately conservative proxy.
            release=BUS.rollforward(d.normalize()+pd.Timedelta(days=7-d.weekday()))
        elif factor=='us_treasury_10y':release=d.normalize()+BUS
        else:raise ValueError('no_verified_release_schedule')
        values.append((release+pd.Timedelta(hours=16,minutes=15)).tz_localize('America/New_York').tz_convert('UTC'))
    return pd.Series(pd.to_datetime(values,utc=True),index=dates.index)

def released_state(panel):
    p=panel.copy();cutoff=pd.to_datetime(p.date).dt.tz_localize('Asia/Seoul')+pd.Timedelta(hours=15,minutes=30)
    for factor in ['usdkrw','us_treasury_10y']:
        # Recover distinct source observations without fabricating an observed publication time.
        obs=p[[factor,factor+'_source_date']].dropna().drop_duplicates(factor+'_source_date').sort_values(factor+'_source_date')
        obs['schedule_not_before']=scheduled_available(obs[factor+'_source_date'],factor)
        obs=obs.sort_values(['schedule_not_before',factor+'_source_date']).drop_duplicates('schedule_not_before',keep='last')
        joined=pd.merge_asof(pd.DataFrame({'cutoff':cutoff.dt.tz_convert('UTC')}),obs,left_on='cutoff',right_on='schedule_not_before',direction='backward')
        p['state_'+factor]=joined[factor].to_numpy()
        p[factor+'_state_observation_date']=joined[factor+'_source_date'].to_numpy()
        p[factor+'_schedule_not_before']=joined.schedule_not_before.to_numpy()
    p['fx_trend20']=p.state_usdkrw.pct_change(20,fill_method=None)*100
    p['us_yield_level']=p.state_us_treasury_10y
    p['publication_verified']=False
    return p

def windows(panel,release_aware=False,horizon=5):
    p=panel.sort_values('date').reset_index(drop=True);state=released_state(p) if release_aware else p
    w=state[['date']+STATES].copy();w['end_date']=p.date.shift(-horizon)
    # Retrospective observed shock labels stay unchanged: do not turn information updates into market shocks.
    common=p[list(SHOCKS)].notna().all(axis=1).rolling(horizon+1).sum().shift(-horizon).eq(horizon+1)
    for f,m in SHOCKS.items():
        future=p[f].shift(-horizon)
        w['s_'+f]=((future/p[f]-1)*100 if m['kind']=='relative' else (future-p[f])*(100 if m['kind']=='bp' else 1)).where(common)
        w[f+'_shock_start_observed_date']=p[f+'_source_date']
        w[f+'_shock_end_observed_date']=p[f+'_source_date'].shift(-horizon)
    for a in ASSETS:
        valid=p[a].gt(0).rolling(horizon+1).sum().shift(-horizon).eq(horizon+1)
        w['y_'+a]=(100*np.log(p[a].shift(-horizon)/p[a])).where(valid)
    w=w.merge(add_scales(p,horizon),on='date',validate='one_to_one')
    ready=pd.to_datetime(w.end_date).dt.tz_localize('Asia/Seoul')+pd.Timedelta(hours=21)
    for f in ['usdkrw','us_treasury_10y']:
        pub=scheduled_available(w[f+'_shock_end_observed_date'],f)
        ready=pd.concat([ready.dt.tz_convert('UTC'),pub],axis=1).max(axis=1)
    w['label_schedule_not_before']=ready
    w['publication_verified']=False
    return w

class PerAssetRidge:
    def __init__(self,assets,features,name='ridge'):
        self.assets=assets;self.features=features;self.name=name
    def inputs(self,w):
        x=w[self.features].to_numpy().copy();x[:,:4]/=np.maximum(w.scale_kospi.to_numpy()[:,None],.05)
        return x if self.name=='ridge' else np.zeros((len(x),1))
    def fit(self,frames):
        self.models={}
        for a in self.assets:
            w=frames[a];scale=np.maximum(w['scale_'+a].to_numpy(),.05)
            self.models[a]=DistributionModel('ridge' if self.name=='ridge' else 'unconditional_history').fit(self.inputs(w),(w['y_'+a].to_numpy()/scale)[:,None])
        return self
    def calibrate(self,w):
        for a in self.assets:
            self.models[a].calibrate(self.inputs(w),(w['y_'+a].to_numpy()/np.maximum(w['scale_'+a].to_numpy(),.05))[:,None])
        return self
    def draws(self,w):
        return np.concatenate([self.models[a].draws(self.inputs(w))*np.maximum(w['scale_'+a].to_numpy(),.05)[:,None,None] for a in self.assets],axis=2)

def require_verified_publication(frame):
    if not frame.publication_verified.fillna(False).all():raise ValueError('historical publication timestamps and vintages required')
