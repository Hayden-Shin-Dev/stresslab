# 최종 서비스 연결

현재 모델은 `final_service_bundle.joblib`로 고정했습니다. 재학습하지 않습니다. 50종목과 네 충격을 한 번에 계산합니다. 모델 파일은 저장소에 올리지 않았으며, `final_service_manifest.json`의 SHA256과 일치하는 파일만 실행됩니다.

## 완료 범위

시장 비교 A는 충격을 제외한 일별 시장 상태로 과거 사례를 찾습니다. B는 같은 상태에서 고정된 종목별 계수로 손익을 계산합니다. A의 검색 결과로 B를 다시 학습하거나 가중 보정하지 않습니다.

`POST /analyze` 한 번으로 민감도, 무충격 기준값, 충격별 기여도, 가상 손익, 포트폴리오 합계와 과거 사례를 받습니다. 과거 사례의 실제 충격은 사용자 충격과 다를 수 있습니다. 사례에는 시작일과 5거래일 뒤 종료일이 함께 있습니다.

## 데이터 확인 결과

공식 원본 재확인 결과와 남은 배포 조건은 [SOURCE_CERTIFICATION.md](SOURCE_CERTIFICATION.md)에 정리했습니다. 수정주가 검증과 공표 시각 검증은 별도로 판단합니다.

FRED의 과거 수정 이력과 날짜가 있는 한국은행 자료를 추가 확보했습니다. 날짜만 확인되는 경우 정확한 공표 시각을 만들지 않고 보수적인 사용 가능 경계를 따로 기록합니다. `available_at`은 알 수 없으면 NULL입니다.

`available_asof`는 근거가 있는 관측값 중 기준 시각 이전 값만 선택합니다. 이전 값으로 바꾼 이력은 별도 수정안이며, 기존 Gold나 고정 모델에 자동 적용하지 않았습니다. 학습 입력이 바뀌면 기존 계수의 학습 정합성을 다시 확인해야 하기 때문입니다.

`STRESSLAB_REQUIRE_CERTIFIED_DATA=1`로 실행하면 공표 검증이 끝나지 않은 모델의 `/analyze`는 503을 반환합니다. 운영 연결 전 이 검사를 통과해야 합니다. `/model-info`는 차단 사유 확인을 위해 계속 조회할 수 있습니다.

현재 API는 고정된 2026-10-30 연구 상태를 사용합니다. 최신 시장이나 배포 승인 모델로 표시하지 않습니다. `data_status`에 관측일, 모델 기준일, 출처 검증 결과와 남은 차단 사유가 함께 반환됩니다.

## 실행

팀 저장소 폴더의 PowerShell에서 실행합니다. 아래 Python은 기존 연구 환경입니다.

```powershell
$env:PYTHONPATH = "$PWD\analytics\src"
$env:STRESSLAB_TIERED_BUNDLE = "$PWD\..\새로운 프로젝트 2\reports\final_model_20261104\final_service_bundle.joblib"
& "..\새로운 프로젝트 2\.venv\Scripts\python.exe" -m uvicorn conditional_service.api:app --host 127.0.0.1 --port 8140
```

`conditional_service.tiered_service:app`도 같은 모델과 응답을 사용합니다. `/docs`에서 API를 확인할 수 있습니다.

| API | 사용 방법 |
| --- | --- |
| `GET /support` | 지원 50종목의 코드와 이름을 가져옵니다. |
| `GET /model-info` | 모델 해시, 연구 종료 결정, 데이터 기준과 배포 차단 사유를 확인합니다. |
| `POST /analyze` | 보유금액과 충격으로 전체 분석을 실행합니다. |

요청은 `service_evidence/example_request.json`, 실제 응답은 `example_response.json`, 형식은 `openapi.json`에 있습니다.

```json
{
  "positions": [{"asset_id": "000120", "value_krw": 1000000}],
  "shocks": {"fx_pct": 5, "us_rate_bp": 100, "wti_pct": 10, "vix_points": 5}
}
```

종목 코드는 `/support`에서 선택하세요. 금액은 원입니다. 환율과 유가는 변화율 %, 미국 금리는 bp, VIX는 포인트입니다. 생략한 충격은 0이며 기존 수준 유지입니다. 금리 100bp는 1%p 상승입니다.

## 화면에 연결

| 응답 | 표시할 값 |
| --- | --- |
| `sensitivities` | 네 충격별 계수, 공통 계수와 종목 편차, 근거 수준 |
| `baseline_model_return_pct` | 네 충격이 모두 0인 모델 수익률 |
| `contributions_pp` | 충격별 수익률 변화분. 합계는 `change_from_baseline_pp`입니다. |
| `scenario_return_pct` | 기준 수익률 + 충격 변화분 |
| `hypothetical_pnl_krw` | 보유금액 × 충격 적용 후 수익률 / 100 |
| `shock_incremental_pnl_krw` | 충격 입력으로 추가된 손익. 전체 손익과 다릅니다. |
| `portfolio_hypothetical_pnl_krw` | 종목별 전체 가상 손익의 합계 |
| `historical_examples` | 실제 과거 충격과 종목 반응. 사용자 시나리오의 정답은 아닙니다. |

React에서는 개발 프록시나 같은 도메인의 백엔드를 통해 호출하세요. API 키를 브라우저에 넣지 않습니다. 로컬에서 다른 포트로 직접 호출할 경우 CORS 설정이 별도로 필요합니다. 이번 작업은 Azure 설정을 변경하지 않았습니다.

```typescript
const response = await fetch('/analyze', {
  method: 'POST',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({positions, shocks})
});
const result = await response.json();
if (!response.ok) throw new Error(JSON.stringify(result.detail));
// result.assets를 종목별로 표시하고 result.data_status도 함께 표시합니다.
```

미지원 종목, 중복 종목, 잘못된 충격은 422입니다. 모델 파일 누락, 해시 불일치, 계산 자료 누락은 503입니다. 오류를 손익 0으로 표시하지 마세요. 현재 결과는 모두 탐색용이며 확정 손실 한도나 미래 수익 보장이 아닙니다.

## 로컬 검증

연구 폴더에서 `python -m conditional_service.verify_final_integration`을 실행합니다. 임시 포트에서 HTTP 서버를 실행하고 종료합니다. 50종목의 무충격, 15개 충격 조합, 극단 충격까지 850개 계산을 확인합니다. 손익 합산, 기여도 합계, A 검색 유지, 오류 응답과 모델 해시도 검사합니다.

가격 대조는 `python -m conditional_service.audit_final_price_paths`입니다. 두 검증 모두 학습하거나 Azure에 접속하지 않습니다. 결과는 `reports/service_integration_20261104`에 저장됩니다.
