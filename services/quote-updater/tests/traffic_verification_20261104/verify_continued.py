import asyncio,json,time,requests,websockets,statistics
from pathlib import Path
from datetime import datetime,timezone
OUT=Path('reports/quote_coalesce_20261104');OUT.mkdir(parents=True,exist_ok=True);Q='https://func-whatif-dev-h6a0ebd4c6duhzg2.koreacentral-01.azurewebsites.net/api/quotes';M='https://ca-marketstate-whatif-dev.proudfield-489f3ad8.koreacentral.azurecontainerapps.io/market-state'
def now():return datetime.now(timezone.utc).isoformat()
def get(url,method='get'):
 r=getattr(requests,method)(url,timeout=30);r.raise_for_status();return r.json()
async def watch(base,kind):
 token=await asyncio.to_thread(get,base+'/negotiate','post');initial=await asyncio.to_thread(get,base+('/latest' if kind=='quote' else '/current'))
 out={'started':now(),'initial_assets':len(initial.get('quotes',[])) if kind=='quote' else (initial.get('snapshot')or{}).get('valid_asset_count'),'initial_snapshot':(initial.get('snapshot')or{}).get('snapshot_id'),'messages':[]};prices={};changed=set();assets=set();seen=set();duplicates=0
 async with websockets.connect(token['url']) as ws:
  end=time.monotonic()+150
  while time.monotonic()<end:
   try:m=json.loads(await asyncio.wait_for(ws.recv(),timeout=5))
   except asyncio.TimeoutError:continue
   if kind=='quote':
    quotes=m.get('quotes',[]);assert len({q['asset_id'] for q in quotes})==len(quotes)
    for q in quotes:
     a=q['asset_id'];assets.add(a)
     if a in prices and prices[a]!=q['price']:changed.add(a)
     prices[a]=q['price']
     if q['event_id'] in seen:duplicates+=1
     seen.add(q['event_id'])
    out['messages'].append({'at':now(),'published_at':m.get('published_at'),'count':len(quotes),'latest_received':max((q['received_at'] for q in quotes),default=None),'delivery':m.get('delivery')})
   else:
    out['messages'].append({'at':now(),**{k:m.get(k) for k in ['record_type','snapshot_id','as_of','computed_at','quality_status','connection_status','valid_asset_count','expected_asset_count']},'mean_return_5m_pct':m.get('market',{}).get('mean_return_5m_pct')})
 out.update(ended=now(),assets_seen=len(assets),price_changed_assets=sorted(changed),duplicate_events=duplicates)
 if kind=='quote' and len(out['messages'])>1:
  times=[datetime.fromisoformat(x['published_at']).timestamp() for x in out['messages']];out['median_interval']=statistics.median(b-a for a,b in zip(times,times[1:]));out['max_interval']=max(b-a for a,b in zip(times,times[1:]))
 (OUT/('continued_'+kind+'.json')).write_text(json.dumps(out,indent=2));print(kind,{k:v for k,v in out.items() if k!='messages'},'messages',len(out['messages']),flush=True)
async def main():await asyncio.gather(watch(Q,'quote'),watch(M,'market'))
asyncio.run(main())
