"""Observed same-date oil episodes and nonpositive-price definition sensitivity."""
import json
import pandas as pd
from evaluate_sector6_factors import OUT
from selection_target_research import sensitivity
from diagnose_shock_evidence import episode_starts

def main():
    d=pd.read_parquet(OUT/'learning_table.parquet');g=pd.read_parquet(OUT/'research_daily_input.parquet');assets=['003490','020560','010950','096770','051910','011170'];d=d[d.asset.isin(assets)]
    common=d.groupby('date').asset.nunique();d=d[d.date.isin(common[common==6].index)]
    hist=d[d.shock_oil>=10];starts=episode_starts(hist[hist.asset==assets[0]])['date'];rows=[]
    for asset,z in hist.groupby('asset'):
        s=z[z.date.isin(starts)];rows.append(dict(asset=asset,overlapping_windows=len(z),episode_first_n=len(s),episode_first_negative_fraction=(s.target<0).mean(),episode_first_median=s.target.median()))
    pd.DataFrame(rows).to_csv(OUT/'oil_episode_first_reactions.csv',index=False)
    market=g.groupby('trading_date').agg(price=('kospi_close','first'),wti=('wti','first')).sort_index();market.index=pd.to_datetime(market.index);bad=market.wti.le(0).rolling(6).max().shift(-5).eq(1);bad_dates=set(market.index[bad]);mt=(market.price.shift(-5)/market.price-1)*100
    full=pd.read_parquet(OUT/'learning_table.parquet');full['market_target']=full.date.map(mt);records=[]
    for asset,z in full[full.asset.isin(assets)].groupby('asset'):
        tr=z[(z.end_date<pd.Timestamp('2025-01-01')-pd.Timedelta(days=20))&~z.date.isin(bad_dates)]
        records.extend(sensitivity(tr,asset,2026))
    pd.DataFrame(records).to_csv(OUT/'nonpositive_oil_excluded_sensitivity.csv',index=False)
    (OUT/'oil_diagnostic.json').write_text(json.dumps({'excluded_start_dates':[str(x.date()) for x in sorted(bad_dates)],'model_results_unchanged':True,'caution':'exclusion also changes6row sampling phase; coefficient robustness diagnostic, not controlled single-observation attribution'},indent=2))

if __name__=='__main__':main()
