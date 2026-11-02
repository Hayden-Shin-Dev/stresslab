"""Two-stock Azure connectivity pilot. No account or order endpoints."""
import asyncio,json,os,uuid,sqlite3,math,ipaddress
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
 if len(symbol)!=6 or not symbol.isdigit():return None
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
 return {'record_type':'quote_event','schema_version':'1.0','event_id':str(uuid.uuid4()),'asset_id':symbol,'instrument_kind':'stock','source':'kiwoom_websocket','event_time':event,'received_at':stamp(received),'price':price,'cumulative_volume':number(v.get('13')),'trade_volume':number(v.get('15')),'venue':'UNKNOWN','session':'unknown','date_inferred':True,'is_mock':False}

async def check_ip():
 async with httpx.AsyncClient(timeout=15) as c:
  r=await c.get('https://api.ipify.org?format=json');r.raise_for_status();ip=str(ipaddress.ip_address(r.json()['ip']))
 log('egress_ip_observed',ip=ip,note='IP to this diagnostic endpoint; not a fixed-IP guarantee')
 return ip

async def receive(db,validator,symbols):
 delay=5
 while True:
  try:
   await check_ip()
   async with httpx.AsyncClient(timeout=20) as c:
    r=await c.post('https://api.kiwoom.com/oauth2/token',json={'grant_type':'client_credentials','appkey':os.environ['KIWOOM_APP_KEY'],'secretkey':os.environ['KIWOOM_SECRET_KEY']})
    r.raise_for_status();d=r.json()
   if not d.get('token'):
    log('kiwoom_auth_failed',provider_code=str(d.get('return_code','unknown')));await asyncio.sleep(60);continue
   log('kiwoom_token_ok')
   expiry=now()+timedelta(minutes=30)
   try:expiry=datetime.strptime(d['expires_dt'],'%Y%m%d%H%M%S').replace(tzinfo=KST).astimezone(timezone.utc)-timedelta(minutes=2)
   except (KeyError,ValueError):pass
   async with websockets.connect('wss://api.kiwoom.com:10000/api/dostk/websocket',ping_interval=None,open_timeout=20,close_timeout=5) as ws:
    await ws.send(json.dumps({'trnm':'LOGIN','token':d['token']}))
    while now()<expiry:
     message=json.loads(await asyncio.wait_for(ws.recv(),90));tr=message.get('trnm')
     if tr=='PING':await ws.send(json.dumps(message))
     elif tr=='LOGIN':
      if str(message.get('return_code'))!='0':raise RuntimeError('login_rejected')
      log('kiwoom_login_ok')
      await ws.send(json.dumps({'trnm':'REG','grp_no':'1','refresh':'1','data':[{'item':symbols,'type':['0B']}]}))
     elif tr=='REG':
      if str(message.get('return_code'))!='0':raise RuntimeError('registration_rejected')
      log('kiwoom_subscribed',symbols=symbols);delay=5
     elif tr=='REAL':
      received=now()
      for row in message.get('data',[]):
       if row.get('item') not in symbols:continue
       event=normalize(row,received)
       if event:
        validator.validate(event)
        db.execute('INSERT INTO outbox VALUES(?,?,?)',(event['event_id'],json.dumps(event),json.dumps(row)));db.commit()
  except asyncio.CancelledError:raise
  except Exception as exc:log('kiwoom_reconnecting',error_type=type(exc).__name__)
  await asyncio.sleep(delay);delay=min(delay*2,60)

async def publish(db):
 from azure.identity.aio import ManagedIdentityCredential
 from azure.eventhub.aio import EventHubProducerClient
 from azure.eventhub import EventData,TransportType
 credential=ManagedIdentityCredential(client_id=os.environ['AZURE_CLIENT_ID'])
 producer=EventHubProducerClient(fully_qualified_namespace=os.environ['EVENTHUB_NAMESPACE'],eventhub_name=os.environ['EVENTHUB_NAME'],credential=credential,transport_type=TransportType.AmqpOverWebsocket)
 sent=0
 async with credential,producer:
  while True:
   rows=db.execute('SELECT id,payload FROM outbox ORDER BY rowid LIMIT 100').fetchall()
   if not rows:await asyncio.sleep(1);continue
   try:
    for event_id,payload in rows:
     batch=await producer.create_batch(partition_key=json.loads(payload)['asset_id']);batch.add(EventData(payload))
     await producer.send_batch(batch)
     db.execute('DELETE FROM outbox WHERE id=?',(event_id,));db.commit();sent+=1
    log('eventhub_sent',total=sent,pending=db.execute('SELECT COUNT(*) FROM outbox').fetchone()[0])
   except asyncio.CancelledError:raise
   except Exception as exc:
    log('eventhub_retry',error_type=type(exc).__name__);await asyncio.sleep(10)

async def main():
 if os.getenv('MODE','probe')=='probe':
  while True:
   try:await check_ip()
   except Exception as exc:log('egress_probe_failed',error_type=type(exc).__name__)
   await asyncio.sleep(60)
 required=['KIWOOM_APP_KEY','KIWOOM_SECRET_KEY','AZURE_CLIENT_ID','EVENTHUB_NAMESPACE','EVENTHUB_NAME']
 missing=[k for k in required if not os.getenv(k)]
 if missing:raise ValueError('missing configuration: '+','.join(missing))
 symbols=os.getenv('SYMBOLS','005930,005380').split(',')
 if not 1<=len(symbols)<=2 or len(set(symbols))!=len(symbols) or any(len(x)!=6 or not x.isdigit() for x in symbols):raise ValueError('pilot requires 1 or 2 six-digit stock codes')
 schema=json.loads(Path('/app/schema.json').read_text());validator=Draft202012Validator(schema,format_checker=FormatChecker())
 db=sqlite3.connect(os.getenv('OUTBOX_PATH','/tmp/kiwoom-outbox.sqlite'))
 db.execute('CREATE TABLE IF NOT EXISTS outbox(id TEXT PRIMARY KEY,payload TEXT NOT NULL,raw TEXT NOT NULL)');db.commit()
 log('pilot_started',durable_across_replica_replacement=False,venue_session_verified=False)
 await asyncio.gather(receive(db,validator,symbols),publish(db))
if __name__=='__main__':asyncio.run(main())
