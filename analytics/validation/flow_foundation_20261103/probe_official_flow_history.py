import contextlib,io,os,json,logging
from pathlib import Path
import requests
from urllib.parse import urlparse
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'reports/flow_foundation_20261103';OUT.mkdir(exist_ok=True)
for filename in ['.env.example','.env']:
 p=ROOT/filename
 if p.exists():
  for line in p.read_text(encoding='utf-8-sig').splitlines():
   if line.lstrip().startswith('#') or '=' not in line:continue
   k,v=line.split('=',1)
   if k.strip() in ['KRX_ID','KRX_PW']:os.environ[k.strip()]=v.strip().strip(chr(34)).strip(chr(39))
original=requests.Session.send
hosts=set()
def checked(s,r,**kw):
 h=urlparse(r.url).hostname or ''
 if not(h=='krx.co.kr' or h.endswith('.krx.co.kr')):raise RuntimeError('NonKRX host blocked')
 hosts.add(h);kw['timeout']=45;return original(s,r,**kw)
requests.Session.send=checked;logging.disable(logging.CRITICAL)
results=[]
with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
 from pykrx.website.comm.auth import get_auth_session
 from pykrx.website.krx.market.ticker import get_stock_ticker_isin
 from pykrx.website.krx.market.core import 투자자별_거래실적_개별종목_일별추이_일반
 assert get_auth_session() is not None
 isin=get_stock_ticker_isin('005930')
 for start,end in [('20000101','20011231'),('20100101','20111231'),('20240101','20251231')]:
  try:
   f=투자자별_거래실적_개별종목_일별추이_일반().fetch(start,end,isin,2,3)
   (OUT/(start+'_'+end+'.json')).write_text(f.to_json(orient='records',force_ascii=False),encoding='utf8')
   results.append(dict(start=start,end=end,rows=len(f),columns=f.columns.tolist(),first=f.TRD_DD.min() if len(f) else None,last=f.TRD_DD.max() if len(f) else None))
  except Exception as e:results.append(dict(start=start,end=end,error=type(e).__name__))
out=dict(asset='005930',source='KRX',probe_only=True,results=results,hosts=sorted(hosts),no_model_validation_claim=True)
(OUT/'probe.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps(out,ensure_ascii=True))
