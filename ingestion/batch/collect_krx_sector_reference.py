"""Collect a dated official KRX industry reference; does not update cloud resources."""
import argparse
import contextlib
import io
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
import requests


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--date',required=True,help='KRX trading date, YYYYMMDD')
    parser.add_argument('--output-dir',required=True)
    args=parser.parse_args()
    day=datetime.strptime(args.date,'%Y%m%d').date()
    if not all(os.environ.get(k) for k in ['KRX_ID','KRX_PW']):
        raise RuntimeError('Set KRX_ID and KRX_PW in the local process environment')
    original=requests.Session.send
    def checked(session,request,**kwargs):
        host=urlparse(request.url).hostname or ''
        if host!='krx.co.kr' and not host.endswith('.krx.co.kr'):
            raise RuntimeError('Non-KRX source blocked')
        kwargs['timeout']=45
        return original(session,request,**kwargs)
    requests.Session.send=checked
    previous_logging=logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        # The provider library prints login information; never forward its console output.
        with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
            from pykrx.website.krx.market.core import 업종분류현황
            rows=업종분류현황().fetch(args.date,'STK').to_dict('records')
        if not rows:raise RuntimeError('Empty KRX reference response')
        payload={'source':'KRX','bld':'dbms/MDC/STAT/standard/MDCSTAT03901',
                 'query_date':day.isoformat(),'retrieved_at':datetime.now(timezone.utc).isoformat(),'rows':rows}
        target=Path(args.output_dir)/('krx_sector_'+args.date+'.json')
        target.parent.mkdir(parents=True,exist_ok=True)
        # Existing raw evidence is immutable. Choose a different folder if recollecting.
        with target.open('x',encoding='utf8') as f:json.dump(payload,f,ensure_ascii=False,indent=2)
        print(json.dumps({'rows':len(rows),'query_date':day.isoformat(),'file':str(target)}))
    finally:
        requests.Session.send=original
        logging.disable(previous_logging)


if __name__=='__main__':main()
