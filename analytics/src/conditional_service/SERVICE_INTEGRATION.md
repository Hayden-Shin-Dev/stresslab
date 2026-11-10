# 서비스 API 연결

50종목과 네 충격을 유지합니다. 용도는 학습된 민감도로 충격 전후 가상 손익을 비교하는 것입니다. 미래 수익률 예측 성능이나 손실 확률이 승인됐다는 뜻은 아닙니다. Azure와 Gold는 변경하지 않았습니다.

## 이번에 완료한 부분

공표 근거를 확인한 정정 데이터로 기존 설정 그대로 재학습했습니다. 입력과 정답 재계산, 날짜 경계, 충격 단위, 미래 데이터 차단, 계수 유한성 검사를 통과했습니다. 수정주가 연결 검증 범위는 [SOURCE_CERTIFICATION.md](SOURCE_CERTIFICATION.md)에 있습니다.

재학습 결과는 이전 정정 버전과 동일합니다. 85개 평가 날짜, 4,150개 종목 관측에서 MAE는 4.787%p이며 0 수익률 기준선은 4.621%p입니다. 성능이 개선됐다고 표시하지 않습니다. 기존 예측 성능 승인 기준도 통과하지 못했습니다.

로컬 기본 모델은 `reports/service_scope_20261105/final_service_bundle.joblib`입니다. 이전 모델은 보존했습니다. 모델 SHA256은 매니페스트와 대조합니다. 공표 근거가 없거나 미래 관측이 포함되면 분석을 503으로 차단합니다.

## 실행

팀 저장소 폴더에서 실행하세요. 모델 파일은 아래 연구 폴더에 별도로 보관하며 Git에는 올리지 않습니다. 다른 개발자는 해당 모델 파일도 전달받아야 합니다.

```powershell
$env:PYTHONPATH = "$PWD\analytics\src"
$env:STRESSLAB_TIERED_BUNDLE = "$PWD\..\새로운 프로젝트 2\reports\service_scope_20261105\final_service_bundle.joblib"
$env:STRESSLAB_MODEL_MANIFEST = "$PWD\analytics\src\conditional_service\final_service_manifest.json"
& "..\새로운 프로젝트 2\.venv\Scripts\python.exe" -m uvicorn conditional_service.api:app --host 127.0.0.1 --port 8140
```

`/docs`에서 요청을 실행할 수 있습니다. `conditional_service.tiered_service:app`도 같은 계산 경로를 사용합니다.

| API | 용도 |
| --- | --- |
| `GET /support` | 지원 종목 코드와 이름 확인 |
| `GET /model-info` | 모델 버전, 데이터 기준, 성능 승인 여부 확인 |
| `POST /analyze` | 시장 근거부터 종목별 가상 손익까지 한 번에 계산 |

실제 요청과 응답은 [service_evidence/service_scope](service_evidence/service_scope)에 있습니다. 보유금액은 원, 환율과 WTI는 변화율 %, 미국 금리는 bp, VIX는 포인트입니다. 금리 100bp는 1%p 상승입니다. 생략한 충격은 0이며 해당 변수의 기존 수준 유지입니다.

## 화면에서 사용할 값

| 응답 | 의미 |
| --- | --- |
| `assets[].sensitivities` | 네 충격의 학습 계수, 공통 계수와 종목 편차, 안정성 |
| `assets[].comparison` | 무충격 기준값, 충격 적용값, 두 값의 차이와 각각의 손익 |
| `assets[].shock_contribution_pnl_krw` | 충격별 추가 손익. 합계는 해당 종목의 충격 전후 손익 차이입니다. |
| `assets[].evidence_summary` | 계수 불안정, 관측 범위 이탈, 과거 검증 오차 |
| `portfolio_summary` | 전체 기준 손익, 충격 적용 손익, 추가 손익, 종목별 및 충격별 기여도 |
| `assets[].historical_examples` | 실제 과거 사건의 충격과 종목 반응. 사용자 시나리오의 정답은 아닙니다. |
| `data_status` | 시장 기준일, 실제 관측일, 사용 가능 시각 근거 |

예를 들어 기준 모델 수익률이 1%, 충격 기여도가 -3%p라면 충격 적용 수익률은 -2%입니다. 보유금액 100만 원의 기준 손익은 +1만 원, 충격 적용 손익은 -2만 원, 충격 때문에 달라진 모델 손익은 -3만 원입니다. 무충격 기준 수익률을 0으로 처리하지 마세요.

손실 집중 비중은 충격 전후 손익 차이가 음수인 종목들의 손실 합계가 분모입니다. 이익 종목으로 상계한 순손익을 분모로 쓰지 않습니다. 손실 종목이 없으면 비중과 최대 손실 종목은 NULL입니다.

시장 검색 A는 충격을 사용하지 않습니다. B는 같은 확정 일별 상태와 사용자 충격으로 계산합니다. A의 사례를 이용해 B를 다시 학습하거나 가중 보정하지 않습니다. 과거 근거와 모델 계산을 구분해서 표시하세요.

## 오류와 남은 연결 작업

미지원 종목, 중복 종목, 잘못된 입력은 422입니다. 모델 누락, 해시 불일치, 데이터 근거 누락은 503입니다. 오류를 손익 0으로 표시하지 마세요.

현재 시장 기준일은 2026-10-30으로 고정돼 있습니다. 최신 시장으로 표시하면 안 됩니다. 결과는 탐색용 가상 시나리오이며 확정 손실 한도나 미래 손익 확률을 제공하지 않습니다. `production_approved=false`는 유지합니다.

React와 모바일은 같은 도메인의 백엔드 또는 개발 프록시를 통해 호출하면 됩니다. 다른 도메인 직접 호출의 CORS, 인증, Azure 배포와 최신 확정 Gold 상태 연결은 아직 수행하지 않았습니다. 이번 완료 범위는 로컬 API 통합입니다.

## 검증

50종목의 무충격, 15개 충격 조합, 극단 충격까지 850개 계산을 실제 HTTP로 확인했습니다. 추가로 서로 다른 보유금액의 합산, 충격 부호 반전, 보유금액 두 배 적용, 충격 변경 시 A 검색 유지와 동일 설정 재학습의 재현성을 검사했습니다.

연구 폴더에서 `PYTHONPATH`를 지정한 뒤 아래 명령으로 검사합니다. 학습을 다시 실행하는 명령은 아닙니다.

```powershell
$env:STRESSLAB_REBUILD_OUT = "reports/service_scope_20261105"
$env:STRESSLAB_VERIFICATION_OUT = "reports/service_scope_20261105"
python -m conditional_service.audit_service_inputs
python -m conditional_service.verify_pit_rebuild
python -m conditional_service.verify_scenario_scope
```

검사 통과는 계산 정합성 확인입니다. 민감도의 인과효과나 향후 성능을 입증한 것은 아닙니다.

## 추가 연구 후보

기본 모델은 그대로입니다. 별도 Huber 후보의 비교 결과와 실행 방법은 [ROBUST_CANDIDATE.md](ROBUST_CANDIDATE.md)에 있습니다. 후보의 개선 수치를 기본 모델 성능으로 표시하지 마세요.
