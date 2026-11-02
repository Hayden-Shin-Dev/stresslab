"""Single-session Azure trade collector. No account or order endpoints."""
import asyncio,json,os,uuid,sqlite3,math,ipaddress,re,signal,random
from collections import Counter,defaultdict
from datetime import datetime,timezone,timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
import httpx,websockets
from jsonschema import Draft202012Validator,FormatChecker
KST=ZoneInfo('Asia/Seoul')
def now():return datetime.now(timezone.utc)
def stamp(t):return t.isoformat().replace('+00:00','Z')
def log(status,**fields):print(json.dumps({'at':stamp(now()),'status':status,**fields}),flush=True)
def number(v):
 try:
  n=abs(float(str(v).replace(',','')))
  return n if math.isfinite(n) else None
 except (TypeError,ValueError):return None

def normalize(row,received):
 if row.get('type')!='0B':return None
 symbol=row.get('item','')
 if not re.fullmatch('[0-9A-Z]{6}',symbol):return None
 v=row.get('values',{});price=number(v.get('10'))
 if price is None or price<=0:return None
 event=None
 try:
  clock=str(v['20'])
  if len(clock)!=6:raise ValueError()
  t=datetime.strptime(clock,'%H%M%S').time()
  candidate=datetime.combine(received.astimezone(KST).date(),t,tzinfo=KST)
  if candidate<=received+timedelta(seconds=5):event=stamp(candidate.astimezone(timezone.utc))
 except (KeyError,ValueError):pass
 return {'record_type':'quote_event','schema_version':'1.0','event_id':str(uuid.uuid4()),'asset_id':symbol,'instrument_kind':'stock','source':'kiwoom_websocket','event_time':event,'received_at':stamp(received),'price':price,'cumulative_volume':number(v.get('13')),'trade_volume':number(v.get('15')),'venue':v.get('9081') if v.get('9081') in ('KRX','NXT') else 'UNKNOWN','session':({'1':'afterhours','2':'regular','3':'afterhours'}.get(str(v.get('290')),'unknown') if v.get('9081') in ('KRX','NXT') else 'unknown'),'date_inferred':True,'is_mock':False}

async def check_ip():
 async with httpx.AsyncClient(timeout=15) as c:
  r=await c.get('https://api.ipify.org?format=json');r.raise_for_status();ip=str(ipaddress.ip_address(r.json()['ip']))
 log('egress_ip_observed',ip=ip,note='IP to this diagnostic endpoint; not a fixed-IP guarantee')
 return ip

def load_universe():
 path=Path(os.getenv('UNIVERSE_PATH',str(Path(__file__).parent/'universe.json')))
 manifest=json.loads(path.read_text(encoding='utf8'))
 symbols=os.getenv('SYMBOLS','').split(',') if os.getenv('SYMBOLS','').strip() else [x['asset_id'] for x in manifest['assets']]
 if not 1<=len(symbols)<=200 or len(set(symbols))!=len(symbols):raise ValueError('subscription_count_must_be_1_to_200_unique_stocks')
 if any(not re.fullmatch('[0-9A-Z]{6}',s) for s in symbols):raise ValueError('invalid_stock_code')
 return manifest,symbols

def open_outbox(path):
 db=sqlite3.connect(path)
 db.execute('PRAGMA journal_mode=WAL');db.execute('PRAGMA synchronous=FULL')
 db.execute('CREATE TABLE IF NOT EXISTS outbox(id TEXT PRIMARY KEY,payload TEXT NOT NULL,raw TEXT NOT NULL)');db.commit()
 return db

async def receive(db,validator,symbols,stats,stop):
 delay=5
 while not stop.is_set():
  try:
   # Stop intake during a prolonged Event Hubs outage; report the gap explicitly.
   if db.execute('SELECT COUNT(*) FROM outbox').fetchone()[0]>200000:raise RuntimeError('outbox_capacity_gap')
   async with httpx.AsyncClient(timeout=20) as c:
    r=await c.post('https://api.kiwoom.com/oauth2/token',json={'grant_type':'client_credentials','appkey':os.environ['KIWOOM_APP_KEY'],'secretkey':os.environ['KIWOOM_SECRET_KEY']})
    r.raise_for_status();d=r.json()
   if not d.get('token'):
    log('kiwoom_auth_failed',provider_code=str(d.get('return_code','unknown')))
    raise RuntimeError('token_rejected')
   expiry=now()+timedelta(minutes=30)
   try:expiry=datetime.strptime(d['expires_dt'],'%Y%m%d%H%M%S').replace(tzinfo=KST).astimezone(timezone.utc)-timedelta(minutes=2)
   except (KeyError,ValueError):pass
   async with websockets.connect('wss://api.kiwoom.com:10000/api/dostk/websocket',ping_interval=None,open_timeout=20,close_timeout=5,max_queue=1024) as ws:
    await ws.send(json.dumps({'trnm':'LOGIN','token':d['token']}))
    while now()<expiry and not stop.is_set():
     message=json.loads(await asyncio.wait_for(ws.recv(),90));tr=message.get('trnm')
     if tr=='PING':await ws.send(json.dumps(message))
     elif tr=='LOGIN':
      if str(message.get('return_code'))!='0':
       log('kiwoom_login_rejected',provider_code=str(message.get('return_code')))
       raise RuntimeError('login_rejected')
      stats['connected']=True;log('kiwoom_login_ok')
      await ws.send(json.dumps({'trnm':'REG','grp_no':'1','refresh':'0','data':[{'item':symbols,'type':['0B']}]}))
     elif tr=='REG':
      if str(message.get('return_code'))!='0':raise RuntimeError('registration_rejected')
      stats['registered']=True;delay=5
      log('kiwoom_subscribed',count=len(symbols),universe_id=stats['universe_id'])
     elif tr=='REAL':
      received=now();records=[]
      for row in message.get('data',[]):
       if row.get('item') not in symbols:continue
       event=normalize(row,received)
       if not event:stats['invalid']+=1;continue
       validator.validate(event)
       records.append((event['event_id'],json.dumps(event),json.dumps(row)))
       stats['counts'][event['asset_id']]+=1
       stats['last_event'][event['asset_id']]=event['event_time']
      if records:
       db.executemany('INSERT INTO outbox VALUES(?,?,?)',records);db.commit();stats['received']+=len(records)
       if db.execute('SELECT COUNT(*) FROM outbox').fetchone()[0]>200000:raise RuntimeError('outbox_capacity_gap')
  except asyncio.CancelledError:raise
  except Exception as exc:
   stats['reconnects']+=1
   log('kiwoom_reconnecting',error_type=type(exc).__name__,reason=str(exc) if isinstance(exc,RuntimeError) else 'connection_or_validation_error',gap_start=stamp(now()),tick_gap_recoverable=False)
  finally:stats['connected']=False;stats['registered']=False
  try:await asyncio.wait_for(stop.wait(),delay+random.random())
  except asyncio.TimeoutError:pass
  delay=min(delay*2,60)

async def publish(db,stats,stop):
 from azure.identity.aio import ManagedIdentityCredential
 from azure.eventhub.aio import EventHubProducerClient
 from azure.eventhub import EventData,TransportType
 credential=ManagedIdentityCredential(client_id=os.environ['AZURE_CLIENT_ID'])
 producer=EventHubProducerClient(fully_qualified_namespace=os.environ['EVENTHUB_NAMESPACE'],eventhub_name=os.environ['EVENTHUB_NAME'],credential=credential,transport_type=TransportType.AmqpOverWebsocket)
 semaphore=asyncio.Semaphore(8)
 async def send_symbol(symbol,rows):
  async with semaphore:
   batch=await producer.create_batch(partition_key=symbol);ids=[]
   for event_id,payload,raw in rows:
    event=EventData(payload)
    # Preserve original exchange/session/time fields without changing the JSON body contract.
    event.properties={'provider_raw':raw,'universe_id':stats['universe_id']}
    try:batch.add(event)
    except ValueError:
     if not ids:raise
     break
    ids.append(event_id)
   await producer.send_batch(batch)
   db.executemany('DELETE FROM outbox WHERE id=?',[(i,) for i in ids]);db.commit()
   stats['sent']+=len(ids);stats['last_send_ack']=stamp(now())
 async with credential,producer:
  while not stop.is_set() or db.execute('SELECT COUNT(*) FROM outbox').fetchone()[0]:
   rows=db.execute('SELECT id,payload,raw FROM outbox ORDER BY rowid LIMIT 4000').fetchall()
   if not rows:await asyncio.sleep(.5);continue
   groups=defaultdict(list)
   for row in rows:groups[json.loads(row[1])['asset_id']].append(row)
   results=await asyncio.gather(*(send_symbol(k,v) for k,v in groups.items()),return_exceptions=True)
   failures=[r for r in results if isinstance(r,BaseException)]
   if failures:
    stats['send_failures']+=len(failures)
    log('eventhub_retry',error_type=type(failures[0]).__name__,retained_event_ids=True)
    await asyncio.sleep(5)

async def heartbeat(db,stats,symbols,stop):
 while not stop.is_set():
  fresh=sum(bool(stats['last_event'].get(s)) and (now()-datetime.fromisoformat(stats['last_event'][s].replace('Z','+00:00'))).total_seconds()<=120 for s in symbols)
  status={k:v for k,v in stats.items() if k not in ('counts','last_event')}
  status.update(expected_assets=len(symbols),observed_assets=len(stats['counts']),fresh_event_assets=fresh,pending=db.execute('SELECT COUNT(*) FROM outbox').fetchone()[0],per_asset_received=dict(stats['counts']),last_event_time=dict(stats['last_event']),generated_at=stamp(now()))
  Path('/tmp/collector-status.json').write_text(json.dumps(status))
  log('collector_status',**{k:v for k,v in status.items() if k not in ('per_asset_received','last_event_time')})
  try:await asyncio.wait_for(stop.wait(),30)
  except asyncio.TimeoutError:pass

async def main():
 if os.getenv('MODE','stream')=='probe':
  while True:
   try:await check_ip()
   except Exception as exc:log('egress_probe_failed',error_type=type(exc).__name__)
   await asyncio.sleep(60)
 required=['KIWOOM_APP_KEY','KIWOOM_SECRET_KEY','AZURE_CLIENT_ID','EVENTHUB_NAMESPACE','EVENTHUB_NAME']
 if any(not os.getenv(k) for k in required):raise ValueError('missing_required_configuration')
 manifest,symbols=load_universe()
 schema=json.loads((Path(__file__).parent/'schema.json').read_text())
 validator=Draft202012Validator(schema,format_checker=FormatChecker())
 db=open_outbox(os.getenv('OUTBOX_PATH','/tmp/kiwoom-outbox.sqlite'))
 stats=dict(universe_id=manifest['universe_id'],connected=False,registered=False,received=0,sent=0,invalid=0,reconnects=0,send_failures=0,last_send_ack=None,counts=Counter(),last_event={})
 stop=asyncio.Event();loop=asyncio.get_running_loop()
 for sig in (signal.SIGTERM,signal.SIGINT):loop.add_signal_handler(sig,stop.set)
 log('collector_started',universe_id=manifest['universe_id'],expected_assets=len(symbols),source_date=manifest['source_date'],full_kospi=False,persistent_replica_storage=False)
 receiver=asyncio.create_task(receive(db,validator,symbols,stats,stop))
 sender=asyncio.create_task(publish(db,stats,stop))
 monitor=asyncio.create_task(heartbeat(db,stats,symbols,stop))
 waiter=asyncio.create_task(stop.wait())
 done,_=await asyncio.wait([receiver,sender,monitor,waiter],return_when=asyncio.FIRST_COMPLETED)
 errors=[t.exception() for t in done if t is not waiter and not t.cancelled() and t.exception()]
 stop.set();receiver.cancel();await asyncio.gather(receiver,return_exceptions=True)
 try:await asyncio.wait_for(asyncio.shield(sender),20)
 except asyncio.TimeoutError:
  log('shutdown_pending',count=db.execute('SELECT COUNT(*) FROM outbox').fetchone()[0]);sender.cancel()
 await asyncio.gather(sender,monitor,return_exceptions=True)
 db.close()
 if errors:raise errors[0]
if __name__=='__main__':asyncio.run(main())
