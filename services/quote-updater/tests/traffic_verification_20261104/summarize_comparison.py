import json,pandas as pd
from pathlib import Path
p=Path('reports/quote_coalesce_20261104');d=pd.read_csv(p/'comparison_minutes.csv',index_col=0)
b=d.loc['2026-11-04 14:18:00+09:00':'2026-11-04 14:20:00+09:00'];a=d.loc['2026-11-04 14:31:00+09:00':'2026-11-04 14:33:00+09:00']
out={'date':'2026-11-04','timezone':'Asia/Seoul','before':'14:18:00 <= t < 14:21:00','after':'14:31:00 <= t < 14:34:00','duration_seconds':180,'metrics':{}}
for k in ['InboundTraffic','OutboundTraffic','IncomingMessages']:
 x=float(b[k].sum());y=float(a[k].sum());out['metrics'][k]={'before':x,'after':y,'reduction_pct':100*(1-y/x)}
out['mean_connections']={'before':float(b.TotalConnectionCount.mean()),'after':float(a.TotalConnectionCount.mean())}
out['inbound_bytes_per_raw_tick']={'before':float(b.InboundTraffic.sum()/b.IncomingMessages.sum()),'after':float(a.InboundTraffic.sum()/a.IncomingMessages.sum())}
out['limitations']='Resource-wide metrics include existing market-state hub; not an isolated randomized comparison. Outbound depends on connections and hub subscriptions, so reduction is not solely code effect. Decimal MB, not MiB. Short intraday observation does not establish200-stock capacity or cost savings.'
out['zero_traffic']={'connections_closed':'13:10 (2 connections)','zero_connections_and_outbound':'13:11 through14:04','resumed':'14:05 connection/traffic;14:06 avg3connections','upstream_continued':True,'closure_reason':'Browser closure vs network interruption not identifiable from aggregate metrics'}
(p/'traffic_comparison.json').write_text(json.dumps(out,indent=2));print(json.dumps(out,indent=2))
