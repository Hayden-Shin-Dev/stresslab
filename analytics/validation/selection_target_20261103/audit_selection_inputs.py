"""Selection diagnostics and proposed universe expansion; no collection/deployment."""
import json
import numpy as np
import pandas as pd
from selection_target_research import ROOT,OUT,sensitivity

def main():
    g=pd.read_parquet(ROOT/'exports/seongjin_gold_v1_1/gold_stress_daily.parquet');d=pd.read_parquet(ROOT/'reports/model_redesign_20261103/learning_table.parquet');market=g.groupby('trading_date').agg(kospi_close=('kospi_close','first'),wti=('wti','first')).sort_index();market.index=pd.to_datetime(market.index)
    d['market_target']=d.date.map((market.kospi_close.shift(-5)/market.kospi_close-1)*100)
    bad=market.wti.le(0).rolling(6).max().shift(-5).eq(1);dates=set(market.index[bad]);rows=[];stats=[]
    for asset,z in d[d.end_date<pd.Timestamp('2025-01-01')-pd.Timedelta(days=20)].groupby('asset'):
        cleaned=z[~z.date.isin(dates)];rows.extend(sensitivity(cleaned,asset,2026))
        stats.append(dict(asset=asset,train_n=len(z),raw_return_sd=z.target.std(),market_excess_sd=(z.target-z.market_target).std(),market_correlation=z.target.corr(z.market_target),oil_invalid_window_rows=int(z.date.isin(dates).sum())))
    pd.DataFrame(rows).to_csv(OUT/'oil_definition_selection_diagnostic.csv',index=False);pd.DataFrame(stats).to_csv(OUT/'training_target_variance.csv',index=False)
    r=pd.read_parquet(OUT/'predictions.parquet');z=r[r.method=='lgb_total'].merge(d[['asset','date','scale']],on=['asset','date'],validate='one_to_one');z['normalized_mae']=z.center_mae/z.scale
    z.groupby('selected').agg(n=('asset','size'),mean_scale=('scale','mean'),mae=('center_mae','mean'),normalized_mae=('normalized_mae','mean')).to_csv(OUT/'selection_composition.csv')
    h=d[d.end_date<pd.Timestamp('2025-01-01')-pd.Timedelta(days=20)].sort_values('date').drop_duplicates('date')
    audit={'wti_nonpositive_dates':[str(x.date()) for x in market.index[market.wti<=0]],'affected_five_day_start_dates':[str(x.date()) for x in sorted(dates)],
        'interpretation':'actual negative WTI observation, not silently deleted; percentage shocks spanning nonpositive price are not ordinary percentage scenarios; primary4experiments preserve old baseline; selection-only diagnostic excludes6day windows containing nonpositive WTI',
        'all_overlapping_training_windows':len(h),'rate_up50_count':int((h.shock_rate>=50).sum()),'rate_up100_count':int((h.shock_rate>=100).sum()),'fx5_and_rate100_count':int(((h.shock_fx>=5)&(h.shock_rate>=100)).sum()),'rate_max_bp':h.shock_rate.max(),
        'availability':'Gold available_at missing, selection respects row date and label embargo but point-in-time macro publication vintage not certified',
        'expanded_universe':'official validated Gold and adjusted history contain20 stocks only; unverified legacy sources not mixed',
        'selection_stability_not_causal':True}
    (OUT/'input_audit.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf8')
    candidates=[('003490','대한항공','항공'),('020560','아시아나항공','항공'),('010950','S-Oil','정유'),('096770','SK이노베이션','정유 및 에너지'),('051910','LG화학','화학'),('011170','롯데케미칼','화학')]
    pd.DataFrame([dict(asset=a,name=n,industry_description=s,status='candidate_not_trained',period='2000-01-04 or listing date through2026-10-30',source='KRX adjusted daily OHLCV and corporate-action/listing history; existing ECOS/FRED macro reused',fabric_scope='Bronze official raw; Silver adjustment and halt checks; existing Gold schema rows after validation',warning='current candidate description is not historical sector classification; delisting/trading halt dates must be checked') for a,n,s in candidates]).to_csv(OUT/'expansion_candidates.csv',index=False)

if __name__=='__main__':main()
