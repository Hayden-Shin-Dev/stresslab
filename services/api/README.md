# 공통 API

웹 요청을 받아 기존 토론 코드, PostgreSQL, ML API에 연결하는 FastAPI입니다. 모델 학습과 Fabric 코드는 변경하지 않습니다.

연결 목표는 `Static Web Apps /api → APIM → 공통 FastAPI`입니다. 실시간 데이터는 연결 주소를 발급받은 뒤 기존 Web PubSub에서 받습니다.

2026-11-11 공통 API와 ML 서버 서명 인증을 배포했습니다. APIM 경유 ML 계산과 실제 Google 로그인 후 지원 종목 조회를 확인했습니다. 모델 학습과 성능 승격은 하지 않았습니다.

| 폴더 | 내용 |
| --- | --- |
| [src](src/) | API와 서비스 로직 |
| [tests](tests/) | API 검증 |

| 경로 | 처리 |
| --- | --- |
| `/api/me/holdings` | 기존 보유금액 조회와 저장 |
| `/api/debates` | 기존 토론 요청 큐와 목록 |
| `/api/quotes/latest`, `/api/quotes/negotiate` | 현재가와 Web PubSub 연결 주소 |
| `/api/market-state/current`, `/api/market-state/negotiate` | 현재 시장 상태와 연결 주소 |
| `/api/stress/support`, `/api/stress/snapshot` | 실제 배포 모델 지원 종목과 입력 기준일 |
| `/api/stress/analyze` | 무충격과 사용자 충격 계산 후 종목별 손익 합산 |

모든 사용자 API는 로그인과 APIM 서버 인증이 필요합니다. 브라우저에 API 키를 넣지 않습니다. 공통 API는 관리 ID로 Key Vault에서 요청에 서명하고, ML 서버는 공개키로 검증합니다. 기존 ML Entra 경로는 유지합니다.

요청 예시입니다. 0은 가격 수준 0이 아니라 변화 없음입니다.

```json
{"model":"catboost","positions":[{"asset_id":"005930","value_krw":50000000},{"asset_id":"005380","value_krw":50000000}],"shocks":{"fx_pct":5,"us_rate_bp":100,"wti_pct":0,"vix_points":0}}
```

ML이 반환하는 5일 로그수익률(%)을 `100 × (exp(값 / 100) - 1)`로 변환하고 보유금액에 적용합니다. 무충격 손익과 충격 후 손익의 차이도 반환합니다. 종목 구간을 더해 포트폴리오 확률 구간으로 표시하지 않습니다.

현재 배포 ML의 지원은 18종목이며 `/support` 결과가 기준입니다. 충격별 기여도와 과거 사례는 현재 ML API에 없어 null과 이유를 반환합니다. 모델의 연구용 판정도 유지합니다. 이 연결 작업을 모델 승인이나 전체 서비스 완성으로 보지 않습니다.

로컬 검사는 Python 3.12에서 `python -m pytest services/ml-auth/test_service_auth.py services/api/tests services/debate/tests/test_api.py -q`로 실행합니다. Azure 실행 방법과 서버 인증과 복구 방법은 [배포 안내](../../infra/gateway/README.md)에 있습니다.
