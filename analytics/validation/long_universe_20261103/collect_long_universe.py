"""KRX-only candidate screening history, with cached bulk ISIN mapping."""
import contextlib,io,json,os,time,logging,threading,argparse
from pathlib import Path
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor,as_completed
import requests,pandas as pd
ROOT=Path(os.environ.get('STRESSLAB_AUDIT_ROOT',Path(__file__).resolve().parents[1]));DEST=ROOT/'data/research/exposure_universe_20261103'
def write(p,x):
    p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_suffix('.tmp');tmp.write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding='utf8');tmp.replace(p)
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--selected',action='store_true');args=ap.parse_args()
    for name in ['.env.example','.env']:
        p=ROOT/name
        if p.exists():
            for s in p.read_text(encoding='utf-8-sig').splitlines():
                if '=' in s and not s.lstrip().startswith('#'):
                    k,v=s.split('=',1)
                    if k.strip() in ['KRX_ID','KRX_PW']:os.environ[k.strip()]=v.strip().strip('"').strip("'")
    assert all(os.environ.get(k) for k in ['KRX_ID','KRX_PW'])
    mode='selected' if args.selected else 'screen';state={'status':'running','mode':mode,'pid':os.getpid(),'completed':0,'failed':[],'hosts':[]}
    status=ROOT/'reports/long_universe_20261103/collection_progress.json'
    def save():state['updated_at']=pd.Timestamp.now(tz='UTC').isoformat();write(status,state)
    orig=requests.Session.send;lock=threading.Lock();last=[0.]
    def send(session,req,**kw):
        host=urlparse(req.url).hostname or '';assert host=='krx.co.kr' or host.endswith('.krx.co.kr')
        state['hosts']=sorted(set(state['hosts']+[host]))
        with lock:time.sleep(max(0,1.05-(time.monotonic()-last[0])));last[0]=time.monotonic()
        if kw.get('timeout') is None:kw['timeout']=45
        return orig(session,req,**kw)
    requests.Session.send=send;logging.disable(logging.CRITICAL);save()
    try:
        with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
            from pykrx.website.krx.market.core import 개별종목시세,전종목시세
            from pykrx.website.comm.auth import get_auth_session
            assert get_auth_session() is not None
            master=DEST/'official_master_20261030.json'
            if not master.exists():write(master,전종목시세().fetch('20261030','STK').to_dict('records'))
            lookup={x['ISU_SRT_CD']:x['ISU_CD'] for x in json.loads(master.read_text(encoding='utf8'))}
            u=json.loads((DEST/'universe.json').read_text(encoding='utf8'))['assets']
            known=set()
            for folder in ['official20_20261102','sector6_20261103']:known.update(a['asset_id'] for a in json.loads((ROOT/f'data/research/{folder}/universe.json').read_text(encoding='utf8'))['assets'])
            chosen=set(json.loads((ROOT/'reports/long_universe_20261103/collection_assets.json').read_text(encoding='utf8'))) if args.selected else {a['asset_id'] for a in u}
            jobs=[]
            for a in u:
                symbol=a['asset_id']
                if symbol in known or symbol not in chosen:continue
                if symbol not in lookup:state['failed'].append({'asset':symbol,'reason':'no_official_isin'});continue
                years=list(range(2000,2027,2)) if args.selected else [2016,2018,2020]
                for y in years:
                    start=f'{y}0101';end=f'{y+1}1231' if y<2026 else '20261030';p=DEST/'stocks'/symbol/f'{start}_{end}.json'
                    if not p.exists():jobs.append((symbol,lookup[symbol],start,end,p))
            state['total_requests']=len(jobs);state['candidate_count']=len(chosen);save()
            def fetch(job):
                symbol,isin,start,end,p=job
                for attempt in range(3):
                    try:
                        payload=개별종목시세().read(isuCd=isin,strtDd=start,endDd=end,adjStkPrc=2,adjBasDd='20261030');assert 'output' in payload;rows=payload['output'];assert all(start<=r['TRD_DD'].replace('/','')<=end for r in rows);write(p,rows);return symbol,start,len(rows),None
                    except Exception as e:
                        if attempt==2:return symbol,start,0,type(e).__name__
                        time.sleep(3)
            with ThreadPoolExecutor(max_workers=6) as pool:
                for f in as_completed([pool.submit(fetch,j) for j in jobs]):
                    symbol,start,n,error=f.result();state['completed']+=1;state['last_asset']=symbol;state['last_rows']=n
                    if error:state['failed'].append({'asset':symbol,'start':start,'error_type':error})
                    save()
        state['status']='complete' if not state['failed'] else 'partial';save()
    except Exception as e:state['status']='failed';state['error_type']=type(e).__name__;save()
    print(json.dumps(state,ensure_ascii=True))
if __name__=='__main__':main()
