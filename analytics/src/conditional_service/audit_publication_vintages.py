"""Compare frozen Gold to official vintages. No training and no timestamp fabrication."""
import json,hashlib
from pathlib import Path
import pandas as pd
import numpy as np

ROOT=Path('data/research/service_certification_20261104')
MAPPING={'usdkrw':'DEXKOUS','us_treasury_10y':'DGS10','wti':'DCOILWTICO','vix':'VIXCLS'}

def vintages(series):
    rows=[]
    for path in (ROOT/'fred').glob(series+'*.json'):
        if path.name.endswith(('.receipt.json','.failure.json')):continue
        receipt=json.loads(path.with_name(path.stem+'.receipt.json').read_text())
        assert hashlib.sha256(path.read_bytes()).hexdigest()==receipt['sha256'],'Source checksum mismatch'
        data=json.loads(path.read_text())
        if 'observations' not in data:continue
        assert len(data['observations'])==data['count'],'Incomplete API pagination'
        for r in data['observations']:
            rows.append(dict(observation_date=r['date'],vintage_date=r['realtime_start'],
                vintage_end_date=r['realtime_end'],value=r['value'],source_file=str(path)))
    frame=pd.DataFrame(rows).drop_duplicates(['observation_date','vintage_date','value'])
    frame['numeric_value']=pd.to_numeric(frame.value,errors='coerce')
    # Date-only evidence: end of the calendar date in UTC-12 (global upper bound).
    # This is a conservative availability boundary, NOT an exact publication time.
    frame['known_by']=frame.vintage_date.map(lambda d:pd.Timestamp(d,tz='UTC')+pd.Timedelta(hours=36))
    return frame

def main():
    g=pd.read_parquet('reports/support_expansion_20261104/research_input.parquet')
    g=g.sort_values(['trading_date','asset_id']).drop_duplicates('trading_date')
    output=Path('reports/service_certification_20261104');output.mkdir(exist_ok=True)
    results=[];latest={};coverage={}
    for key,series in MAPPING.items():
        v=vintages(series)
        v.to_parquet(output/(series+'_vintages.parquet'),index=False)
        coverage[key]=dict(series=series,vintage_rows=len(v),earliest_vintage=v.vintage_date.min(),
            observation_start=v.observation_date.min(),observation_end=v.observation_date.max(),
            exact_intraday_publication_time=False,date_only_upper_bound=True)
        by_observation={k:q for k,q in v.groupby('observation_date')}
        for row in g.itertuples():
            obs=getattr(row,key+'_observation_date');val=getattr(row,key)
            date=pd.Timestamp(row.trading_date).strftime('%Y-%m-%d')
            # Strict model convention: end of previous confirmed daily bar, not download time.
            cutoff=pd.Timestamp(date+' 15:30',tz='Asia/Seoul').tz_convert('UTC')
            all_versions=by_observation.get(str(pd.Timestamp(obs).date()),v.iloc[:0])
            known_versions=all_versions[all_versions.known_by<=cutoff].sort_values('known_by')
            matching=all_versions[np.isclose(all_versions.numeric_value,float(val),equal_nan=False)]
            eligible=matching[matching.known_by<=cutoff]
            if not eligible.empty:
                record=known_versions.iloc[-1]
                status='known_before_cutoff' if np.isclose(record.numeric_value,float(val)) else 'superseded_before_cutoff'
            elif matching.empty:status='value_not_found_in_vintages';record=None
            else:
                record=matching.sort_values('known_by').iloc[0]
                first_possible=pd.Timestamp(record.vintage_date,tz='UTC')-pd.Timedelta(hours=14)
                status='not_available_even_at_start_of_vintage_day' if first_possible>cutoff else 'same_day_time_unresolved'
            if pd.isna(obs) or pd.isna(val):status='original_gold_missing_observation'
            if date<coverage[key]['earliest_vintage']:
                status='before_vintage_archive_no_historical_proof'
            result=dict(model_basis_date=date,source=key,observation_date=str(pd.Timestamp(obs).date()),value=float(val),status=status,
                known_by=record.known_by.isoformat() if record is not None else None,
                available_at=None,availability_basis='official_vintage_date_upper_bound',cutoff=cutoff.isoformat())
            results.append(result)
            if date==g.trading_date.max().strftime('%Y-%m-%d'):
                previous=v[(v.known_by<=cutoff) & v.observation_date.le(date)].sort_values(['observation_date','known_by']).drop_duplicates('observation_date',keep='last')
                previous=previous[previous.numeric_value.notna()]
                if not previous.empty:
                    r=previous.iloc[-1]
                    result['safe_previous_observation']=dict(observation_date=r.observation_date,value=float(r.numeric_value),known_by=r.known_by.isoformat(),available_at=None)
                latest[key]=result
    records=pd.DataFrame(results);records.to_csv(output/'publication_checks.csv',index=False)
    counts=records.groupby(['source','status']).size().unstack(fill_value=0)
    counts.to_csv(output/'publication_summary.csv')
    recent=records[records.model_basis_date>='2015-01-01'].groupby(['source','status']).size().unstack(fill_value=0)
    summary=dict(cutoff_convention='15:30 Asia/Seoul on confirmed daily state date',
        availability_precision='Vintage calendar-date upper bound UTC-12; not an actual release or ingestion timestamp', evidence_limit='ALFRED vintage dates may represent source release, provider release, or first FRED availability; this is source-specific date evidence, not proof of intraday availability or pre-archive history',coverage=coverage,latest=latest,
        status_counts=json.loads(counts.to_json(orient='index')),ecos='API supplies observation day, no historic publication/vintage time; fresh response receipt cannot certify old availability',
        since_2015_status_counts=json.loads(recent.to_json(orient='index')),
        production_approved=False,model_retrained=False,
        sources=['https://fred.stlouisfed.org/docs/api/fred/series_observations.html','https://fred.stlouisfed.org/docs/api/fred/realtime_period.html'])
    (output/'publication_audit.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(dict(latest=latest,counts=summary['status_counts'])))

if __name__=='__main__':main()
