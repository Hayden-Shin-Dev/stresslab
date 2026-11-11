# 공통 API 연결

2026-11-11 민철 작업입니다. Fabric, Gold, ML 학습 코드와 모델 파일은 수정하지 않았습니다.

| 대상 | 작업 상태 |
| --- | --- |
| `apim-whatif-dev` | Consumption 리소스 생성, 17개 경로와 백엔드 정책 등록 |
| `ca-api-whatif-dev` | 공통 FastAPI 배포, 기존 토론 코드 재사용 |
| 기존 ML 앱 인증 | 기존 허용 클라이언트 유지, 호출 관리 ID 추가 |
| ML Entra 앱 | 서버용 `Prediction.Invoke` 역할 생성, 역할 할당은 관리자 권한 부족으로 미완료 |
| 기존 Static Web App | 연결과 배포 파일 미전환, 기존 서비스 유지 |

관리 ID는 기존 `id-debate-whatif-dev`를 사용합니다. 기존 PostgreSQL, Service Bus, PubSub 권한을 재사용하며 DB 테이블을 변경하지 않습니다. 공통 API는 0.5 CPU, 1 GiB, 최소 1개 복제본으로 실행하므로 실행 비용이 추가됩니다. APIM은 호출량 기준 Consumption입니다.

## 남은 관리자 작업

앱 소유자는 역할을 만들 수 있지만 서버에 Application 역할을 할당하는 권한과는 다릅니다. 현재 `5dt024`는 앱 소유자로 추가됐고 역할 생성은 성공했습니다. 역할 할당은 `403 Authorization_RequestDenied`로 거절됐습니다.

Entra Application Administrator 또는 Cloud Application Administrator 등 해당 권한이 있는 관리자가 Azure CLI에 로그인하고 다음을 실행합니다.

```powershell
az login --tenant 5fb256f0-fbf2-40d2-81d5-bac1b32c419d
./infra/gateway/grant-ml-role.ps1
```

이 스크립트는 ML API의 `Prediction.Invoke` 역할 한 건만 `id-debate-whatif-dev`에 부여합니다. 기존 사용자용 `Prediction.Read` scope와 소유자는 유지합니다. 이미 부여되어 있으면 재생성하지 않습니다.

## 실행 순서

저장소 루트에서 실행합니다. Python에는 requests가 필요합니다. Azure CLI 로그인 권한을 사용하며 키는 화면이나 파일에 출력하지 않습니다.

```powershell
./infra/gateway/build.ps1
python infra/gateway/deploy.py prepare
python infra/gateway/verify.py --output gateway-verification.json
python infra/gateway/deploy.py gateway
```

`verify.py`는 공통 API 직접 우회 차단, 보유종목 조회, 토론 목록, 현재가와 시장 상태, ML 지원 목록 및 두 종목 계산을 확인합니다. 실제 계정의 보유종목을 저장하거나 토론을 생성하지 않습니다. 현재 ML 역할 미할당 상태에서는 실패하는 것이 정상입니다.

전환 전 SWA 로그인 요청을 APIM으로 전달하는 검사도 필요합니다. 현재 인위적으로 만든 로그인 헤더에서 `claims` 필드가 없으면 Consumption 경유 500, 있으면 200이 재현됐습니다. 실제 SWA 로그인 헤더 전달은 아직 검증하지 않았으므로 해결됐다고 표시하지 않습니다.

검사를 모두 마친 뒤에만 다음을 실행합니다.

```powershell
python infra/gateway/deploy.py cutover
python infra/gateway/deploy.py product
python apps/web/quote-monitor/deploy.py
```

`cutover`는 기존 SWA backend1을 APIM으로 바꾸고, `product`는 SWA가 생성한 인증 상품에 공통 API를 추가합니다. SWA가 생성한 JWT 정책과 구독 키는 직접 수정하지 않습니다. 문제가 있으면 `python infra/gateway/deploy.py rollback`으로 기존 토론 API 연결을 복구하고, 웹 파일도 전환 전 버전으로 배포해야 합니다.

## 파일별 변경

| 파일 | 내용 |
| --- | --- |
| `services/api/src/gateway.py` | 인증 경계, ML 호출, 로그수익률 변환, 포트폴리오 합산 |
| `services/api/tests/test_gateway.py` | 인증 우회, 단위 변환, 입력 오류, 버전 혼합 검사 |
| `services/api/Dockerfile` | Python 3.12 공통 API 이미지 |
| `apps/web/quote-monitor/monitor.js`, `market-state.js` | REST 요청을 같은 사이트 `/api`로 연결하는 전환안 |
| `apps/web/quote-monitor/stress.html`, `stress.js` | 기존 배포 ML 호출 확인 화면 |
| `staticwebapp.config.json` | 전환 후 화면과 API 로그인 보호, 기존 Google 설정 유지 |

[SWA와 APIM 공식 연결 문서](https://learn.microsoft.com/en-us/azure/static-web-apps/apis-api-management), [관리 ID 앱 역할 부여 문서](https://learn.microsoft.com/en-us/graph/api/serviceprincipal-post-approleassignments)를 기준으로 작업했습니다.
