"""Training-scaled local calibration; no test-label neighbor selection."""
import json
import numpy as np
import pandas as pd
import joblib
from pooled_stress_core_20261104 import ROOT,OUT as PREV,STATE,SHOCKS,prepare,point_score,interval_score
from service_candidate_20261104 import components
from crash_cases_center_20261104 import inputs,DOM
from crash_separation_20261104 import OUT,report

def wq(y,w,qs):
    ix=np.argsort(y);y=y[ix];w=w[ix];c=(np.cumsum(w)-.5*w)/w.sum()
    return np.interp(qs,c,y)
def main():
    d,g=prepare();d=d.merge(inputs()[['asset','date']+DOM+['diagnostic_only_future_market5']],on=['asset','date'],validate='one_to_one')
    rows=[];audit=[]
    for year in [2020,2021,2023,2024,2025,2026]:
        pack=joblib.load(PREV/'folds'/f'{year}_models.joblib');frames={}
        for split,suf in [('test','points'),('cal','calibration')]:
            z=pd.read_parquet(PREV/'folds'/f'{year}_{suf}.parquet');z=z[z.model=='catboost']
            frames[split]=z[['asset','date','regime']].merge(d,on=['asset','date'],validate='one_to_one')
        te=frames['test'];ca=frames['cal'];tc=components(te,pack)[1];cc=components(ca,pack)[1]
        errors=(ca.target.to_numpy()-cc)/ca.scale.to_numpy();qglobal=np.quantile(errors,[.1,.9])
        tr=d[(d.end_date<pd.Timestamp(year-1,1,1)-pd.Timedelta(days=20))&d.oil_valid]
        for mode in ['recent','state','state_shock']:
            cols=STATE+['market_return5','market_drawdown60']+(SHOCKS if mode=='state_shock' else [])
            med=tr[cols].median();scale=(tr[cols].quantile(.75)-tr[cols].quantile(.25)).replace(0,1)
            cx=((ca[cols]-med)/scale).fillna(0).to_numpy();tx=((te[cols]-med)/scale).fillna(0).to_numpy()
            recency=np.exp(-np.log(2)*(ca.date.max()-ca.date).dt.days.to_numpy()/180)
            # Equal date mass prevents dates with more observed stocks dominating.
            recency/=ca.groupby('date').date.transform('size').to_numpy()
            qs=[];eff=[]
            for x in tx:
                w=recency.copy()
                if mode!='recent':
                    dist=np.mean((cx-x)**2,axis=1);local=np.exp(-np.minimum(dist,50)/2)
                    w*=.25+.75*local
                qs.append(wq(errors,w,[.1,.5,.9]))
                bydate=pd.Series(w,index=ca.date).groupby(level=0).sum();eff.append(bydate.sum()**2/(bydate**2).sum())
            qs=np.asarray(qs)
            base=te[['asset','date','end_date','sector','regime','scale','target']].rename(columns={'target':'actual'}).copy();base['fold']=year
            for policy in ['center_only','interval_only','both']:
                z=base.copy();z['model']='cal_'+mode+'_'+policy;z['center']=tc if policy=='interval_only' else tc+qs[:,1]*te.scale.to_numpy()
                if policy=='center_only':z['lo']=z.center+qglobal[0]*z.scale;z['hi']=z.center+qglobal[1]*z.scale
                else:z['lo']=tc+qs[:,0]*z.scale;z['hi']=tc+qs[:,2]*z.scale
                rows.append(z)
            audit.append(dict(year=year,mode=mode,min_effective_dates=min(eff),median_effective_dates=np.median(eff),cal_dates=ca.date.nunique()))
    old=pd.read_parquet(OUT/'predictions.parquet');old=old[~old.model.str.startswith('cal_')];r=pd.concat([old,*rows],ignore_index=True)
    r.to_parquet(OUT/'predictions.parquet',index=False);pd.DataFrame(audit).to_csv(OUT/'local_calibration_audit.csv',index=False)
    (OUT/'local_calibration_protocol.json').write_text(json.dumps(dict(half_life_days=180,kernel='exp(-mean squared train IQR standardized distance /2)',global_floor=.25,selection='same2020/21 development gate, no tuning on evaluation',date_weights='one total mass per date before recency/local weights',limitations='Effective dates remain small; calibration similarity is not tail guarantee'),indent=2))
    report(r,d)
if __name__=='__main__':main()
