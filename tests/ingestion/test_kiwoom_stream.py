import asyncio,json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from datetime import datetime,timezone
from test_kiwoom_pilot import collector

class CollectorChecks(unittest.TestCase):
 def test_universe_and_provider_limit(self):
  with patch.dict(os.environ,{'SYMBOLS':''}):
   m,s=collector.load_universe()
  self.assertEqual(len(s),20);self.assertFalse(m['full_kospi']);self.assertFalse(m['official_kospi200'])
  with patch.dict(os.environ,{'SYMBOLS':','.join(str(x).zfill(6) for x in range(201))}):
   with self.assertRaises(ValueError):collector.load_universe()
 def test_provider_fields_and_alphanumeric_code(self):
  row={'type':'0B','item':'00088K','values':{'10':'1000','20':'100000','9081':'KRX','290':'2'}}
  event=collector.normalize(row,datetime(2026,11,2,1,0,1,tzinfo=timezone.utc))
  self.assertEqual(event['venue'],'KRX');self.assertEqual(event['session'],'regular');self.assertTrue(event['date_inferred'])
  row['values']['9081']='unverified'
  self.assertEqual(collector.normalize(row,datetime(2026,11,2,1,0,1,tzinfo=timezone.utc))['session'],'unknown')
 def test_pending_survives_process_reopen(self):
  with tempfile.TemporaryDirectory() as d:
   path=str(Path(d)/'outbox.sqlite');db=collector.open_outbox(path)
   db.execute('INSERT INTO outbox VALUES(?,?,?)',('same-id','{}','{}'));db.commit();db.close()
   db=collector.open_outbox(path);self.assertEqual(db.execute('SELECT id FROM outbox').fetchone()[0],'same-id');db.close()

class RetryChecks(unittest.IsolatedAsyncioTestCase):
 async def test_send_failure_preserves_ids_and_partition_key(self):
  stop=asyncio.Event();calls=[]
  class Context:
   def __init__(self,*a,**kw):pass
   async def __aenter__(self):return self
   async def __aexit__(self,*args):pass
  class Batch:
   def __init__(self,key):self.key=key;self.rows=[]
   def add(self,event):self.rows.append(json.loads(event.body_as_str()))
  class Producer(Context):
   async def create_batch(self,partition_key):return Batch(partition_key)
   async def send_batch(self,batch):
    calls.append((batch.key,batch.rows))
    if len(calls)==1:raise OSError('simulated_send_failure')
    stop.set()
  with tempfile.TemporaryDirectory() as d:
   db=collector.open_outbox(str(Path(d)/'o.sqlite'))
   db.execute('INSERT INTO outbox VALUES(?,?,?)',('stable',json.dumps({'event_id':'stable','asset_id':'005930'}),'{}'));db.commit()
   stats={'universe_id':'test','sent':0,'send_failures':0}
   env={'AZURE_CLIENT_ID':'test','EVENTHUB_NAMESPACE':'test','EVENTHUB_NAME':'test'}
   with patch.dict(os.environ,env),patch('azure.identity.aio.ManagedIdentityCredential',Context),patch('azure.eventhub.aio.EventHubProducerClient',Producer):
    await asyncio.wait_for(collector.publish(db,stats,stop),10)
   self.assertEqual(calls[0],calls[1]);self.assertEqual(calls[1][0],'005930')
   self.assertEqual(stats['sent'],1);self.assertEqual(stats['send_failures'],1)
   self.assertEqual(db.execute('SELECT COUNT(*) FROM outbox').fetchone()[0],0);db.close()
if __name__=='__main__':unittest.main()
