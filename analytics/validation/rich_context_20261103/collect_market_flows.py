import contextlib,io,os,json,logging
from pathlib import Path
import requests
from urllib.parse import urlparse
ROOT=Path(os.environ.get('STRESSLAB_AUDIT_ROOT',Path(__file__).resolve().parents[1]));OUT=ROOT/'data/research/official_flow_20261103/market';OUT.mkdir(parents=True,exist_ok=True)
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
 from pykrx.website.krx.market.core import 투자자별_거래실적_전체시장_일별추이_일반
 assert get_auth_session() is not None
 import time
 for year in range(2000,2027,2):
  start=f"{year}0101";end=f"{year+1}1231" if year<2026 else "20261030";path=OUT/(start+"_"+end+".json")
  if not path.exists():
   for attempt in range(3):
    try:
     time.sleep(1.05)
     f=투자자별_거래실적_전체시장_일별추이_일반().fetch(start,end,"STK","","","",2,3)
     assert all(start<=str(v).replace("/","")<=end for v in f.TRD_DD)
     path.write_text(f.to_json(orient="records",force_ascii=False),encoding="utf8");break
    except Exception:
     if attempt==2:raise RuntimeError("KRX_market_flow_failed") from None
     time.sleep(3)
  results.append({"start":start,"end":end,"rows":len(json.loads(path.read_text(encoding="utf8")))})
(OUT/"manifest.json").write_text(json.dumps({"status":"complete","source":"KRX","market":"STK","etf_etn_elw":False,"results":results},indent=2),encoding="utf8")
