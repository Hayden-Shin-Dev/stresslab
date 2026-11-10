"""KRX-only website history collector. Run in the isolated .venv-krx-batch.
The stock_api adjusted-price convenience function is deliberately NOT used:
pykrx 1.2.8 routes it to Naver. Network allowlisting also blocks that fallback.
"""
import contextlib,io,json,os,sys,time,hashlib,logging,threading
from concurrent.futures import ThreadPoolExecutor,as_completed
from pathlib import Path
from urllib.parse import urlparse
import requests,pandas as pd
ROOT=Path(__file__).resolve().parents[1]
DEST=ROOT/'data/research/sector6_20261103'
def write(p,obj):
    p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_suffix('.tmp')
    tmp.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf8');tmp.replace(p)
def main():
    DEST.mkdir(parents=True,exist_ok=True)
    import msvcrt
    lock=open(DEST/'collection.lock','a+b');lock.write(b'0');lock.flush();lock.seek(0)
    try:msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
    except OSError:return
    for filename in ['.env.example','.env']:
        path=ROOT/filename
        if not path.exists():continue
        for line in path.read_text(encoding='utf-8-sig').splitlines():
            if line.lstrip().startswith('#') or '=' not in line:continue
            k,v=line.split('=',1)
            if k.strip() in ['KRX_ID','KRX_PW']:os.environ[k.strip()]=v.strip().strip('"').strip("'")
    if not all(os.environ.get(k) for k in ['KRX_ID','KRX_PW']):raise RuntimeError('KRX_login_not_configured')
    universe={'universe_id':'sector6_research_20261103','assets':[{'asset_id':a,'name':n} for a,n in [('003490','대한항공'),('020560','아시아나항공'),('010950','S-Oil'),('096770','SK이노베이션'),('051910','LG화학'),('011170','롯데케미칼')]]}
    write(DEST/'universe.json',universe)
    state={'status':'running','pid':os.getpid(),'universe_id':universe['universe_id'],'assets':{},'network_hosts':[],'naver_allowed':False}
    def status():
        state['updated_at']=pd.Timestamp.now(tz='UTC').isoformat();write(DEST/'progress.json',state)
    original=requests.Session.send;rate_lock=threading.Lock();last_send=[0.0]
    def checked_send(session,request,**kwargs):
        host=urlparse(request.url).hostname or ''
        if not (host=='krx.co.kr' or host.endswith('.krx.co.kr')):raise RuntimeError('Non_KRX_network_blocked')
        state['network_hosts']=sorted(set(state['network_hosts']+[host]))
        with rate_lock:
            time.sleep(max(0,1.05-(time.monotonic()-last_send[0])))
            last_send[0]=time.monotonic()
        kwargs.setdefault('timeout',45)
        if kwargs.get('timeout') is None:kwargs['timeout']=45
        return original(session,request,**kwargs)
    requests.Session.send=checked_send;logging.disable(logging.CRITICAL)
    try:
        # Auth library prints the ID by default; discard all library console output.
        with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
            from pykrx.website.krx.market.core import 개별종목시세,전종목시세,전종목기본정보,개별지수시세
            from pykrx.website.krx.market.ticker import get_stock_ticker_isin
            from pykrx.website.comm.auth import get_auth_session
            auth=get_auth_session()
            if auth is None:raise RuntimeError('KRX_login_failed')
            probe=전종목시세().fetch('20000104','STK')
            if probe.empty:raise RuntimeError('KRX_2000_probe_empty')
            write(DEST/'cross_sections/20000104.json',probe.to_dict('records'))
            state['login_verified_by_data']=True;state['pre2010_probe_rows']=len(probe);status()
            # Use a single fixed adjustment date across every chunk.
            jobs=[]
            for asset in universe['assets']:
                symbol=asset['asset_id'];isin=get_stock_ticker_isin(symbol)
                if not isin:raise RuntimeError('ISIN_missing_'+symbol)
                total=0;completed=0
                for year in range(2000,2027,2):
                    start=f'{year}0101';end=f'{year+1}1231' if year<2026 else '20261030'
                    p=DEST/'stocks'/symbol/(start+'_'+end+'.json')
                    if p.exists():
                        total+=len(json.loads(p.read_text(encoding='utf8')));completed+=1
                    else:jobs.append((symbol,isin,start,end,p))
                state['assets'][symbol]={'rows':total,'completed_chunks':completed,'status':'complete' if completed==14 else 'collecting'};status()
            def fetch_chunk(job):
                symbol,isin,start,end,p=job
                for attempt in range(3):
                    try:
                        payload=개별종목시세().read(isuCd=isin,strtDd=start,endDd=end,adjStkPrc=2,adjBasDd='20261030')
                        if 'output' not in payload:raise RuntimeError('KRX_response_block_missing')
                        rows=payload['output']
                        if any(not(start<=r['TRD_DD'].replace('/','')<=end) for r in rows):raise RuntimeError('KRX_wrong_period')
                        write(p,rows);return symbol,end,len(rows)
                    except Exception:
                        if attempt==2:raise
                        time.sleep(5)
            # Three outstanding reads, globally paced at <= one request/second.
            with ThreadPoolExecutor(max_workers=3) as pool:
                for future in as_completed([pool.submit(fetch_chunk,j) for j in jobs]):
                    symbol,end,n=future.result();item=state['assets'][symbol]
                    item['rows']+=n;item['completed_chunks']+=1;item['last_requested_end']=end
                    if item['completed_chunks']==14:item['status']='complete'
                    status()
        state['status']='complete';status()
    except Exception as exc:
        state['status']='failed';state['error_type']=type(exc).__name__
        # Exception text can contain credential-bearing request data; never persist it.
        status()
    print(json.dumps(state,ensure_ascii=True))
if __name__=='__main__':main()
