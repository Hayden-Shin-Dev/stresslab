"""Read-only official source evidence acquisition. Never logs credentials or request URLs."""
import argparse
import contextlib
import hashlib
import io
import json
import logging
import os
from pathlib import Path
import time
from datetime import datetime, timezone
import requests

OUT=Path('data/research/service_certification_20261104')

def save(path, value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf8')

def credentials():
    for name in ('.env.example','.env'):
        path=Path(name)
        if not path.exists():continue
        for line in path.read_text(encoding='utf-8-sig').splitlines():
            # User-authorized .env.example also stores these named credentials in comments.
            k,sep,v=line.lstrip().lstrip('#').strip().partition('=')
            if sep and k.strip() in ('FRED_API_KEY','ECOS_API_KEY','KRX_ID','KRX_PW'):
                os.environ[k.strip()]=v.strip().strip('"').strip("'")

def capture(label, host, fn):
    path=OUT/(label+'.json')
    meta=OUT/(label+'.receipt.json')
    if path.exists() and meta.exists():return json.loads(meta.read_text(encoding='utf8'))
    start=datetime.now(timezone.utc).isoformat()
    try:
        status,payload=fn()
        encoded=json.dumps(payload,ensure_ascii=False)
        for key in ('FRED_API_KEY','ECOS_API_KEY','KRX_ID','KRX_PW'):
            secret=os.environ.get(key)
            if secret:encoded=encoded.replace(secret,'[REDACTED]')
        payload=json.loads(encoded)
        save(path,payload)
        record=dict(source=host,status=status,received_at=datetime.now(timezone.utc).isoformat(),
            started_at=start,sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        if isinstance(payload,dict):
            record['response_keys']=list(payload)
            record['rows']=len(payload.get('observations',payload.get('output',[])))
        save(meta,record);return record
    except Exception as exc:
        record=dict(source=host,error_type=type(exc).__name__,started_at=start)
        save(OUT/(label+'.failure.json'),record);return record

def macro():
    session=requests.Session();summary={}
    def get(url,**kwargs):
        r=session.get(url,timeout=60,**kwargs)
        return r.status_code,r.json()
    for series in ('DEXKOUS','DGS10','DCOILWTICO','VIXCLS'):
        summary[series]=capture('fred/'+series,'api.stlouisfed.org',lambda s=series:get(
            'https://api.stlouisfed.org/fred/series/observations',params=dict(api_key=os.environ['FRED_API_KEY'],
            file_type='json',series_id=s,observation_start='2000-01-01',observation_end='2026-10-30',
            realtime_start='1776-07-04',realtime_end='9999-12-31',output_type=1,limit=100000)))
        if summary[series].get('status')!=200:
            for year in range(2000,2027,5):
                end=f'{year+4}-12-31' if year<2025 else '2026-11-04'
                label=f'fred/{series}_{year}'
                summary[label]=capture(label,'api.stlouisfed.org',lambda s=series,y=year,e=end:get(
                    'https://api.stlouisfed.org/fred/series/observations',params=dict(api_key=os.environ['FRED_API_KEY'],
                    file_type='json',series_id=s,observation_start='2000-01-01',observation_end='2026-10-30',
                    realtime_start=f'{y}-01-01',realtime_end=e,output_type=1,limit=100000)))
    key=os.environ['ECOS_API_KEY']
    for label,endpoint in [('meta','StatisticMeta/'+key+'/json/kr/1/100/817Y002'),
        ('items','StatisticItemList/'+key+'/json/kr/1/100/817Y002'),
        ('recent','StatisticSearch/'+key+'/json/kr/1/100/817Y002/D/20260901/20261030/010200000')]:
        summary['ECOS_'+label]=capture('ecos/'+label,'ecos.bok.or.kr',lambda e=endpoint:get('https://ecos.bok.or.kr/api/'+e))
    save(OUT/'macro_summary.json',summary)
    print(json.dumps(summary))

def main():
    p=argparse.ArgumentParser();p.add_argument('--macro',action='store_true');args=p.parse_args()
    credentials()
    if args.macro:macro()

if __name__=='__main__':main()
