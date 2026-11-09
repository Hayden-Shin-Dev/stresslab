import subprocess,shutil,pathlib,json
p=pathlib.Path('reports/quote_coalesce_20261104');p.mkdir(parents=True,exist_ok=True)
base='/subscriptions/27db5ec6-d206-4028-b5e1-6004dca5eeef/resourceGroups/5dt-final-team3/providers/'
for name,res,metrics,agg in [('pubsub',base+'Microsoft.SignalRService/WebPubSub/wps-whatif-dev',['InboundTraffic','OutboundTraffic','ConnectionOpenCount','ConnectionCloseCount'],'Total'),('eventhub',base+'Microsoft.EventHub/namespaces/evhns-whatif-dev',['IncomingMessages','OutgoingMessages','ThrottledRequests','ServerErrors'],'Total'),('connections',base+'Microsoft.SignalRService/WebPubSub/wps-whatif-dev',['TotalConnectionCount'],'Average')]:
 args=[shutil.which('az'),'monitor','metrics','list','--resource',res,'--metric',*metrics,'--aggregation',agg,'--interval','PT1M','--start-time','2026-11-04T03:50:00Z','--end-time','2026-11-04T05:34:00Z','-o','json','--only-show-errors']
 r=subprocess.run(args,capture_output=True,text=True,encoding='utf8');(p/(name+'_comparison_metrics.json')).write_text(r.stdout,encoding='utf8')
 if r.returncode:print(name,r.stderr[:700]);continue
 for m in json.loads(r.stdout)['value']:
  for series in m['timeseries']:
   data=series['data'];print(m['name']['value'], [(v['timeStamp'],v.get(agg.lower())) for v in data if v['timeStamp'][11:16]>='03:58' and v['timeStamp'][11:16]<='04:06'])

