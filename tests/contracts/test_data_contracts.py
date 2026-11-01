"""Contract checks only. Synthetic fixtures never go to operational data."""
import copy,json,unittest
from pathlib import Path
from jsonschema import Draft202012Validator,FormatChecker,ValidationError
ROOT=Path(__file__).resolve().parents[2]
def load(area,name):return json.loads((ROOT/'contracts'/area/name).read_text(encoding='utf8'))
def validator(area):return Draft202012Validator(load(area,'schema.json'),format_checker=FormatChecker())
class Contracts(unittest.TestCase):
    def test_daily_example_and_keys(self):
        rows=load('daily','mock.json');Draft202012Validator.check_schema(load('daily','schema.json'));validator('daily').validate(rows)
        self.assertEqual(len({(r['dataset_version'],r['trading_date'],r['asset_id']) for r in rows}),len(rows))
        self.assertTrue(all(r['is_mock'] for r in rows))
        for day in {r['trading_date'] for r in rows}:
            same=[r for r in rows if r['trading_date']==day]
            for field in ['kospi_close','usdkrw','us_treasury_10y','wti','vix']:self.assertEqual(len({r[field] for r in same}),1)
    def test_daily_rejects_numeric_codes_and_invalid_date(self):
        for field,value in [('asset_id',5930),('trading_date','2026-02-30')]:
            rows=load('daily','mock.json');rows[0][field]=value
            with self.assertRaises(ValidationError):validator('daily').validate(rows)
    def test_realtime_example_counts_and_timestamps(self):
        examples=load('realtime','mock.json');Draft202012Validator.check_schema(load('realtime','schema.json'))
        for row in examples:validator('realtime').validate(row);self.assertTrue(row['is_mock'])
        s=examples[1];self.assertLessEqual(s['declining_asset_count'],s['valid_asset_count']);self.assertLessEqual(s['valid_asset_count'],s['expected_asset_count'])
        self.assertEqual(s['declining_ratio'],s['declining_asset_count']/s['valid_asset_count'])
        self.assertLessEqual(s['last_event_time'],s['as_of']);self.assertLessEqual(s['as_of'],s['computed_at'])
        for row in s['sectors']:self.assertEqual(row['declining_ratio'],row['declining_asset_count']/row['valid_asset_count'])
    def test_market_state_v2_remains_separate_from_daily_ml(self):
        row=next(x for x in load('realtime','mock.json') if x['record_type']=='market_state_snapshot')
        validator('realtime').validate(row)
        self.assertFalse(row['applied_to_daily_ml'])
        self.assertEqual(len(row['assets']),row['expected_asset_count'])
        for asset in row['assets']:
            self.assertLessEqual(asset['minutes_observed'],asset['minutes_expected'])
        row['applied_to_daily_ml']=True
        with self.assertRaises(ValidationError):validator('realtime').validate(row)
    def test_rest_is_not_a_trade_and_times_require_utc(self):
        q=load('realtime','mock.json')[0];q['source']='kiwoom_rest'
        with self.assertRaises(ValidationError):validator('realtime').validate(q)
        q['trade_volume']=None;validator('realtime').validate(q)
        q['received_at']='2026-10-30T10:00:01+09:00'
        with self.assertRaises(ValidationError):validator('realtime').validate(q)
if __name__=='__main__':unittest.main()
