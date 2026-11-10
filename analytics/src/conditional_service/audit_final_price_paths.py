"""Read official cached price paths; flag unresolved discontinuities, never repair silently."""
import json
from pathlib import Path
import numpy as np
import pandas as pd

def main():
    manifest=json.loads(Path(__file__).with_name('final_service_manifest.json').read_text())
    gold=pd.read_parquet('reports/support_expansion_20261104/research_input.parquet')
    roots=[Path('data/research')/s/'stocks' for s in
           ['exposure_universe_20261103','sector6_20261103','official20_20261102']]
    summaries=[];exceptions=[]
    for asset in manifest['supported_assets']:
        # Choose one collection/basis per asset; never concatenate adjustment vintages.
        folder=next((root/asset for root in roots if (root/asset).is_dir()),None)
        if folder is None:
            summaries.append(dict(asset_id=asset,source_found=False));continue
        rows=[]
        for path in sorted(folder.glob('*.json')):
            raw=json.loads(path.read_text(encoding='utf8'))
            if isinstance(raw,list):rows.extend(r for r in raw if 'TRD_DD' in r)
        q=pd.DataFrame(rows)
        if q.empty:
            summaries.append(dict(asset_id=asset,source_found=False));continue
        q['date']=pd.to_datetime(q.TRD_DD)
        for col in ('TDD_CLSPRC','FLUC_RT'):
            q[col]=pd.to_numeric(q[col].astype(str).str.replace(',',''),errors='coerce')
        duplicates=int(q.date.duplicated().sum())
        q=q.sort_values('date').drop_duplicates('date',keep='last')
        previous=q.TDD_CLSPRC.shift()
        q['calculated_pct']=(q.TDD_CLSPRC/previous-1)*100
        # Adjusted integer price rounding tolerance used by existing import audit.
        q['difference_pp']=(q.calculated_pct-q.FLUC_RT).abs()
        q['flag']=q.difference_pp.gt(.011+200/previous) & previous.gt(0)
        g=gold[gold.asset_id==asset].copy();g['date']=pd.to_datetime(g.trading_date)
        m=q.merge(g[['date','close','quality_status']],on='date',how='inner')
        mismatch=~np.isclose(m.close,m.TDD_CLSPRC,rtol=0,atol=.001,equal_nan=False)
        for r in m[m.flag | mismatch].itertuples():
            exceptions.append(dict(asset_id=asset,date=str(r.date.date()),raw_close=r.TDD_CLSPRC,
                gold_close=r.close,reported_change_pct=r.FLUC_RT,calculated_change_pct=r.calculated_pct,
                quality_status=r.quality_status,reason='Review adjustment basis, reference-price change or halt; numerical discrepancy is not proof of a corporate event'))
        summaries.append(dict(asset_id=asset,source_found=True,source=str(folder),raw_rows=len(q),
            overlap_rows=len(m),duplicate_dates=duplicates,price_mismatches=int(mismatch.sum()),
            return_discontinuities=int(m.flag.sum()),flagged_but_gold_valid=int((m.flag & m.quality_status.eq('valid')).sum()),
            corporate_action_ledger_verified=False))
    out=Path('reports/service_integration_20261104');out.mkdir(exist_ok=True)
    (out/'price_path_audit.json').write_text(json.dumps(dict(assets=summaries,exceptions=exceptions,
        production_certification=False,automatic_price_repair=False),ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(dict(assets=len(summaries),sources_found=sum(r['source_found'] for r in summaries),
        exceptions=len(exceptions),price_mismatches=sum(r.get('price_mismatches',0) for r in summaries),
        flagged_but_gold_valid=sum(r.get('flagged_but_gold_valid',0) for r in summaries))))

if __name__=='__main__':main()
