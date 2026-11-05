"""KRX raw-price evidence, independent of model fitting and the operating pipeline."""
import argparse,contextlib,io,importlib.util,json,os,sys,time,threading
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import date,timedelta
import pandas as pd
import requests
from pathlib import Path
from .collect_certification_evidence import credentials,capture,save,OUT

def main():
    p=argparse.ArgumentParser();p.add_argument('--all',action='store_true');p.add_argument('--manifest');p.add_argument('--status-file',default=str(OUT/'raw_collection_status.json'));args=p.parse_args()
    credentials()
    spec=importlib.util.spec_from_file_location('krx_evidence_auth',Path('.venv-krx-batch/Lib/site-packages/pykrx/website/comm/auth.py'))
    auth=importlib.util.module_from_spec(spec);sys.modules[spec.name]=auth;spec.loader.exec_module(auth)
    with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
        session=auth.build_krx_session(os.environ['KRX_ID'],os.environ['KRX_PW'])
    if session is None:
        save(Path(args.status_file),{'status':'authentication_failed'});return
    master=json.loads(Path('data/research/exposure_universe_20261103/official_master_20261030.json').read_text(encoding='utf8'))
    lookup={r['ISU_SRT_CD']:r['ISU_CD'] for r in master}
    assets=json.loads((Path(args.manifest) if args.manifest else Path(__file__).with_name('final_service_manifest.json')).read_text())['supported_assets']
    if not args.all:assets=assets[:1]
    results=[];jobs=[]
    gold=pd.read_parquet('reports/support_expansion_20261104/research_input.parquet')
    first=gold[gold.quality_status.eq('valid')].groupby('asset_id').trading_date.min()
    for asset in assets:
        start=pd.Timestamp(first[asset]).date()
        while start<=date(2026,10,30):
            end=min(start+timedelta(days=729),date(2026,10,30))
            jobs.append((asset,start.strftime('%Y%m%d'),end.strftime('%Y%m%d')))
            start=end+timedelta(days=1)
    lock=threading.Lock();last=[0.];local=threading.local()
    headers=session.get_headers();headers.update({'Referer':'https://data.krx.co.kr/contents/MDC/MDI/outerLoader/index.cmd','X-Requested-With':'XMLHttpRequest'})
    def job(spec):
        asset,start,end=spec
        def fetch():
            if not hasattr(local,'session'):
                local.session=requests.Session();local.session.cookies.update(session.session.cookies)
            with lock:
                time.sleep(max(0,1.05-(time.monotonic()-last[0])));last[0]=time.monotonic()
            r=local.session.post('https://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd',
                headers=headers,data=dict(bld='dbms/MDC/STAT/standard/MDCSTAT01701',
                isuCd=lookup[asset],strtDd=start,endDd=end,adjStkPrc=1,adjBasDd='20261030'),timeout=40)
            payload=r.json()
            if 'output' not in payload:raise ValueError('Missing KRX output')
            return r.status_code,payload
        record=capture(f'krx_raw/{asset}/{start}_{end}','data.krx.co.kr',fetch)
        for attempt in range(2):
            if 'error_type' not in record:break
            time.sleep(3*(attempt+1))
            record=capture(f'krx_raw/{asset}/{start}_{end}','data.krx.co.kr',fetch)
        return dict(asset_id=asset,start=start,end=end,**record)
    with ThreadPoolExecutor(max_workers=4) as pool:
        for result in as_completed([pool.submit(job,j) for j in jobs]):
            results.append(result.result())
            save(Path(args.status_file),dict(status='running',pid=os.getpid(),completed=len(results),total=len(jobs),results=results))
    save(Path(args.status_file),dict(status='complete',completed=len(results),total=len(jobs),results=results))
    print(json.dumps(dict(completed=len(results),failed=sum('error_type' in r for r in results))))

if __name__=='__main__':main()
