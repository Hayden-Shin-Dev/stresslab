"""Historical conditional response map; descriptive associations, not causal effects."""
import json
import numpy as np
import pandas as pd
from research_shock_context import OUT,SHOCKS

def main():
    d=pd.read_parquet(OUT/'learning_table.parquet');rows=[]
    for asset,f in d.groupby('asset'):
        train=f[f.end_date<pd.Timestamp('2021-12-12')].sort_values('date');hist=train.iloc[::6]
        high=train.market_vol20.quantile(.75)
        for shock in SHOCKS:
            threshold=train[shock].abs().quantile(.75)
            for period,h in [('pre2022',hist),('2023plus',f[f.date>=pd.Timestamp('2023-01-01')].sort_values('date').iloc[::6])]:
                for sign in ['increase','decrease']:
                    event=h[h[shock]>=threshold] if sign=='increase' else h[h[shock]<=-threshold]
                    for trend in ['up','down']:
                        z=event[event.market_trend20.ge(0)] if trend=='up' else event[event.market_trend20.lt(0)]
                        for vol in ['ordinary','high']:
                            q=z[z.market_vol20>high] if vol=='high' else z[z.market_vol20<=high]
                            rows.append(dict(asset=asset,shock=shock,period=period,shock_direction=sign,prior_market_trend=trend,prior_market_volatility=vol,n=len(q),years=q.date.dt.year.nunique(),shock_threshold=threshold,actual_median=q.target.median(),actual_mean=q.target.mean(),up_fraction=q.target.gt(0).mean(),crash_fraction=q.target.le(-5).mean(),sparse=len(q)<30))
    pd.DataFrame(rows).to_csv(OUT/'historical_response_map.csv',index=False)

if __name__=='__main__':main()
