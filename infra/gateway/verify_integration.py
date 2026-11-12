"""실제 APIM, ML, PubSub 검증. 비밀값은 저장하지 않고 테스트 사용자만 사용합니다."""
import argparse
import asyncio
import base64
import itertools
import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
import websockets

import deploy as d


def principal(uid):
    return base64.b64encode(json.dumps({'identityProvider':'aad','userId':uid,
        'userDetails':'integration-test','userRoles':['authenticated'],'claims':[]}).encode()).decode()


async def stream(url, seconds):
    out = {'connected':False,'messages':0,'records':0,'assets':set(),'as_of':set(),'record_types':set()}
    try:
        async with websockets.connect(url, open_timeout=15) as ws:
            out['connected'] = True
            end = time.monotonic() + seconds
            while time.monotonic() < end:
                try: raw = await asyncio.wait_for(ws.recv(), max(.1,end-time.monotonic()))
                except asyncio.TimeoutError: break
                data = json.loads(raw)
                out['messages'] += 1
                rows = data.get('quotes',[]) if data.get('type')=='quote_batch' else [data]
                for row in rows:
                    out['records'] += 1
                    if row.get('asset_id'): out['assets'].add(row['asset_id'])
                    if row.get('as_of'): out['as_of'].add(row['as_of'])
                    if row.get('record_type'): out['record_types'].add(row['record_type'])
    except Exception as exc:
        out['error_type'] = type(exc).__name__  # 토큰이 포함된 연결 URL/예외 본문은 저장하지 않습니다.
    for k in ('assets','as_of','record_types'): out[k] = sorted(out[k])
    return out


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',required=True)
    p.add_argument('--stream-seconds',type=int,default=75);args=p.parse_args()
    out={'checked_at':datetime.now(timezone.utc).isoformat(),'checks':[],
         'auth_scope':'APIM server subscription with isolated test principal; browser login tested separately'}
    common=d.call(d.COMMON,'2024-03-01')
    base='https://'+common['properties']['configuration']['ingress']['fqdn']
    apim=d.call(d.APIM,'2024-05-01')['properties']['gatewayUrl']
    subscriptions=d.call(d.APIM+'/subscriptions','2024-05-01')['value']
    # 서버 측 검사 전용 구독을 메모리에서만 사용합니다. 브라우저에 키를 전달하지 않습니다.
    eligible=[s for s in subscriptions if s['properties']['state']=='active' and
              (s['properties'].get('scope','').endswith('/apis') or
               s['properties'].get('scope','').rstrip('/')==d.APIM)]
    if not eligible: raise RuntimeError('No existing service-wide test subscription; do not create one automatically')
    key=d.call(eligible[0]['id']+'/listSecrets','2024-05-01','POST')['primaryKey']
    headers={'Ocp-Apim-Subscription-Key':key,'X-MS-CLIENT-PRINCIPAL':principal('gateway-integration-20261112')}

    def check(name,method,path,body=None,expected=200,other=False):
        h=dict(headers)
        if other:h['X-MS-CLIENT-PRINCIPAL']=principal('gateway-integration-other-20261112')
        started=time.monotonic()
        r=requests.request(method,apim+path,headers=h,json=body,timeout=45)
        row={'name':name,'status':r.status_code,'expected_status':expected,
             'elapsed_seconds':round(time.monotonic()-started,3),'passed':r.status_code==expected}
        out['checks'].append(row);print(name,r.status_code,flush=True)
        if r.status_code != expected: raise RuntimeError(name+' status '+str(r.status_code))
        return r.json()

    try:
        support=check('support','GET','/api/stress/support')
        snapshot=check('snapshot','GET','/api/stress/snapshot')
        out['ml']={'assets':support['supported_assets'],'snapshot':snapshot,'package_id':support['package_id']}
        quotes=check('quotes','GET','/api/quotes/latest')
        market=check('market','GET','/api/market-state/current')
        out['quote_count']=len(quotes.get('quotes',[]))
        out['market']={k:(market.get('snapshot') or {}).get(k) for k in
            ('as_of','snapshot_id','quality_status','valid_asset_count','expected_asset_count','market_phase')}
        body={'positions':[{'asset_id':a,'value_krw':1000000} for a in support['supported_assets']],
              'shocks':{'fx_pct':5,'us_rate_bp':100,'wti_pct':10,'vix_points':5},'model':'catboost'}
        all_result=check('all_supported_assets','POST','/api/stress/analyze',body)
        assert len(all_result['assets'])==len(body['positions'])
        assert math.isclose(all_result['portfolio_hypothetical_pnl_krw'],sum(a['hypothetical_pnl_krw'] for a in all_result['assets']))
        out['all_assets_result']=all_result
        body['positions']=[{'asset_id':'005930','value_krw':50000000},{'asset_id':'005380','value_krw':50000000}]
        combinations=[]
        for size in range(1,5):
            for keys in itertools.combinations(body['shocks'],size):
                b={**body,'shocks':{k:v if k in keys else 0 for k,v in body['shocks'].items()}}
                j=check('shocks_'+'_'.join(keys),'POST','/api/stress/analyze',b)
                assert j['shocks']==b['shocks']
                for a in j['assets']:
                    assert math.isclose(a['baseline_pnl_krw']+a['shock_incremental_pnl_krw'],a['hypothetical_pnl_krw'],abs_tol=1e-6)
                combinations.append({'active_shocks':keys,'pnl_krw':j['portfolio_hypothetical_pnl_krw']})
        out['shock_combinations']=combinations
        zero=check('zero_shocks','POST','/api/stress/analyze',{**body,'shocks':{}})
        assert all(a['change_from_baseline_pp']==0 for a in zero['assets'])
        check('unsupported','POST','/api/stress/analyze',{**body,'positions':[{'asset_id':'373220','value_krw':1}]},422)
        check('duplicate','POST','/api/stress/analyze',{**body,'positions':[body['positions'][0]]*2},422)
        check('invalid_shock','POST','/api/stress/analyze',{**body,'shocks':{'fx_pct':-100}},422)
        check('missing_positions','POST','/api/stress/analyze',{'shocks':{}},422)
        holdings=check('holdings','GET','/api/me/holdings')
        # 이 전용 테스트 사용자의 기존 값을 보존하고 finally에서 복구합니다.
        previous={'holdings':[{'asset_id':a['asset_id'],'amount_krw':a['amount_krw']} for a in holdings['holdings']]}
        try:
            check('holdings_write','PUT','/api/me/holdings',{'holdings':[{'asset_id':'005930','amount_krw':123456}]})
            own=check('holdings_readback','GET','/api/me/holdings')
            other=check('holdings_other_user','GET','/api/me/holdings',other=True)
            assert own['total_krw']==123456 and other['holdings']==[]
        finally: check('holdings_restore','PUT','/api/me/holdings',previous)
        for name,url,h in [
            ('direct_common',base+'/api/me',{}),
            ('apim_no_key',apim+'/api/me',{}),
            ('apim_no_user',apim+'/api/me',{'Ocp-Apim-Subscription-Key':key})]:
            r=requests.get(url,headers=h,timeout=20,allow_redirects=False)
            out['checks'].append({'name':name,'status':r.status_code,'passed':r.status_code in (401,403)})
        q=check('quotes_negotiate','POST','/api/quotes/negotiate',{})
        m=check('market_negotiate','POST','/api/market-state/negotiate',{})
        async def both(): return await asyncio.gather(stream(q['url'],15),stream(m['url'],args.stream_seconds))
        out['streams']=dict(zip(('quotes','market'),asyncio.run(both())))
        out['http_checks_passed']=all(x['passed'] for x in out['checks'])
        out['stream_data_observed']=all(x['messages']>0 for x in out['streams'].values())
    finally:
        Path(args.output).write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf8')


if __name__=='__main__':main()
