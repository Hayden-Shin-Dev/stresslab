"""Prepare a dated correction proposal from acquired vintages, without changing Gold/model."""
import json
from pathlib import Path
import pandas as pd
from .audit_publication_vintages import MAPPING,vintages

def main():
    root=Path('reports/service_certification_20261104')
    g=pd.read_parquet('reports/support_expansion_20261104/research_input.parquet')
    days=sorted(pd.to_datetime(g.trading_date).unique());results=[];stats={}
    old=g.drop_duplicates('trading_date').set_index('trading_date')
    for name,series in MAPPING.items():
        v=vintages(series).sort_values(['known_by','observation_date','vintage_date'])
        events=list(v.itertuples());cursor=0;observations={};changed=0;missing=0
        for day in days:
            cutoff=pd.Timestamp(day).tz_localize('Asia/Seoul')+pd.Timedelta(hours=15,minutes=30)
            while cursor<len(events) and events[cursor].known_by<=cutoff:
                r=events[cursor];observations[r.observation_date]=r;cursor+=1
            eligible=[r for d,r in observations.items() if d<=str(pd.Timestamp(day).date()) and pd.notna(r.numeric_value)]
            chosen=max(eligible,key=lambda r:r.observation_date) if eligible else None
            if chosen is None:missing+=1
            elif abs(float(old.loc[day,name])-chosen.numeric_value)>1e-9:changed+=1
            results.append(dict(model_basis_date=str(pd.Timestamp(day).date()),source=name,
                value=float(chosen.numeric_value) if chosen else None,
                observation_date=chosen.observation_date if chosen else None,
                known_by=chosen.known_by.isoformat() if chosen else None,available_at=None,
                availability_basis='official_vintage_date_upper_bound',verified=chosen is not None,
                previous_observation_used=bool(chosen and chosen.observation_date<str(pd.Timestamp(day).date())),source_file=chosen.source_file if chosen else None))
        stats[name]=dict(dates=len(days),no_certified_observation=missing,values_changed_from_frozen_gold=changed)
    pd.DataFrame(results).to_parquet(root/'verified_macro_history_proposal.parquet',index=False)
    (root/'macro_correction_plan.json').write_text(json.dumps(dict(summary=stats,gold_modified=False,model_modified=False,
        ecos='No historical publication evidence; no synthetic fallback',
        consequence='Corrected observations change historical feature values. Fixed trained coefficients cannot be retroactively certified by editing metadata.'),indent=2),encoding='utf8')
    print(json.dumps(stats))

if __name__=='__main__':main()
