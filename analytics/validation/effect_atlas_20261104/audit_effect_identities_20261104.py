import pandas as pd,json
from analyze_effect_atlas_20261104 import ROOT,OUT

def main():
    d=pd.read_parquet(ROOT/'reports/rich_context_20261103/learning_table.parquet');d=d[d.end_date<pd.Timestamp('2022-01-01')-pd.Timedelta(days=20)]
    formulas={'relative_market5':d.asset_trend5-d.market_trend5,'relative_market20':d.asset_trend20-d.market_trend20,'relative_market60':d.asset_trend60-d.market_trend60,
        'equity_assets':1-d.debt_assets,'asset_vol_ratio':d.asset_vol5/d.asset_vol60,'market_vol_ratio':d.market_vol5/d.market_vol60,
        'asset_acceleration':d.asset_trend5-d.asset_trend20/4,'market_acceleration':d.market_trend5-d.market_trend20/4,
        'foreign_flow_accel':d.foreign_flow_5-d.foreign_flow_20,'institution_flow_accel':d.institution_flow_5-d.institution_flow_20}
    rows=[]
    for feature,value in formulas.items():
        error=(d[feature]-value).dropna().abs();assert len(error)>0 and error.max()<1e-8
        rows.append(dict(feature=feature,n=len(error),max_abs_error=float(error.max()),exact_identity=True,period='pre2022',interpretation='Not an independently variable coordinate when parents are held fixed'))
    pd.DataFrame(rows).to_csv(OUT/'exact_feature_identities.csv',index=False)
if __name__=='__main__':main()
