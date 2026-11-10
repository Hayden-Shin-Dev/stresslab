"""Official DART annual accounts and current company metadata; secrets never logged."""
import sys,json,time,threading,io,zipfile,os,xml.etree.ElementTree as ET
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,as_completed
import requests
ROOT=Path(os.environ.get('STRESSLAB_AUDIT_ROOT',Path(__file__).resolve().parents[1]));sys.path.insert(0,str(ROOT))
def keys():
    result=dict(os.environ)
    for name in ['.env.example','.env']:
        path=ROOT/name
        if path.exists():
            for line in path.read_text(encoding='utf-8-sig').splitlines():
                if '=' in line and not line.lstrip().startswith('#'):
                    k,v=line.split('=',1)
                    if k.strip()=='DART_API_KEY':result[k.strip()]=v.strip().strip(chr(34)).strip(chr(39))
    return result
def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf8');tmp.replace(path)
OUT=ROOT/'data/research/rich_dart_20261103';STATUS=ROOT/'reports/rich_context_20261103/dart_progress.json'

def main():
    OUT.mkdir(exist_ok=True);assets=json.loads((ROOT/'reports/long_universe_20261103/selected_assets.json').read_text());key=keys()['DART_API_KEY']
    lock=threading.Lock();last=[0.];state=dict(status='running',completed=0,failed=[])
    def get(endpoint,**params):
        for attempt in range(3):
            try:
                with lock:time.sleep(max(0,.45-(time.monotonic()-last[0])));last[0]=time.monotonic()
                r=requests.get('https://opendart.fss.or.kr/api/'+endpoint,params={'crtfc_key':key,**params},timeout=40);r.raise_for_status()
                if endpoint.endswith('.xml'):return r.content
                j=r.json()
                if j.get('status') not in ['000','013']:raise ValueError('provider_status_'+str(j.get('status')))
                return j
            except Exception:
                if attempt==2:raise RuntimeError('DART_request_failed') from None
                time.sleep(3)
    mapping_path=OUT/'company_map.json'
    if mapping_path.exists():mapping=json.loads(mapping_path.read_text())
    else:
        payload=get('corpCode.xml');archive=zipfile.ZipFile(io.BytesIO(payload));tree=ET.fromstring(archive.read(archive.namelist()[0]));mapping={}
        for item in tree.findall('list'):
            stock=(item.findtext('stock_code') or '').strip()
            if stock in assets:mapping[stock]=item.findtext('corp_code')
        write(mapping_path,mapping)
    state['unmapped']=[a for a in assets if a not in mapping];jobs=[]
    for a,corp in mapping.items():
        p=OUT/a/'company_current.json'
        if not p.exists():jobs.append((a,'current',corp,p))
        for year in range(2015,2026):
            p=OUT/a/f'{year}.json';old=ROOT/'data/research/dart_ml_history'/a/f'{year}.json'
            if not p.exists() and old.exists():write(p,json.loads(old.read_text(encoding='utf8')))
            if not p.exists():jobs.append((a,str(year),corp,p))
    state['total']=len(jobs);write(STATUS,state)
    def fetch(job):
        a,year,corp,p=job
        try:
            j=get('company.json',corp_code=corp) if year=='current' else get('fnlttSinglAcnt.json',corp_code=corp,bsns_year=year,reprt_code='11011')
            write(p,j);return None
        except Exception:return dict(asset=a,year=year,error='request_failed')
    with ThreadPoolExecutor(max_workers=3) as pool:
        for fut in as_completed([pool.submit(fetch,j) for j in jobs]):
            error=fut.result();state['completed']+=1
            if error:state['failed'].append(error)
            write(STATUS,state)
    state['status']='complete' if not state['failed'] else 'partial';write(STATUS,state)

if __name__=='__main__':main()
