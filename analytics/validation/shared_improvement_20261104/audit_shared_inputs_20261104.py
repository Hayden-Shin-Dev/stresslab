"""Descriptive input/target drift audit; no outcome-based sample removal."""
import json
import numpy as np
import pandas as pd
from gold_quantile_benchmark import ROOT,FEATURES,build
from shared_improvement_20261104 import OUT
def main():
    g=pd.read_parquet(ROOT/'exports/seongjin_gold_v1_1/gold_stress_daily.parquet');d=build(g);d=d[d.asset!='portfolio'];locked=pd.read_parquet(ROOT/'reports/gold20_locked_20261104/locked_baseline.parquet');rows=[]
    for asset,f in d.groupby('asset'):
        tr=f[f.end_date<pd.Timestamp('2025-01-01')-pd.Timedelta(days=20)];te=f[f.date.isin(locked.loc[(locked.asset==asset)&(locked.fold==2026),'date'])]
        for col in FEATURES:
            low,high=tr[col].quantile([.01,.99]);rows.append(dict(asset=asset,feature=col,train_median=tr[col].median(),evaluation_median=te[col].median(),train_p01=low,train_p99=high,evaluation_outside_p01_p99=((te[col]<low)|(te[col]>high)).mean(),train_n=len(tr),evaluation_n=len(te)))
    pd.DataFrame(rows).to_csv(OUT/'feature_range_shift_2026.csv',index=False)
    d.assign(abs_target=d.target.abs()).nlargest(50,'abs_target')[['asset','date','end_date','target','shock_fx','shock_rate','shock_oil','shock_vix']].to_csv(OUT/'largest_historical_returns_audit.csv',index=False)
    obs=[]
    for factor in ['usdkrw','us_treasury_10y','wti','vix','korea_3y']:
        col=factor+'_observation_date';delta=(pd.to_datetime(g.trading_date)-pd.to_datetime(g[col])).dt.days
        obs.append(dict(factor=factor,missing_observation_dates=int(delta.isna().sum()),observation_after_trading_date=int((delta<0).sum()),median_calendar_age=delta.median(),max_calendar_age=delta.max(),missing_actual_publication_fraction=g[factor+'_available_at'].isna().mean()))
    pd.DataFrame(obs).to_csv(OUT/'macro_time_audit.csv',index=False)
    schema=json.loads((ROOT.parent/'stresslab-team/contracts/daily/schema.json').read_text(encoding='utf8'))
    assert len(g.columns)==34 and set(g.columns)==set(schema['items']['required'])
    (OUT/'schema_check.json').write_text(json.dumps(dict(columns=34,contract_matches=True,modified=False)),encoding='utf8')
    print(pd.DataFrame(obs).to_string(index=False))
if __name__=='__main__':main()
