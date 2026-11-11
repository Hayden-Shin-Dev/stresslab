# Gold 시점 근거 연결

2026-11-10 민철 수정입니다. ML Notebook, 모델, Gold 34컬럼과 예약 설정은 변경하지 않았습니다.

## 처리 순서

1. 기존 Bronze 수집에서 FRED 빈티지와 한국은행·연준 공식 문서를 보관합니다.
2. Silver에서 값, 관측일, 공개 근거를 연결합니다.
3. Gold는 분석일 15:30 KST까지 사용 가능했던 자료 중 가장 최근 관측을 선택합니다. 나중에 공개된 값이나 수정된 값을 과거에 소급하지 않습니다.
4. 원문 해시, 값, 관측일, 이용 가능 시점, 빈티지 유효기간을 검사합니다. 근거가 없거나 오래된 값은 제외합니다. 거래일 행은 삭제하지 않습니다.

현재 Gold 테이블은 `lh_whatif.gold_stress_daily`입니다. 기존 파이프라인이 실행될 때마다 같은 검사가 적용됩니다.

## 시간값의 의미

- `*_available_at`: 공식 문서에서 확인한 실제 공개 알림 시각만 기록합니다.
- `provenance.parquet`의 `known_by`: 그 값이 사용 가능했다고 판단하는 기준입니다. 실제 공개 알림과 보수적 날짜 상한을 `evidence_precision`, `availability_basis`로 구분합니다.
- FRED 빈티지 날짜의 36시간 뒤, 한국은행 문서 등록일의 다음 날 같은 기존 로컬 기준을 사용합니다. 이를 실제 공표 시각으로 복사하지 않습니다.
- `*_observed_at`: 실제 관측 시각을 확인한 경우만 기록합니다. 일별 관측 날짜는 `*_observation_date`에 있습니다.

따라서 정확한 시각이 NULL이어도 날짜별 공식 근거로 사용 가능함을 검증할 수 있습니다. 근거 없는 NULL을 통과시킨다는 의미는 아닙니다.

## 확인할 파일

`Files/gold_evidence/gold_stock_market_daily_v11/latest.json`이 가리키는 버전 폴더를 사용하세요.

| 파일 | 용도 |
|---|---|
| `gold.parquet` | 테이블과 같은 34컬럼 데이터 |
| `provenance.parquet` | 날짜·지표별 선택한 값과 사용 가능 근거 |
| `input_eligibility.parquet` | 행별 입력 가능 여부와 제외 사유 |
| `publication_ledger.parquet` | 해당 실행에 사용한 공개·수정 이력 |
| `availability_certificate.json` | 시점 검사 결과와 적용 정책 |
| `certificate.json` | 데이터와 근거 파일의 해시 |

피처와 5거래일 정답은 전체 거래일 달력에서 계산한 후 제외 마스크를 적용해야 합니다. 발표 지연 때문에 지표별 실제 관측일이 다를 수 있습니다. 분석일을 지표의 관측일로 바꾸면 안 됩니다. 미래 충격 정답은 시장 상태 입력과 분리하고 학습 시점까지 공개됐는지 별도로 확인해야 합니다.

이번 검증 범위는 거시 입력의 당시 이용 가능 여부입니다. 가격의 전체 수정 이력, 업종의 역사적 분류, 모델 성능 승인까지 완료됐다는 표시로 사용하지 않습니다. `historical_availability_verified`를 일괄 True로 바꾸지 않습니다.

## 실제 실행 확인

2026-11-10 수동 전체 실행과 11-11 오전 8시 예약 실행이 완료됐습니다. 최신 Gold는 11-10 기준 20종목이며, 전체 103,049행 중 68,162행이 입력 검사를 통과했습니다. 나머지 34,887행은 삭제하지 않고 제외 표시했습니다. 피처 계산과 정답 생성 이후 학습 행 수는 별도로 줄어들 수 있습니다.

34컬럼 계약과 기존 가격·거래일을 유지했고, Gold Delta 테이블과 스냅샷의 값이 일치했습니다. 같은 공식 원장으로 로컬에서 다시 계산한 결과도 일치했습니다. 정확한 공개 시각이 확보된 경우와 날짜 기준만 확보된 경우는 [출처별 조사](TIMESTAMP_SOURCES.md)에 구분했습니다.

근거를 적용하면서 과거 거시 입력 값과 시차가 달라졌습니다. 기존 모델 성능 수치를 이 데이터의 검증 성능으로 그대로 사용하면 안 됩니다. 이번 작업에서는 ML 학습과 Notebook을 수정하지 않았습니다.

## 코드와 검사

선택 및 검증은 `gold_availability.py`, 기존 시점·신선도 규칙은 `availability_policy.py`, 공식 수집은 `publication_evidence.py`에 있습니다. 변경 위치에는 날짜와 수정 설명을 남겼습니다.

```powershell
python -m unittest discover -s fabric/batch/quality -p test_gold_availability.py
python -m unittest discover -s fabric/batch/quality -p test_publication_evidence.py
```
