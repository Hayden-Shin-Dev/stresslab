"""공통 API 실연결 검사. 계정/보유종목은 쓰지 않으며 인증값은 출력하지 않습니다."""
import argparse
import base64
import json
import time
from pathlib import Path
import requests
import deploy as d

parser=argparse.ArgumentParser()
parser.add_argument('--output',default='gateway-verification.json')
args=parser.parse_args()
app=d.call(d.COMMON,'2024-03-01')
url='https://'+app['properties']['configuration']['ingress']['fqdn']
principal=base64.b64encode(json.dumps({'identityProvider':'aad','userId':'gateway-integration-readonly',
    'userDetails':'integration-test','userRoles':['anonymous','authenticated']}).encode()).decode()
headers={'X-StressLab-Gateway-Key':d.backend_key(),'X-MS-CLIENT-PRINCIPAL':principal}
results={'checked_at':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'common_api':url,'checks':[]}
checks=[('health','GET','/healthz',None,False),('untrusted','GET','/api/me',None,False),
    ('holdings','GET','/api/me/holdings',None,True),('debates','GET','/api/debates',None,True),
    ('quotes','GET','/api/quotes/latest',None,True),('quote_negotiate','POST','/api/quotes/negotiate',{},True),
    ('market','GET','/api/market-state/current',None,True),('market_negotiate','POST','/api/market-state/negotiate',{},True),
    ('support','GET','/api/stress/support',None,True),('snapshot','GET','/api/stress/snapshot',None,True),
    ('analyze','POST','/api/stress/analyze',{'positions':[{'asset_id':'005930','value_krw':50000000},
       {'asset_id':'005380','value_krw':50000000}],'shocks':{'fx_pct':5,'us_rate_bp':100,'wti_pct':0,'vix_points':0},'model':'catboost'},True)]
for name,method,path,body,auth in checks:
    t=time.monotonic()
    r=requests.request(method,url+path,headers=headers if auth else {},json=body,timeout=45)
    row={'name':name,'status':r.status_code,'elapsed_seconds':round(time.monotonic()-t,2)}
    # 연결 토큰/인증 헤더를 결과 파일에 저장하지 않습니다.
    if name in ('analyze','support','snapshot') and r.status_code==200:row['response']=r.json()
    elif r.status_code>=400:
        try:row['error']=r.json().get('detail')
        except ValueError:row['error']='non-JSON response'
    elif name=='quotes':row['quote_count']=len(r.json().get('quotes',[]))
    elif name=='market':row['snapshot_as_of']=(r.json().get('snapshot') or {}).get('as_of')
    results['checks'].append(row)
    print(name,r.status_code,row['elapsed_seconds'],flush=True)
Path(args.output).write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf8')
if any(x['status']!=(403 if x['name']=='untrusted' else 200) for x in results['checks']):raise SystemExit(1)
