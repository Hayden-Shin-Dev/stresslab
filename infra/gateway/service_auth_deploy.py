"""2026-11-11 민철 추가: 팀 RG 권한으로 Key Vault 서명 인증을 배포합니다.

Entra 앱 역할/동의/할당 정책은 변경하지 않습니다. 기존 ML 경로도 유지합니다.
prepare -> ML wrapper 배포 -> readiness 확인 -> enable 순서를 지킵니다.
"""
import argparse
import copy
import json
import time
import uuid
from pathlib import Path

import requests
import deploy as d

VAULT = d.ROOT + '/providers/Microsoft.KeyVault/vaults/kv-whatif-dev-5dt'
KEY = VAULT + '/keys/stresslab-ml-request-signing'
STATE = Path.home()/'.cache/stresslab-gateway-service-auth-state.json'
NAMESPACE = uuid.UUID('63f3480c-53c5-4f1b-bf56-cf52b90fedf3')


def role_assignment(scope, principal, definition, kind):
    path = scope + '/providers/Microsoft.Authorization/roleAssignments/' + str(uuid.uuid5(NAMESPACE, principal+definition))
    d.call(path, '2022-04-01', 'PUT', {'properties': {'principalId': principal,
        'principalType': kind, 'roleDefinitionId': definition}})
    return path


def set_env(container, values):
    container['env'] = [x for x in container.get('env', []) if x['name'] not in values]
    container['env'] += [{'name': k, 'value': v} for k, v in values.items()]


def prepare():
    if STATE.exists():
        print('Prepared state already exists; no keys or identities recreated')
        return
    app = d.call(d.COMMON, '2024-03-01')
    identities = {k: {} for k in app['identity'].get('userAssignedIdentities', {})}
    updated = d.call(d.COMMON, '2024-03-01', 'PATCH', {'identity': {
        'type': 'SystemAssigned, UserAssigned', 'userAssignedIdentities': identities}})
    principal = d.call(d.COMMON, '2024-03-01')['identity']['principalId']
    # 암호화/복호화/백업/다른 비밀 조회 권한은 포함하지 않습니다.
    definition = d.ROOT + '/providers/Microsoft.Authorization/roleDefinitions/' + str(uuid.uuid5(NAMESPACE, 'sign-only'))
    d.call(definition, '2022-04-01', 'PUT', {'properties': {
        'roleName': 'StressLab ML Request Signer', 'type': 'CustomRole',
        'description': 'Read public key and sign ML service requests with one assigned key.',
        'permissions': [{'actions': [], 'notActions': [], 'dataActions': [
            'Microsoft.KeyVault/vaults/keys/read', 'Microsoft.KeyVault/vaults/keys/sign/action'], 'notDataActions': []}],
        'assignableScopes': [d.ROOT]}})
    key = d.call(KEY, '2023-07-01', 'PUT', {'properties': {'kty': 'RSA', 'keySize': 2048,
        'keyOps': ['sign', 'verify'], 'attributes': {'enabled': True, 'exp': int(time.time())+365*86400}}})
    kid = key['properties']['keyUriWithVersion']
    assignment = role_assignment(KEY, principal, definition, 'ServicePrincipal')
    # 배포자에게는 공개키 읽기만 임시 부여하고 조회 직후 회수합니다.
    user = d.cli('ad', 'signed-in-user', 'show')['id']
    reader = '/subscriptions/'+d.SUB+'/providers/Microsoft.Authorization/roleDefinitions/21090545-7ca7-4776-b22c-e363652d74d2'
    temporary = role_assignment(KEY, user, reader, 'User')
    info = {'key_id': kid, 'principal_id': principal, 'role_assignment': assignment,
            'temporary_reader_assignment': temporary,
            'issuer': 'stresslab-common-api:'+principal,
            'original_ml_auth': d.call(d.ML+'/authConfigs/current', '2024-03-01')['properties'],
            'original_ml_template': d.call(d.ML, '2024-03-01')['properties']['template'],
            'original_common_template': app['properties']['template']}
    STATE.write_text(json.dumps(info, indent=2), encoding='utf8')
    print('Dedicated system identity and key-scoped sign-only permission created')


def public_key():
    info=json.loads(STATE.read_text(encoding='utf8'))
    token=d.cli('account','get-access-token','--resource','https://vault.azure.net')['accessToken']
    r=requests.get(info['key_id']+'?api-version=7.4',headers={'Authorization':'Bearer '+token},timeout=30)
    if not r.ok: raise RuntimeError('Public key read HTTP '+str(r.status_code)+'; RBAC propagation may be pending')
    key=r.json()['key']
    info['public_keys']={info['key_id']:{k:key[k] for k in ['kty','n','e']}}
    STATE.write_text(json.dumps(info, indent=2),encoding='utf8')
    d.call(info['temporary_reader_assignment'],'2022-04-01','DELETE')
    print('Public key pinned; temporary reader permission removed')


def wrapper(image):
    info=json.loads(STATE.read_text(encoding='utf8'))
    ml=d.call(d.ML,'2024-03-01')
    template=copy.deepcopy(ml['properties']['template'])
    template['containers'][0]['image']=image
    set_env(template['containers'][0],{'ML_SERVICE_PUBLIC_KEYS':json.dumps(info['public_keys'],separators=(',',':')),
        'ML_SERVICE_ISSUER':info['issuer']})
    d.call(d.ML,'2024-03-01','PATCH',{'properties':{'template':template}})
    print('ML auth wrapper deployed; original model image digest preserved as base')


def enable(image):
    info=json.loads(STATE.read_text(encoding='utf8'))
    ml=d.call(d.ML,'2024-03-01')
    if (ml['properties']['provisioningState'] != 'Succeeded'
        or ml['properties']['latestRevisionName'] != ml['properties']['latestReadyRevisionName']
        or 'service-auth' not in ml['properties']['template']['containers'][0]['image']):
        raise RuntimeError('ML wrapper revision is not ready')
    auth=d.call(d.ML+'/authConfigs/current','2024-03-01')['properties']
    excluded=auth.setdefault('globalValidation',{}).setdefault('excludedPaths',[])
    # 광범위한 /* 예외가 아니라 코드에서 서명을 검증하는 경로 3개만 추가합니다.
    for path in ['/service/metadata','/service/snapshot/metadata','/service/predict/auto']:
        if path not in excluded: excluded.append(path)
    d.call(d.ML+'/authConfigs/current','2024-03-01','PUT',{'properties':auth})
    app=d.call(d.COMMON,'2024-03-01');template=copy.deepcopy(app['properties']['template'])
    template['containers'][0]['image']=image
    set_env(template['containers'][0], {'ML_API_URL':'https://'+ml['properties']['configuration']['ingress']['fqdn']+'/service',
        'ML_SIGNING_KEY_ID':info['key_id'],'ML_SERVICE_ISSUER':info['issuer']})
    d.call(d.COMMON,'2024-03-01','PATCH',{'properties':{'template':template}})
    print('Signed service requests enabled; original Entra authentication remains enabled')


def rollback():
    info=json.loads(STATE.read_text(encoding='utf8'))
    # 인증 예외를 먼저 닫은 다음 이전 이미지를 복원합니다.
    d.call(d.ML+'/authConfigs/current','2024-03-01','PUT',{'properties':info['original_ml_auth']})
    d.call(d.ML,'2024-03-01','PATCH',{'properties':{'template':info['original_ml_template']}})
    d.call(d.COMMON,'2024-03-01','PATCH',{'properties':{'template':info['original_common_template']}})
    print('Original auth and templates restored')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('step',choices=['prepare','public_key','wrapper','enable','rollback'])
    p.add_argument('--image');args=p.parse_args()
    if args.step in ['wrapper','enable']:
        if not args.image:p.error('--image is required')
        globals()[args.step](args.image)
    else:globals()[args.step]()
