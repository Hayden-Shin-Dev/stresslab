"""Gold structural checks and future-price perturbation check; not a PIT certification."""
import json,os
from pathlib import Path
import pandas as pd
from gold_quantile_benchmark import ROOT,OUT,build,FEATURES,SHOCKS

def main():
    g=pd.read_parquet(ROOT/'exports/seongjin_gold_v1_1/gold_stress_daily.parquet')
    schema=Path(os.environ.get('STRESSLAB_GOLD_SCHEMA',ROOT.parent/'stresslab-team/contracts/daily/schema.json'))
    s=json.loads(schema.read_text(encoding='utf8'))
    assert set(g.columns)==set(s['items']['properties'])
    assert not g.duplicated(['dataset_version','trading_date','asset_id']).any() and not g.is_mock.any()
    shared=['kospi_close','usdkrw','us_treasury_10y','wti','vix','korea_3y']
    assert g.groupby('trading_date')[shared].nunique().max().max()==1
    obs={c:int((pd.to_datetime(g[c])>pd.to_datetime(g.trading_date)).sum()) for c in g if c.endswith('_observation_date')}
    assert max(obs.values())==0
    small=g[g.asset_id.isin(['005930','005380'])].copy();base=build(small);t=pd.Timestamp('2025-06-02')
    changed=small.copy();changed.loc[pd.to_datetime(changed.trading_date)>t,'close']*=1.1;new=build(changed)
    cols=[c for c in FEATURES if c not in SHOCKS]
    assert base[base.date.eq(t)].sort_values('asset')[cols].equals(new[new.date.eq(t)].sort_values('asset')[cols])
    result={'schema_columns_exact':True,'unique_primary_key':True,'shared_daily_market_values_consistent':True,
        'observation_dates_after_state':obs,'future_price_mutation_keeps_current_features':True,
        'publication_nulls':{c:int(g[c].isna().sum()) for c in g if c.endswith('_available_at')},'rows':len(g)}
    OUT.mkdir(parents=True,exist_ok=True);(OUT/'gold_input_audit.json').write_text(json.dumps(result,indent=2),encoding='utf8')
    print('Gold checks passed; publication timestamps remain unverified')

if __name__=='__main__':main()
