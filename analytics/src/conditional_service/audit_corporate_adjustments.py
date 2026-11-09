"""Audit adjusted returns against KRX raw reference prices; no inferred repairs."""
import hashlib,json,argparse
from pathlib import Path
import numpy as np
import pandas as pd

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--manifest');parser.add_argument('--status-file',default='data/research/service_certification_20261104/raw_collection_status.json');parser.add_argument('--out',default='reports/service_certification_20261104');args=parser.parse_args()
    root=Path('data/research/service_certification_20261104')
    status=json.loads(Path(args.status_file).read_text(encoding='utf8'))
    assert status['status']=='complete' and status['completed']==status['total']
    assert all(r.get('status')==200 and 'error_type' not in r for r in status['results'])
    supported=json.loads((Path(args.manifest) if args.manifest else Path(__file__).with_name('final_service_manifest.json')).read_text())['supported_assets']
    gold=pd.read_parquet('reports/support_expansion_20261104/research_input.parquet')
    summary=[];events=[];errors=[]
    for asset in supported:
        rows=[]
        for path in sorted((root/'krx_raw'/asset).glob('*.json')):
            if path.name.endswith(('.receipt.json','.failure.json')):continue
            receipt=json.loads(path.with_name(path.stem+'.receipt.json').read_text())
            assert hashlib.sha256(path.read_bytes()).hexdigest()==receipt['sha256']
            rows.extend(json.loads(path.read_text(encoding='utf8'))['output'])
        raw=pd.DataFrame(rows)
        raw['date']=pd.to_datetime(raw.TRD_DD)
        assert not raw.date.duplicated().any()
        for col in ('TDD_CLSPRC','CMPPREVDD_PRC','FLUC_RT','ACC_TRDVOL'):
            raw[col]=pd.to_numeric(raw[col].astype(str).str.replace(',',''),errors='coerce')
        raw=raw.sort_values('date')
        # KRX supplies signed change; cross-check its implied rate before relying on reference.
        raw['reference']=raw.TDD_CLSPRC-raw.CMPPREVDD_PRC
        raw['reference_return']=100*(raw.TDD_CLSPRC/raw.reference-1)
        raw['previous_raw']=raw.TDD_CLSPRC.shift()
        raw['reference_adjusted']=~np.isclose(raw.reference,raw.previous_raw,rtol=0,atol=.01) & raw.previous_raw.notna() & raw.reference.gt(0)
        z=gold[gold.asset_id.eq(asset)].copy();z['date']=pd.to_datetime(z.trading_date)
        q=raw.merge(z[['date','close','quality_status','volume','adjustment_version']],on='date',how='left').sort_values('date')
        q['previous_adjusted']=q.close.shift()
        q['adjusted_return']=100*(q.close/q.previous_adjusted-1)
        q['usable']=q.quality_status.eq('valid') & q.quality_status.shift().eq('valid') & q.volume.gt(0) & q.volume.shift().gt(0) & q.reference.gt(0)
        q['tolerance_pp']=.011+200/q.previous_adjusted
        bad_rate=q.usable & (q.reference_return-q.FLUC_RT).abs().gt(.011)
        bad_adjustment=q.usable & (q.adjusted_return-q.reference_return).abs().gt(q.tolerance_pp)
        missing=int(z[z.quality_status.eq('valid') & ~z.date.isin(raw.date)].shape[0])
        for r in q[q.reference_adjusted].itertuples():
            events.append(dict(asset_id=asset,date=str(r.date.date()),previous_raw_close=float(r.previous_raw),
                official_reference=float(r.reference),raw_close=float(r.TDD_CLSPRC),adjusted_close=float(r.close) if pd.notna(r.close) else None,
                official_reference_return_pct=float(r.reference_return),adjusted_return_pct=float(r.adjusted_return) if pd.notna(r.adjusted_return) else None,
                usable_for_return=bool(r.usable),quality_status=str(r.quality_status),
                event_kind='official_reference_change_type_not_inferred',evidence='KRX raw close minus signed price change'))
        for r in q[bad_rate | bad_adjustment].itertuples():
            errors.append(dict(asset_id=asset,date=str(r.date.date()),reference_return_pct=float(r.reference_return),
                adjusted_return_pct=float(r.adjusted_return),reported_pct=float(r.FLUC_RT),tolerance_pp=float(r.tolerance_pp)))
        summary.append(dict(asset_id=asset,raw_rows=len(raw),first=str(raw.date.min().date()),last=str(raw.date.max().date()),
            checked_return_pairs=int(q.usable.sum()),reference_change_days=int(q.reference_adjusted.sum()),
            valid_gold_dates_missing_in_raw=missing,reference_formula_mismatches=int(bad_rate.sum()),adjustment_mismatches=int(bad_adjustment.sum())))
    passed=not errors and not any(r['valid_gold_dates_missing_in_raw'] or r['checked_return_pairs']<100 for r in summary)
    report=dict(price_adjustment_validation_passed=passed,assets=len(summary),summary=summary,errors=errors,
        official_reference_change_events=events,event_type_ledger_complete=False,
        scope='Adjusted price-return continuity versus official raw reference-price returns, not dividend total return or full corporate disclosure history.',
        model_changed=False,gold_changed=False)
    out=Path(args.out);out.mkdir(exist_ok=True)
    (out/'corporate_adjustment_audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8')
    print(json.dumps(dict(passed=passed,assets=len(summary),checked_pairs=sum(x['checked_return_pairs'] for x in summary),events=len(events),errors=len(errors))))

if __name__=='__main__':main()
