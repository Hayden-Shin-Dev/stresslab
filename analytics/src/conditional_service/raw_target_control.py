"""Ablation separating raw-target choice from pooling; no tuning or promotion."""
import argparse
from pathlib import Path
import pandas as pd
import numpy as np
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import Ridge
from threadpoolctl import threadpool_limits
from .core import features,anchors,STATE,ASSET,SHOCKS,metrics

def run(gold,out):
    out=Path(out);d=features(pd.read_parquet(gold)).dropna(subset=SHOCKS+['target','end_date']);ref=pd.read_parquet(out/'predictions.parquet');rows=[]
    for year in [2023,2024,2025,2026]:
        tr=d[d.end_date<pd.Timestamp(year-1,1,1)-pd.Timedelta(days=20)]
        ca=anchors(d[(d.date>=pd.Timestamp(year-1,1,1))&(d.end_date<pd.Timestamp(year,1,1)-pd.Timedelta(days=20))])
        locked=ref[ref.model.eq('ridge')&ref.fold.eq(year)]
        for asset,z in locked.groupby('asset'):
            train=tr[tr.asset.eq(asset)];cal=ca[ca.asset.eq(asset)];test=d[d.asset.eq(asset)].set_index('date').loc[z.date]
            m=make_pipeline(StandardScaler(),Ridge(alpha=300)).fit(train[STATE+ASSET+SHOCKS],train.target)
            q=np.quantile((cal.target-m.predict(cal[STATE+ASSET+SHOCKS]))/cal.scale,[.1,.9]);r=z.copy();r['center']=m.predict(test[STATE+ASSET+SHOCKS]);r['lo']=r.center.to_numpy()+q[0]*test.scale.to_numpy();r['hi']=r.center.to_numpy()+q[1]*test.scale.to_numpy();r['model']='individual_ridge_raw';rows.append(r)
    p=pd.concat(rows);p.to_parquet(out/'raw_control_predictions.parquet',index=False);pd.DataFrame([dict(model='individual_ridge_raw',**metrics(p))]).to_csv(out/'raw_control_metrics.csv',index=False)
    print(metrics(p))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--gold',required=True);p.add_argument('--out',required=True);a=p.parse_args()
    with threadpool_limits(limits=2):run(a.gold,a.out)
