"""APIM -> 공통 FastAPI 연결. 비밀값은 메모리와 Azure에만 보관합니다.

prepare: 새 공통 API 배포와 ML 호출 클라이언트 허용
gateway: APIM API/정책 생성 (웹 연결은 아직 변경하지 않음)
cutover: 기존 웹의 backend1을 APIM으로 전환하고 생성된 상품에 API 연결
rollback: 웹을 이전 토론 API로 복구
"""
import argparse
import copy
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import time

import requests

SUB = '27db5ec6-d206-4028-b5e1-6004dca5eeef'
RG = '5dt-final-team3'
ROOT = f'/subscriptions/{SUB}/resourceGroups/{RG}'
ARM = 'https://management.azure.com'
APIM = ROOT + '/providers/Microsoft.ApiManagement/service/apim-whatif-dev'
COMMON = ROOT + '/providers/Microsoft.App/containerApps/ca-api-whatif-dev'
DEBATE = ROOT + '/providers/Microsoft.App/containerApps/ca-debateapi-whatif-dev'
ML = ROOT + '/providers/Microsoft.App/containerApps/ca-stresslab-api-research-dev'
SWA = ROOT + '/providers/Microsoft.Web/staticSites/swa-whatif-dev'

def cli(*args):
    p = subprocess.run([shutil.which('az'), *args, '-o', 'json', '--only-show-errors'],
                       capture_output=True, encoding='utf8', errors='replace', timeout=120)
    if p.returncode: raise RuntimeError('Azure CLI failed: ' + p.stderr[:250])
    return json.loads(p.stdout)

_token = None
_token_at = 0
def headers():
    global _token, _token_at
    if _token is None or time.time()-_token_at > 1800:
        _token = cli('account','get-access-token','--resource',ARM+'/')['accessToken']
        _token_at = time.time()
    return {'Authorization':'Bearer ' + _token}

def call(path, version, method='GET', body=None):
    r=requests.request(method,ARM+path,params={'api-version':version},headers=headers(),json=body,timeout=120)
    if not r.ok:
        # 오류 본문에 설정값이 포함될 수 있어 상태 코드만 출력합니다.
        try:code=r.json().get('error',{}).get('code')
        except ValueError:code=None
        raise RuntimeError(f'ARM {method} {path} returned {r.status_code} {code}')
    if not r.content:return {}
    text=r.content.decode('utf-8-sig').strip()
    if text.startswith('<'):return {'raw_xml':text}
    return json.loads(text)

def backend_key():
    j=call(COMMON+'/listSecrets','2024-03-01','POST')
    return next(x['value'] for x in j.get('value',[]) if x['name']=='gateway-key')

def ml_role():
    # 2026-11-11 민철 추가: 사용자 위임 scope와 서버 간 Application 역할을 구분합니다.
    # 기존 Prediction.Read 사용자 scope와 기존 앱 역할은 보존합니다.
    token=cli('account','get-access-token','--resource','https://graph.microsoft.com/')['accessToken']
    def graph(path,method='GET',body=None):
        r=requests.request(method,'https://graph.microsoft.com/v1.0'+path,
            headers={'Authorization':'Bearer '+token},json=body,timeout=40)
        if not r.ok:raise RuntimeError(f'Graph {method} {path} HTTP {r.status_code}: '+r.json().get('error',{}).get('code',''))
        return r.json() if r.content else {}
    auth=call(ML+'/authConfigs/current','2024-03-01')['properties']
    app_id=auth['identityProviders']['azureActiveDirectory']['registration']['clientId']
    app=graph(f"/applications?$filter=appId eq '{app_id}'")['value'][0]
    roles=app.get('appRoles',[])
    role=next((x for x in roles if x['value']=='Prediction.Invoke' and 'Application' in x['allowedMemberTypes']),None)
    if role is None:
        role={'id':'08ab959e-3db1-493e-a01e-d97cfcd1cc64','allowedMemberTypes':['Application'],
            'description':'Read prediction outputs from the StressLab ML API.',
            'displayName':'Read model predictions','isEnabled':True,'value':'Prediction.Invoke'}
        graph('/applications/'+app['id'],'PATCH',{'appRoles':roles+[role]})
        print('ML application role created: Prediction.Invoke')
    resource=graph(f"/servicePrincipals?$filter=appId eq '{app_id}'")['value'][0]
    identity=call(COMMON,'2024-03-01')['identity']['userAssignedIdentities']
    principal=next(iter(identity.values()))['principalId']
    assignments=graph('/servicePrincipals/'+principal+'/appRoleAssignments')['value']
    if not any(x['resourceId']==resource['id'] and x['appRoleId']==role['id'] for x in assignments):
        graph('/servicePrincipals/'+principal+'/appRoleAssignments','POST',
            {'principalId':principal,'resourceId':resource['id'],'appRoleId':role['id']})
    print('Common API identity granted ML Prediction.Invoke application role')

def prepare(image):
    old=call(DEBATE,'2024-03-01')
    ml=call(ML,'2024-03-01')
    p=old['properties'];container=p['template']['containers'][0]
    env=[copy.deepcopy(x) for x in container.get('env',[]) if 'secretRef' not in x and x['name'] not in
         ['ALLOW_DEV_USER_HEADER','CORS_ORIGINS','ALLOWED_ASSETS']]
    identity=copy.deepcopy(old['identity']);mi=next(iter(identity['userAssignedIdentities'].values()))
    identity={'type':'UserAssigned','userAssignedIdentities':{k:{} for k in identity['userAssignedIdentities']}}
    auth=call(ML+'/authConfigs/current','2024-03-01')
    aad=auth['properties']['identityProviders']['azureActiveDirectory']
    ml_app=aad['registration']['clientId']
    allowed=aad.setdefault('validation',{}).setdefault('defaultAuthorizationPolicy',{}).setdefault('allowedApplications',[])
    if mi['clientId'] not in allowed:
        allowed.append(mi['clientId'])
        call(ML+'/authConfigs/current','2024-03-01','PUT',{'properties':auth['properties']})
        print('ML auth: added common API managed identity; existing clients preserved')
    # 2026-11-11 민철 추가: 기존 앱 설정은 복사만 하며 원본 토론 앱/예약은 수정하지 않습니다.
    exists=requests.get(ARM+COMMON,params={'api-version':'2024-03-01'},headers=headers(),timeout=30)
    if exists.status_code==200:key=backend_key()
    elif exists.status_code==404:key=secrets.token_urlsafe(48)
    else:raise RuntimeError('Cannot determine common API existence')
    env += [{'name':'GATEWAY_SHARED_KEY','secretRef':'gateway-key'},
            {'name':'ALLOW_DEV_USER_HEADER','value':'false'},
            {'name':'ML_API_URL','value':'https://'+ml['properties']['configuration']['ingress']['fqdn']},
            {'name':'ML_TOKEN_SCOPE','value':f'api://{ml_app}/.default'},
            {'name':'QUOTE_API_URL','value':'https://func-whatif-dev-h6a0ebd4c6duhzg2.koreacentral-01.azurewebsites.net/api/quotes'},
            {'name':'MARKET_STATE_URL','value':'https://ca-marketstate-whatif-dev.proudfield-489f3ad8.koreacentral.azurecontainerapps.io/market-state'}]
    body={'location':old['location'],'identity':identity,'tags':{'project':'StressLab','role':'common-api'},
          'properties':{'environmentId':p['environmentId'],
             'configuration':{'activeRevisionsMode':'Single','secrets':[{'name':'gateway-key','value':key}],
                 'registries':p['configuration']['registries'],
                 'ingress':{'external':True,'targetPort':8000,'allowInsecure':False,'transport':'auto'}},
             'template':{'containers':[{'name':'common-api','image':image,'env':env,
                  'resources':{'cpu':0.5,'memory':'1Gi'},'probes':[
                    {'type':'Readiness','httpGet':{'path':'/healthz','port':8000},'initialDelaySeconds':10,'periodSeconds':10},
                    {'type':'Liveness','httpGet':{'path':'/healthz','port':8000},'initialDelaySeconds':30,'periodSeconds':30}]}],
                 'scale':{'minReplicas':1,'maxReplicas':2}}}}
    j=call(COMMON,'2024-03-01','PUT',body)
    print('Common API:',j.get('properties',{}).get('provisioningState'))

def gateway():
    apim=call(APIM,'2024-05-01')
    if apim['properties']['provisioningState']!='Succeeded':raise RuntimeError('APIM not ready')
    app=call(COMMON,'2024-03-01')
    url='https://'+app['properties']['configuration']['ingress']['fqdn']
    call(APIM+'/namedValues/common-api-key','2024-05-01','PUT',{'properties':{
        'displayName':'common-api-key','secret':True,'value':backend_key()}})
    api=APIM+'/apis/stresslab'
    call(api,'2024-05-01','PUT',{'properties':{'displayName':'StressLab common API','path':'api',
         'protocols':['https'],'serviceUrl':url+'/api','subscriptionRequired':True}})
    # 실제 공개 경로만 등록합니다. /scheduled-debates 또는 임의 프록시는 공개하지 않습니다.
    routes=[('GET','/healthz'),('GET','/me'),('GET','/me/holdings'),('PUT','/me/holdings'),
        ('POST','/debates'),('GET','/debates'),('GET','/debates/{debate_id}'),
        ('POST','/debates/{debate_id}/questions'),('GET','/debates/{debate_id}/negotiate'),('GET','/debates/{debate_id}/events'),
        ('GET','/quotes/latest'),('POST','/quotes/negotiate'),('GET','/market-state/current'),('POST','/market-state/negotiate'),
        ('GET','/stress/support'),('GET','/stress/snapshot'),('POST','/stress/analyze')]
    for n,(method,path) in enumerate(routes):
        params=[{'name':'debate_id','type':'string','required':True}] if '{debate_id}' in path else []
        call(api+f'/operations/route-{n}','2024-05-01','PUT',{'properties':{'displayName':method+' '+path,
            'method':method,'urlTemplate':path,'templateParameters':params,'responses':[]}})
    # product의 SWA JWT 검증은 <base/>를 통해 유지합니다. 해당 상품 정책은 수정하지 않습니다.
    policy='''<policies><inbound><base /><set-header name="X-StressLab-Gateway-Key" exists-action="override"><value>{{common-api-key}}</value></set-header><set-header name="X-User-Id" exists-action="delete" /><set-header name="Authorization" exists-action="delete" /><set-header name="Ocp-Apim-Subscription-Key" exists-action="delete" /></inbound><backend><forward-request timeout="40" /></backend><outbound><base /></outbound><on-error><base /></on-error></policies>'''
    call(api+'/policies/policy','2024-05-01','PUT',{'properties':{'format':'rawxml','value':policy}})
    print('APIM routes configured:',len(routes))

def cutover():
    # SWA가 전용 subscription/JWT 정책을 생성하게 합니다. 생성된 인증값은 직접 덮어쓰지 않습니다.
    j=call(SWA+'/linkedBackends/backend1','2023-12-01','PUT',{'properties':{'backendResourceId':APIM,'region':'koreacentral'}})
    print('SWA backend:',j.get('properties',{}).get('provisioningState'))

def product():
    products=call(APIM+'/products','2024-05-01').get('value',[])
    matches=[p for p in products if 'red-field-0b8ece310' in p['properties'].get('displayName','')]
    if len(matches)!=1:raise RuntimeError('Expected exactly one SWA linked product; retry after link completes')
    call(matches[0]['id']+'/apis/stresslab','2024-05-01','PUT',{})
    print('Common API added to SWA linked product')

def rollback():
    call(SWA+'/linkedBackends/backend1','2023-12-01','PUT',{'properties':{'backendResourceId':DEBATE,'region':'koreacentral'}})
    print('SWA restored to original debate API')

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('step',choices=['prepare','ml_role','gateway','cutover','product','rollback'])
    parser.add_argument('--image',default='acrwhatifdev5dt.azurecr.io/common-api:gateway-20261111-v2')
    args=parser.parse_args()
    if args.step=='prepare':prepare(args.image)
    else:globals()[args.step]()
