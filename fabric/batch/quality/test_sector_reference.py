import json
import tempfile
import unittest
from pathlib import Path
import pandas as pd
from sector_reference import read_references, assign_sectors, assign_current_sectors


class SectorReferenceTest(unittest.TestCase):
    def test_current_metadata_covers_history_without_claiming_historical_knowledge(self):
        references = pd.DataFrame({'asset_id':['005930','005930'],
                                   'sector_id':['KRX_KOSPI:old','KRX_KOSPI:new'],
                                   'classification_date':pd.to_datetime(['2020-01-02','2026-11-09']),
                                   'retrieved_at':pd.to_datetime(['2026-11-10T00:00:00Z']*2)})
        keys = pd.DataFrame({'asset_id':['005930']*2,'trading_date':['2000-01-04','2026-11-09']})
        result = assign_current_sectors(keys, references)
        self.assertEqual(result.sector_id.tolist(), ['KRX_KOSPI:new']*2)
        self.assertEqual(result.historical_backfill.tolist(), [True,False])
        self.assertFalse(result.point_in_time_known.any())
        with self.assertRaises(ValueError):
            assign_current_sectors(pd.DataFrame({'asset_id':['999999'],'trading_date':['2026-11-09']}),references)

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
