"""Additional predeclared direct LightGBM 10/90 quantiles under the new80% target."""
import numpy as np
import pandas as pd
from lightgbm import LGBMRegressor
from gold_quantile_benchmark import ROOT,build,FEATURES
from adaptive_residual_benchmark import OUT,rec

def main():
    g=pd.read_parquet(ROOT/'exports/seongjin_gold_v1_1/gold_stress_daily.parquet');data=build(g)
    market=g.groupby('trading_date').kospi_close.first().sort_index();cr=(market.shift(-5)/market-1)*100;cr.index=pd.to_datetime(cr.index)
    rows=[]
    for asset,f in data.groupby('asset'):
        f=f.sort_values('date')
        for year in [2023,2024,2025,2026]:
            cut=pd.Timestamp(year,1,1);cc=pd.Timestamp(year-1,1,1)
            tr=f[f.end_date<cc-pd.Timedelta(days=20)];ca=f[(f.date>=cc)&(f.end_date<cut-pd.Timedelta(days=20))].iloc[::6]
            te=f[(f.date>=cut)&(f.date<pd.Timestamp(year+1,1,1))].iloc[::6];te=te[te.end_date<pd.Timestamp(year+1,1,1)]
            if len(tr)<250 or len(ca)<30 or not len(te):continue
            qs=[]
            for alpha in [.1,.5,.9]:
                m=LGBMRegressor(objective='quantile',alpha=alpha,n_estimators=250,learning_rate=.04,max_depth=4,num_leaves=15,min_child_samples=40,random_state=20261103,n_jobs=2,verbosity=-1)
                m.fit(tr[FEATURES],tr.target/tr.scale);qs.append(m.predict(te[FEATURES])*te.scale.to_numpy())
            raw=np.column_stack(qs);q=np.sort(raw,axis=1)
            for i,(_,t) in enumerate(te.iterrows()):
                r=rec(t,q[i],'lightgbm','direct80',ca.iloc[:0],np.array([]),False,tr.market_vol20.quantile(2/3),cr.get(t.date,np.nan),raw[i,1]);r['crossing']=bool(np.any(np.diff(raw[i])<0));rows.append(r)
        print('direct80',asset,flush=True)
    pd.DataFrame(rows).to_parquet(OUT/'direct80_predictions.parquet',index=False)

if __name__=='__main__':main()
