import json,pandas as pd
from pathlib import Path
p=Path('reports/quote_coalesce_20261104');cols={}
for name in ['pubsub','eventhub','connections']:
 for m in json.loads((p/(name+'_comparison_metrics.json')).read_text())['value']:
  for s in m['timeseries']:
   cols[m['name']['value']]=pd.Series({x['timeStamp']:x.get('total',x.get('average')) for x in s['data']})
d=pd.DataFrame(cols);d.index=pd.to_datetime(d.index);d.index=d.index.tz_convert('Asia/Seoul');d.to_csv(p/'comparison_minutes.csv')
for name,a,b in [('before','2026-11-04 14:18','2026-11-04 14:20'),('after','2026-11-04 14:31','2026-11-04 14:33')]:
 q=d.loc[a:b];print(name,q[['InboundTraffic','OutboundTraffic','TotalConnectionCount','IncomingMessages']].to_string());print('sum',q[['InboundTraffic','OutboundTraffic','IncomingMessages']].sum().to_dict())
print('13h zero outbound');q=d.loc['2026-11-04 13:00':'2026-11-04 13:59'];print(q[q.OutboundTraffic==0][['InboundTraffic','OutboundTraffic','TotalConnectionCount','IncomingMessages']].to_string())
