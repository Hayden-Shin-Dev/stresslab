# 공통 API 연결

2026-11-11 민철 작업입니다. Fabric, Gold, ML 학습 코드와 모델 파일은 변경하지 않았습니다.

웹의 `/api` 요청은 `Static Web Apps → APIM → 공통 FastAPI`로 전달합니다. 시세와 시장 상태는 연결 주소를 발급받은 뒤 기존 Web PubSub에서 받습니다.

실제 Google 로그인, 웹의 두 종목 계산, 보유종목 조회, 시세 20종목과 새 메시지 62건 수신을 확인했습니다. 시장 상태 연결과 저장 스냅샷 조회도 정상입니다. 장 종료 후 확인이므로 장중 지표의 최신성까지 재검증한 것은 아닙니다. 검증 기록은 [validation_20261111.json](validation_20261111.json)입니다.

## 서버 인증

공통 API의 시스템 할당 관리 ID로 기존 Key Vault의 `stresslab-ml-request-signing` 키를 사용합니다. 해당 키의 공개키 조회와 서명만 허용하는 역할을 키 하나에 한정해 부여했습니다. 개인키는 서버에 저장하거나 내보내지 않습니다.

ML에는 기존 모델 이미지를 그대로 상속한 인증 래퍼만 추가했습니다. 다음 세 경로는 30초 유효 서명, 호출 주체, 대상 서비스, HTTP 메서드, 경로, 요청 본문 해시를 검사합니다.

- `GET /service/metadata`
- `GET /service/snapshot/metadata`
- `POST /service/predict/auto`

기존 `/metadata`, `/predict` 등의 Entra 인증은 유지합니다. 서버 전용 세 경로만 Easy Auth 검사 대상에서 제외하고 코드에서 서명을 검증합니다. 서명이 없거나 틀리면 401입니다. 읽기와 계산만 지원하며, 같은 서명 요청은 유효시간 내 재사용할 수 있습니다. 저장·주문 경로에는 이 방식을 그대로 확장하지 않습니다.

Entra의 `Prediction.Invoke` 역할 할당은 사용하지 않습니다. 이전 관리자 요청은 더 이상 필요하지 않습니다. 기존 `Prediction.Read`와 앱의 권한 할당 요구 설정은 변경하지 않았습니다.

DB·Service Bus·PubSub 호출은 기존 토론 관리 ID를 재사용합니다. ML 서명 권한은 이 ID가 아닌 공통 API의 시스템 할당 ID에만 있습니다. APIM과 공통 API 사이는 서버 전용 키로 보호하고, 사용자 정보는 SWA 인증 정책을 통과한 요청에서만 받습니다. 브라우저에는 키를 넣지 않습니다.

## 배포와 검증

```powershell
./infra/gateway/build.ps1 -ImageTag gateway-20261111-v3
az acr build --registry acrwhatifdev5dt --image stresslab-api:service-auth-20261111-v1 --file services/ml-auth/Dockerfile services/ml-auth
python infra/gateway/service_auth_deploy.py prepare
python infra/gateway/service_auth_deploy.py public_key
python infra/gateway/service_auth_deploy.py wrapper --image acrwhatifdev5dt.azurecr.io/stresslab-api:service-auth-20261111-v1
# 새 ML revision이 Ready가 된 뒤 실행합니다.
python infra/gateway/service_auth_deploy.py enable --image acrwhatifdev5dt.azurecr.io/common-api:gateway-20261111-v3
python infra/gateway/verify.py --output gateway-verification.json
```

`prepare`는 이미 준비됐으면 재생성하지 않습니다. 공개키를 읽기 위해 배포자에게 잠시 부여한 읽기 권한은 `public_key`에서 회수합니다. 복구용 원본 설정은 배포 PC의 `.cache/stresslab-gateway-service-auth-state.json`에 보존합니다. 토큰과 개인키는 저장하지 않습니다.

웹 연결은 `deploy.py cutover`, `deploy.py product`, 웹 `deploy.py` 순서입니다. SWA는 연결된 백엔드 하나만 허용하므로 기존 연결을 해제한 뒤 APIM으로 연결합니다. SWA가 만든 상품의 JWT 정책과 구독 키는 유지합니다. 전환 실패 시 기존 토론 API로 복구합니다.

검사 명령은 다음과 같습니다.

```powershell
python -m pytest services/ml-auth/test_service_auth.py services/api/tests services/debate/tests/test_api.py -q
```

## 운영과 복구

서명 키의 최초 만료는 생성 후 365일입니다. 만료 전 새 키 버전의 공개키를 ML 허용 목록에 먼저 추가하고, 공통 API의 `ML_SIGNING_KEY_ID`를 새 버전으로 변경해 확인한 뒤 이전 버전을 폐기합니다. 자동 키 교체는 아직 구현하지 않았습니다. Key Vault 장애나 권한 회수 시 서명 요청은 실패하며 인증 없이 통과시키지 않습니다.

ML 인증 복구는 `service_auth_deploy.py rollback`입니다. 먼저 기존 Entra 경로 설정을 복원한 뒤 이전 ML·공통 API 이미지를 복원합니다. 웹 연결 복구는 `deploy.py rollback`이며, 웹 파일도 이전 버전으로 배포해야 합니다.

공통 API는 0.5 CPU, 1 GiB, 최소 1개 복제본입니다. APIM은 Consumption이며 Key Vault 서명 호출에도 사용량 비용이 발생합니다.

## 변경 파일

| 파일 | 역할 |
| --- | --- |
| `services/api/src/gateway.py` | 기존 토론 경로, ML 호출, 수익률 변환과 손익 합산 |
| `services/api/src/service_signing.py` | 관리 ID로 Key Vault 요청 서명 |
| `services/ml-auth/service_auth.py` | 서명 확인 후 기존 ML 함수 호출 |
| `services/ml-auth/Dockerfile` | 원래 모델 이미지 digest를 고정한 인증 이미지 |
| `service_auth_deploy.py` | 키·최소 권한·인증 래퍼 배포와 복구 |
| `apps/web/quote-monitor/stress.html`, `stress.js` | 보유금액과 네 충격을 입력하는 연결 확인 화면 |

공식 기준: [Key Vault 인증](https://learn.microsoft.com/en-us/azure/key-vault/general/authentication), [서명과 검증](https://learn.microsoft.com/en-us/azure/key-vault/keys/javascript-developer-guide-sign-verify-key), [SWA와 APIM 연결](https://learn.microsoft.com/en-us/azure/static-web-apps/apis-api-management).
