"""Independent label, macro-window and feature-prefix checks."""
import json
import numpy as np
import pandas as pd
from asset_feature_research import ROOT, make_data, EXPANDED, SHOCKS
SRC=ROOT/'reports/long_universe_20261103'
OUT=ROOT/'reports/center_audit_20261103'

def main():
    g=pd.read_parquet(SRC/'research_daily_input.parquet').sort_values(['asset_id','trading_date'])
    d=pd.read_parquet(SRC/'learning_table.parquet')
    audit=[]
    for asset,z in g.groupby('asset_id'):
        f=d[d.asset.eq(asset)].set_index('date')
        if f.empty:continue
        z=z.set_index('trading_date')
        for shock,col,relative,mult in [('shock_fx','usdkrw',True,100),('shock_rate','us_treasury_10y',False,100),('shock_oil','wti',True,100),('shock_vix','vix',False,1)]:
            value=(z[col].shift(-5)/z[col]-1)*mult if relative else (z[col].shift(-5)-z[col])*mult
            error=(f[shock]-value.reindex(f.index)).abs().max()
            assert error<1e-9
            audit.append(dict(asset=asset,shock=shock,rows=len(f),max_error=error))
    pd.DataFrame(audit).to_csv(OUT/'shock_window_audit.csv',index=False)
    m=g[g.asset_id.eq('005930')].copy();macro=[]
    for c in ['usdkrw','us_treasury_10y','wti','vix','korea_3y']:
        obs=pd.to_datetime(m[c+'_observation_date']);age=(m.trading_date-obs).dt.total_seconds()/86400
        macro.append(dict(series=c,rows=len(m),missing_values=int(m[c].isna().sum()),missing_observation_date=int(obs.isna().sum()),observation_date_after_trading_date=int(age.lt(0).sum()),observation_age_over7_days=int(age.gt(7).sum()),max_observation_age_days=float(age.max()),missing_available_at=int(m[c+'_available_at'].isna().sum())))
    pd.DataFrame(macro).to_csv(OUT/'macro_timing_audit.csv',index=False)
    # Removing all future rows must leave current-state features unchanged.
    sub=g[g.asset_id.isin(['005930','005380','003490'])]
    full,_=make_data(sub,require_outcome=False);state=[c for c in EXPANDED if c not in SHOCKS]
    checks=[]
    for date in ['2008-10-24','2020-03-20','2025-04-09']:
        cut=pd.Timestamp(date);prefix,_=make_data(sub[sub.trading_date<=cut],require_outcome=False)
        a=full[full.date.eq(cut)].set_index('asset');b=prefix[prefix.date.eq(cut)].set_index('asset')
        assert len(a)>0 and set(a.index)==set(b.index)
        error=(a[state]-b[state]).abs().max().max();assert error<1e-10
        checks.append(dict(date=date,assets=len(a),state_max_error=float(error)))
    (OUT/'feature_prefix_audit.json').write_text(json.dumps(checks,indent=2),encoding='utf8')

if __name__=='__main__':main()
