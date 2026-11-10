import json
import tempfile
import unittest
from pathlib import Path
import pandas as pd
from sector_reference import read_references, assign_sectors


class SectorReferenceTest(unittest.TestCase):
    def test_dated_mapping_does_not_backfill_or_extend_stale_reference(self):
        with tempfile.TemporaryDirectory() as d:
            obj = {'source':'KRX','bld':'dbms/MDC/STAT/standard/MDCSTAT03901',
                   'query_date':'2026-11-09','retrieved_at':'2026-11-10T06:00:00Z',
                   'rows':[{'ISU_SRT_CD':'005935','MKT_TP_NM':'KOSPI','IDX_IND_NM':'전기·전자'}]}
            p=Path(d)/'snapshot.json';p.write_text(json.dumps(obj),encoding='utf8')
            ref=read_references(d)
            keys=pd.DataFrame({'asset_id':['005935']*4+['999999'],
                               'trading_date':['2000-01-04','2026-11-09','2026-11-10','2026-12-10','2026-11-10']})
            result=assign_sectors(keys,ref).set_index(['trading_date','asset_id'])
            self.assertEqual(result.sector_id.notna().sum(),2)
            self.assertEqual(result.loc[(pd.Timestamp('2026-11-09'),'005935'),'sector_id'],'KRX_KOSPI:전기·전자')
            self.assertFalse(result.loc[(pd.Timestamp('2026-11-09'),'005935'),'point_in_time_known'])
            self.assertTrue(result.loc[(pd.Timestamp('2026-11-10'),'005935'),'point_in_time_known'])
            carried=assign_sectors(keys,ref,max_age_days=None)
            self.assertEqual(carried.sector_id.notna().sum(),3)
            self.assertEqual(carried.loc[carried.trading_date==pd.Timestamp('2026-12-10'),'classification_age_days'].iloc[0],31)
            obj['rows']*=2;p.write_text(json.dumps(obj),encoding='utf8')
            with self.assertRaises(ValueError):read_references(d)


if __name__=='__main__':unittest.main()
