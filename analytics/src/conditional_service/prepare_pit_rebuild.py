"""Prepare point-in-time inputs without altering Gold or tuning models."""
import hashlib,json,re
from pathlib import Path
import numpy as np,pandas as pd
from .core import features,STATE,ASSET,SHOCKS
from .audit_publication_vintages import vintages,MAPPING
OUT=Path('reports/pit_rebuild_20261105')
GOLD=Path('reports/support_expansion_20261104/research_input.parquet')

def audit_index(g):
    rows=[];sources=[]
    for path in sorted(Path('data/research/official20_20261102/index').glob('*.json')):
        raw=json.loads(path.read_text(encoding='utf8'))
        if not isinstance(raw,list):continue
        rows.extend(dict(date=pd.Timestamp(r['TRD_DD']),value=float(r['CLSPRC_IDX'].replace(',',''))) for r in raw)
        sources.append(dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    official=pd.DataFrame(rows).set_index('date').value
    assert official.index.is_unique
    market=g.drop_duplicates('trading_date').set_index('trading_date').kospi_close
    for day in market.index.difference(official.index):
        path=Path('data/research/api_history_bridge/20261001_20261030_fbf9659cefe3/krx_index')/(day.strftime('%Y%m%d')+'.json')
        raw=json.loads(path.read_text(encoding='utf8'))
        chosen=[r for r in raw['rows'] if r['IDX_NM']=='코스피']
        assert len(chosen)==1 and chosen[0]['BAS_DD']==day.strftime('%Y%m%d')
        official.loc[day]=float(chosen[0]['CLSPRC_IDX'].replace(',',''))
        sources.append(dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    np.testing.assert_allclose(market,official.reindex(market.index),rtol=0,atol=.000001)
    return dict(passed=True,checked_dates=len(market),source_files=sources)

def dated_curve(records,days,name):
    records=sorted(records,key=lambda r:(r['known_by'],r['observation_date']))
    cur=0;observations={};rows=[]
    for day in days:
        cutoff=pd.Timestamp(day,tz='Asia/Seoul')+pd.Timedelta(hours=15,minutes=30)
        while cur<len(records) and records[cur]['known_by']<=cutoff:
            r=records[cur];observations[r['observation_date']]=r;cur+=1
        nearby=[observations.get(day-pd.Timedelta(days=lag)) for lag in range(11)]
        eligible=[r for r in nearby if r is not None and pd.notna(r['value'])]
        r=max(eligible,key=lambda x:x['observation_date']) if eligible else None
        rows.append(dict(date=day,source=name,value=r['value'] if r else np.nan,
            observation_date=r['observation_date'] if r else pd.NaT,known_by=r['known_by'] if r else pd.NaT,
            source_ref=r['source_ref'] if r else None,verified=r is not None))
    return pd.DataFrame(rows)

def main():
    progress=json.loads(Path('data/research/pit_rebuild_20261105/bok/progress.json').read_text())
    assert progress['stage']=='complete' and progress['completed']==progress['total'],'Publication collection is unfinished'
    protocol=json.loads((OUT/'locked_protocol.json').read_text());assets=protocol['supported_assets']
    assert hashlib.sha256(GOLD.read_bytes()).hexdigest()==protocol['source_policy']['gold_input_sha256'],'Source Gold changed after protocol lock'
    g=pd.read_parquet(GOLD);g=g[g.asset_id.isin(assets)].copy();g.trading_date=pd.to_datetime(g.trading_date)
    index_audit=audit_index(g)
    (OUT/'market_index_audit.json').write_text(json.dumps(index_audit,indent=2),encoding='utf8')
    days=list(pd.DatetimeIndex(sorted(g.trading_date.unique())));curves=[];labels={};receipts=[]
    for name,series in MAPPING.items():
        v=vintages(series);records=[]
        for r in v.itertuples():
            records.append(dict(observation_date=pd.Timestamp(r.observation_date),known_by=pd.Timestamp(r.known_by),value=r.numeric_value,source_ref=r.source_file))
        curve=dated_curve(records,days,name);curves.append(curve)
        # Preserve the existing shift(-5) definition on corrected as-of daily levels.
        # Never use a US same-calendar-day close unavailable at the KRX cutoff.
        labels[name]=curve.rename(columns={'value':'numeric_value','observation_date':'observed'})
    evidence=json.loads(Path('data/research/pit_rebuild_20261105/bok/evidence.json').read_text(encoding='utf8'))
    assert len(evidence)==progress['total']
    api=json.loads(Path('data/research/service_certification_20261104/ecos/full_2000_20261030.json').read_text(encoding='utf8'))['StatisticSearch']
    assert len(api['row'])==int(api['list_total_count'])
    ecos={pd.Timestamp(r['TIME']):float(r['DATA_VALUE']) for r in api['row']}
    records=[];excluded=[]
    for r in evidence:
        if r['status']!='verified_dated_value':excluded.append(dict(id=r['id'],reason=r['status']));continue
        raw=Path('data/research/pit_rebuild_20261105/bok/documents')/(r['id']+'.html')
        assert hashlib.sha256(raw.read_bytes()).hexdigest()==r['sha256']
        registered=re.search(r'<dt[^>]*>등록일</dt>\s*<dd class="date">(\d{4}\.\d{2}\.\d{2})</dd>',raw.read_text(encoding='utf8'))
        assert registered and registered.group(1).replace('.','-')==r['publication_date'],'Official registration date mismatch'
        day=pd.Timestamp(r['observation_date']);value=r['value']
        if day not in ecos or not np.isclose(value,ecos[day],atol=.000001):
            excluded.append(dict(id=r['id'],reason='official_document_ecos_value_difference',date=str(day.date()),document=value,ecos=ecos.get(day)));continue
        records.append(dict(observation_date=day,known_by=pd.Timestamp(r['known_by']),value=value,source_ref=r['url']))
    assert records,'No certified ECOS observations'
    curves.append(dated_curve(records,days,'korea_3y'))
    provenance=pd.concat(curves,ignore_index=True);provenance.to_parquet(OUT/'observation_provenance.parquet',index=False)
    for name in [*MAPPING,'korea_3y']:
        curve=provenance[provenance.source.eq(name)].set_index('date')
        g[name]=g.trading_date.map(curve.value)
        g[name+'_observation_date']=g.trading_date.map(curve.observation_date)
        # Date upper bounds stay in provenance, not invented exact publication timestamps.
    g['dataset_version']='pit-corrected-local-20261105'
    g.to_parquet(OUT/'corrected_daily_input.parquet',index=False)
    f=features(g)
    # Both endpoints of lagged macro features must have certified provenance.
    # Missing intermediate observations are not silently forward-filled by features().
    assert f[STATE+ASSET+['scale']].notna().all().all()
    calendar=pd.DataFrame({'date':days});calendar['end_date']=calendar.date.shift(-5)
    cutoffs=[]
    for name,shock in zip(MAPPING,SHOCKS):
        z=labels[name];start=z.numeric_value;end=start.shift(-5)
        if shock in ['fx_pct','wti_pct']:values=((end/start-1)*100).where(start.gt(0)&end.gt(0))
        elif shock=='us_rate_bp':values=(end-start)*100
        else:values=end-start
        calendar[shock]=values
        calendar[name+'_start_observation_date']=z.observed
        calendar[name+'_end_observation_date']=z.observed.shift(-5)
        stamps=pd.concat([pd.to_datetime(z.known_by,utc=True),pd.to_datetime(z.known_by.shift(-5),utc=True)],axis=1)
        cutoffs.append(stamps.max(axis=1))
    calendar['label_known_by']=pd.concat(cutoffs,axis=1).max(axis=1)
    calendar.to_parquet(OUT/'shock_observation_windows.parquet',index=False)
    for shock in SHOCKS:
        expected=f.date.map(calendar.set_index('date')[shock])
        np.testing.assert_allclose(f[shock],expected,equal_nan=True)
    f=f.drop(columns=SHOCKS).merge(calendar[['date',*SHOCKS,'label_known_by']],on='date',how='left',validate='many_to_one')
    f.to_parquet(OUT/'corrected_features.parquet',index=False)
    good=provenance[provenance.verified]
    assert (pd.to_datetime(good.known_by,utc=True)<=pd.to_datetime(good.date,utc=True)+pd.Timedelta(hours=6,minutes=30)).all()
    complete=f.dropna(subset=SHOCKS+['target','end_date','label_known_by'])
    audit=dict(gold_sha256=hashlib.sha256(GOLD.read_bytes()).hexdigest(),gold_modified=False,verified_ecos_documents=len(records),excluded_ecos_documents=excluded,
        availability_policy='Official vintage/date bounds; 10-calendar-day maximum observation age; no synthetic exact timestamp',
        state_cutoff='15:30 Asia/Seoul of confirmed daily state date',label_definition='Existing five-KRX-session change in as-of daily macro levels; source observation dates may precede each cutoff and are recorded separately. No assertion of synchronous US and KRX closing times.',
        earliest_model_date=str(complete.date.min()),latest_model_date=str(complete.date.max()),training_candidate_rows=len(complete),assets=complete.asset.nunique(),
        daily_coverage={s:dict(verified=int(z.verified.sum()),excluded=int((~z.verified).sum())) for s,z in provenance.groupby('source')},
        retained_snapshot_dates=sorted(str(x.date()) for x in f.groupby('date').filter(lambda z:len(set(assets)-set(z.asset))==0).date.drop_duplicates().tail(3)))
    (OUT/'data_correction_audit.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({k:v for k,v in audit.items() if k not in ['excluded_ecos_documents','daily_coverage']}))
if __name__=='__main__':main()
