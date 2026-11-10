"""Fixed-cohort summaries; never reselect stocks using evaluation outcomes."""
import json
import pandas as pd
from select_long_universe import OUT, ROOT
from select_exposure_universe import assemble
from report_long_universe import metric

def main():
    r = pd.read_parquet(OUT/'predictions.parquet')
    pairs = pd.read_csv(OUT/'eligible_pairs.csv', dtype={'asset':str})
    original = set(pd.read_parquet(ROOT/'exports/seongjin_gold_v1_1/gold_stress_daily.parquet', columns=['asset_id']).asset_id)
    event = pd.Series(False, index=r.index)
    for _, p in pairs.iterrows():
        event |= r.asset.eq(p.asset) & r[p.shock+'_event']
    scopes = {
        'selected_all_dates': r.selected,
        'selected_shock_events_union': r.selected & event,
        'original20_common_selected': r.selected & r.asset.isin(original),
        'original20_common_selected_events': r.selected & r.asset.isin(original) & event,
    }
    rows=[]
    for scope, mask in scopes.items():
        for method,z in r[mask].groupby('method'):
            rows.append(dict(scope=scope,method=method,assets=z.asset.nunique(),first=str(z.date.min()),last=str(z.date.max()),**metric(z)))
    pd.DataFrame(rows).to_csv(OUT/'cohort_comparison.csv',index=False)
    pairs.groupby(['shock','direction']).size().rename('pairs').to_csv(OUT/'selected_shock_counts.csv')
    # Restore full candidate source audit separately from training-only audit.
    candidates=json.loads((OUT/'collection_assets.json').read_text())
    _,quality=assemble(candidates)
    quality.to_csv(OUT/'source_quality.csv',index=False)
    summary=dict(candidate_count=len(candidates),selected_assets=int(pairs.asset.nunique()),selected_pairs=len(pairs),original20_common_selected=int(r[r.selected & r.asset.isin(original)].asset.nunique()),evaluation_start=str(r.date.min()),evaluation_end=str(r.date.max()),reused_evaluation=True,selection_uses_post2021_outcomes=False,azure_changed=False,gold_changed=False)
    (OUT/'completion_summary.json').write_text(json.dumps(summary,indent=2),encoding='utf8')

if __name__=='__main__':main()
