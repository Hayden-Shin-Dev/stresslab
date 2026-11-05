# 서비스 테스트 화면

기본 계산 모델은 충격 반영 업종 Ridge입니다. 정정 데이터의 동일 50종목과 85개 날짜, 4,150건을 비교한 뒤 선택했습니다.

| 모델 | MAE (%p) | 방향 일치율 | 급락 손실 과소평가 (%p) |
| --- | ---: | ---: | ---: |
| 선정한 업종 Ridge | 4.615 | 54.14% | 8.673 |
| CatBoost | 4.686 | 53.49% | 8.173 |
| Huber | 4.726 | 51.56% | 8.014 |
| 기존 부분 풀링 Ridge | 4.787 | 51.56% | 8.277 |
| 부분 풀링과 LightGBM 결합 | 5.745 | 47.73% | 11.608 |
| 0 수익률 기준선 | 4.621 | 해당 없음 | 8.838 |

방향은 실제 수익률이 0인 48건을 모두 제외한 기준입니다. 과거 표의 50.96%와 분모가 다릅니다. 급락은 실제 5거래일 수익률 -5% 이하입니다. 2023~2026년 반복 사용한 개발 평가이며 독립 검증이 아닙니다.

업종 Ridge는 비교 대상 중 MAE와 RMSE가 가장 낮고 방향 일치율이 가장 높으며, 네 충격의 기여도를 학습 계수로 그대로 설명할 수 있습니다. 다만 0 기준선보다 MAE가 약 0.12% 낮을 뿐이며 날짜 블록 신뢰구간은 0을 포함합니다. 급락에서는 CatBoost와 Huber보다 오차가 큽니다. 모든 지표에서 우수한 모델이라는 뜻은 아닙니다.

2025~2026년 동일 2,057건에서는 업종 Ridge MAE 5.329%p, 기존 Ridge 5.657%p, 0 기준선 5.285%p입니다. 기존 모델보다 개선됐지만 최근 기간의 기준선 열세는 해결되지 않았습니다. 전체 평균만으로 해결됐다고 판단하지 않습니다.

## 계산과 적용 범위

1. 시장 상태로 유사 과거 환경을 검색합니다. 검색에는 사용자 충격을 넣지 않습니다.
2. 각 종목이 속한 업종의 학습 계수에 네 충격을 곱합니다.
3. 무충격 모델값과 충격 기여도를 더하고, 보유금액에 적용합니다.
4. 과거 사례, 계수의 연도별 부호 안정성, 외삽 여부를 함께 표시합니다.

같은 학습 집단의 같은 업종은 같은 계수를 사용합니다. 종목 고유 민감도가 아닙니다. 시장 상태는 과거 근거 검색에 반영되지만 B의 계수를 바꾸지는 않습니다. 이 제약을 화면과 API에 반환합니다.

0은 지표 수준 유지입니다. 환율과 WTI는 %, 미국 10년 금리는 bp, VIX는 포인트입니다. 충격별 기여도의 합계는 무충격 대비 수익률 변화와 일치합니다.

과거 개별 범위를 벗어나거나 시장 상태와 충격 조합의 근거가 부족하면 해당 결과에 표시합니다. 선형 모델이 숫자를 반환한다는 이유로 극단 충격까지 검증됐다고 판단하지 않습니다. 확률적 손실 한도는 제공하지 않습니다.

## 실행

저장소 루트에서 기존 Python 환경을 활성화합니다. 경로는 실제 전달받은 모델 위치로 지정하세요.

```powershell
$env:PYTHONPATH = "$PWD/analytics/src"
$env:STRESSLAB_SELECTED_MODEL_DIR = "C:/모델경로/web_model_selection_20261105"
$env:STRESSLAB_TIERED_BUNDLE = "C:/이전모델경로/final_service_bundle.joblib"
$env:STRESSLAB_MODEL_MANIFEST = "$PWD/analytics/src/conditional_service/final_service_manifest.json"
python -m pip install -r analytics/src/conditional_service/requirements-research.txt
python -m uvicorn conditional_service.preview_api:app --host 127.0.0.1 --port 8157
```

http://127.0.0.1:8157 에서 테스트하세요. 새 모델 폴더에는 `selection.json`과 `selected_service_bundle.joblib`이 필요합니다. 이전 모델 파일은 데이터 검증 메타데이터 확인에만 사용하며 웹 손익 계산에는 사용하지 않습니다.

현재 시장 상태는 2026-10-30 고정값입니다. 계산 모델은 2026년 외표본 결과를 재현한 학습본을 그대로 사용합니다. 2025년 이전 정답과 20일 간격을 적용했고, 검증되지 않은 최신 재학습본으로 바꾸지 않았습니다.

## API와 검증

`GET /api/support`, `GET /api/model-info`, `POST /api/analyze`를 사용합니다. 요청은 기존 positions와 shocks 형식입니다. 응답 버전은 2.0이며 `coefficient_source=sector_proxy_not_individual_stock`, `sector`, `training_cohort`로 계수 출처를 구분합니다.

```powershell
python -m conditional_service.verify_preview --output ./preview-verification
```

기존 모델의 4,150건 예측을 다시 생성해 일치하는지 확인했습니다. HTTP 검증은 50종목, 무충격, 복합 충격, 극단 입력 표시, 기여도 합계와 금액 환산을 확인합니다. 결과는 `preview/selection.json`, `preview/comparison.csv`, `preview/verification.json`에 있습니다.

재현 코드는 `select_web_model.py`입니다. 기존 정정 데이터와 평가 파일이 있는 연구 작업 폴더에서 기본 실행으로 CatBoost 비교를 재현하고, `--select-sector`로 업종 Ridge 재현 및 서비스 모델 선택을 저장합니다. 신규 알고리즘이나 하이퍼파라미터 탐색은 없습니다.

Azure와 Gold는 변경하지 않았습니다. 공개 배포 전에 최신 확정 Gold 입력 경로, 인증 및 요청 제한을 연결해야 합니다. 기존 운영 API와 Ridge 파일도 보존했습니다.
