"""Synthetic fixtures only. Does not contact Azure or Kiwoom."""
import importlib.util,json,unittest
from pathlib import Path
from datetime import datetime,timezone
from jsonschema import Draft202012Validator,FormatChecker
ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('collector',ROOT/'ingestion/kiwoom/collector.py')
collector=importlib.util.module_from_spec(spec);spec.loader.exec_module(collector)
class Pilot(unittest.TestCase):
 def test_contract_and_conservative_metadata(self):
  row={'type':'0B','item':'005930','values':{'10':'-71000','13':'1000','15':'-10','20':'100000'}}
  at=datetime(2026,10,30,1,0,1,tzinfo=timezone.utc)
  event=collector.normalize(row,at)
  schema=json.loads((ROOT/'contracts/realtime/schema.json').read_text(encoding='utf8'))
  Draft202012Validator(schema,format_checker=FormatChecker()).validate(event)
  self.assertEqual(event['price'],71000);self.assertEqual(event['trade_volume'],10)
  self.assertEqual(event['event_time'],'2026-10-30T01:00:00Z')
  self.assertTrue(event['date_inferred']);self.assertEqual(event['venue'],'UNKNOWN');self.assertEqual(event['session'],'unknown')
  row['values']['20']='235959';self.assertIsNone(collector.normalize(row,at)['event_time'])
  row['values']['10']='NaN';self.assertIsNone(collector.normalize(row,at))
 def test_non_trade_is_not_forwarded(self):
  self.assertIsNone(collector.normalize({'type':'PING'},datetime.now(timezone.utc)))
if __name__=='__main__':unittest.main()
