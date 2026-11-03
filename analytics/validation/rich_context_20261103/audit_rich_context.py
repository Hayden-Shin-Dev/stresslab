"""Independent source arithmetic and time-boundary checks for the research run."""
import json,hashlib
import numpy as np
import pandas as pd
from build_rich_context import OUT,FLOW,ROOT,number,accounts
from research_shock_context import COLS

def main():
    d=pd.read_parquet(OUT/'learning_table.parquet')
    old=pd.read_parquet(ROOT/'reports/shock_context_20261103/learning_table.parquet')
    z=d.merge(old[['asset','date','target']+COLS],on=['asset','date'],suffixes=('_new','_old'),validate='one_to_one')
    assert len(z)==len(d)
    for c in ['target']+COLS:assert np.allclose(z[c+'_new'],z[c+'_old'],equal_nan=True),c
    g=pd.read_parquet(ROOT/'reports/long_universe_20261103/research_daily_input.parquet')
    calendar=pd.DatetimeIndex(sorted(g.trading_date.unique()));checked=0
    for asset,f in d.groupby('asset'):
        raw=[]
        for path in sorted((FLOW/'stocks'/asset).glob('*.json')):raw+=json.loads(path.read_text(encoding='utf8'))
        raw=pd.DataFrame(raw);raw.index=pd.to_datetime(raw.TRD_DD)
        for _,row in f.iloc[np.linspace(0,len(f)-1,min(3,len(f)),dtype=int)].iterrows():
            # Truncate BEFORE the state date, then independently calculate the lagged feature.
            hist=raw.reindex(calendar[calendar<row.date]);v=number(hist.TRDVAL4)
            expected=v.tail(20).mean()/v.tail(60).abs().mean()
            assert np.isclose(expected,row.foreign_flow_20), (asset,str(row.date),'future_flow_or_alignment')
            checked+=1
    receipts=pd.read_csv(OUT/'financial_receipts.csv',dtype={'receipt_no':str})
    assert (pd.to_datetime(receipts.known_from)>pd.to_datetime(receipts.receipt_no.str[:8],format='%Y%m%d')).all()
    audit=pd.read_csv(OUT/'time_audit.csv')
    assert (pd.to_datetime(audit.train_end)<pd.to_datetime(audit.test_start)).all()
    search=pd.read_csv(OUT/'market_search_audit.csv')
    assert (pd.to_datetime(search.closest_label_end)<pd.to_datetime(search.date)).all()
    assert not search.shock_used_in_search.any()
    p=pd.read_parquet(OUT/'predictions.parquet')
    assert p.groupby(['asset','date']).method.nunique().eq(9).all()
    for _,f in p[p.method.eq('all')].groupby('asset'):
        f=f.sort_values('date');assert (f.end_date.to_numpy()[:-1]<f.date.to_numpy()[1:]).all()
    gold=ROOT/'exports/seongjin_gold_v1_1/gold_stress_daily.parquet'
    digest=hashlib.sha256(gold.read_bytes()).hexdigest();assert digest==json.loads((OUT/'protocol.json').read_text())['gold_sha256']
    result=dict(status='passed',stocks=int(d.asset.nunique()),learning_rows=len(d),past_flow_prefix_checks=checked,
        inherited_features_and_targets_unchanged=True,financial_receipt_after_publication=True,
        future_shocks='Allowed only as conditional scenario inputs, not in state search',
        no_overlapping_evaluation_labels=True,all_nine_methods_same_keys=True,gold_unchanged=True,
        macro_release_vintage_certified=False,stock_survivorship_bias_resolved=False)
    (OUT/'independent_audit.json').write_text(json.dumps(result,indent=2),encoding='utf8');print(json.dumps(result))

if __name__=='__main__':main()
