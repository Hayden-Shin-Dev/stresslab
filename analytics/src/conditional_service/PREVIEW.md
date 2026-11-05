# 서비스 테스트 화면

최종 고정 모델인 부분 풀링 Ridge를 호출합니다. 50종목과 환율, 미국 10년 금리, WTI, VIX의 단일 및 복합 충격을 지원합니다. 새로운 학습이나 모델 교체는 하지 않습니다.

## 화면에서 확인할 내용

1. 보유 종목과 현재 평가금액을 입력합니다.
2. 향후 5거래일의 충격 변화량을 입력합니다. 0은 해당 지표 수준 유지입니다. 금리는 bp, 환율과 WTI는 %, VIX는 포인트입니다.
3. 분석 실행을 누르면 기준 손익, 충격에 따른 변화, 최종 가상 손익이 표시됩니다.
4. 종목별 계산 근거를 펼치면 실제 학습 계수와 기여도를 확인할 수 있습니다. 계수에 입력 충격을 곱한 기여도의 합계가 수익률 변화와 같습니다.
5. 과거 사례는 시장 상태로 후보를 찾고 그 안에서 충격이 가까운 사례를 표시합니다. 이 검색으로 Ridge 결과를 다시 보정하지 않습니다.

## 실행

저장소 루트에서 기존 Python 환경을 활성화하고 실행합니다. 모델 파일은 별도로 받은 검증된 파일의 절대 경로를 지정하세요. 공개 저장소에는 모델을 추가하지 않았습니다.

```powershell
$env:PYTHONPATH = "$PWD/analytics/src"
$env:STRESSLAB_TIERED_BUNDLE = "C:/모델이있는경로/final_service_bundle.joblib"
$env:STRESSLAB_MODEL_MANIFEST = "$PWD/analytics/src/conditional_service/final_service_manifest.json"
python -m pip install -r analytics/src/conditional_service/requirements-research.txt
python -m uvicorn conditional_service.preview_api:app --host 127.0.0.1 --port 8157
```

브라우저에서 http://127.0.0.1:8157 을 여세요. 화면과 API가 같은 서버에서 실행되므로 별도의 API 주소나 키를 입력하지 않습니다. 실행 환경은 기존 서비스의 requirements를 사용합니다.

```powershell
python -m conditional_service.verify_preview --output ./preview-verification
```

이 명령은 50종목 계산, 네 충격 합계, 금액 환산, 무충격, 극단 입력 표시, 잘못된 입력 거부를 실제 HTTP로 확인합니다. 모델 성능을 새로 검증하는 명령은 아닙니다.

## 모델 상태

모델 SHA-256은 `d1574cc88a1aece3863dbf5d63eb7c21d03b1a8062d8481f11b8fe00d82ef4f0`입니다. 다른 모델이면 성능표를 표시하지 않습니다.

| 기존 개발 평가 | 결과 |
| --- | ---: |
| 범위 | 50종목, 85개 날짜, 4,150건 |
| 중심 수익률 MAE | 4.787%p |
| 방향 일치율 | 50.96% |
| 0 수익률 기준선 MAE | 4.621%p |
| 급락 시 손실 과소평가 평균 | 8.277%p |

2023~2026년 반복 사용한 개발 평가이며 독립 블라인드 결과가 아닙니다. 기준선보다 오차가 커서 정확한 손실 예측으로 승인한 모델은 아닙니다. 학습 계수에 따른 가상 시나리오를 확인하는 탐색용 화면입니다. 위험 구간은 표시하지 않습니다.

현재 입력 시장 상태는 2026-10-30의 고정 스냅샷입니다. 실시간 현재 시장으로 표시하지 않습니다. API 원본에서 피처별 관측일과 검증 상태를 확인할 수 있습니다.

## Azure 연결 전

이 화면은 실제 API와 연결됐지만 Azure에는 배포하지 않았습니다. 사용자가 화면을 확인한 다음 기존 서비스 배포 방식에 맞춰 웹과 API를 연결합니다. HTML만 올리면 계산되지 않으므로 모델 파일과 API 실행 환경도 필요합니다. 공개 배포 전에는 인증과 요청 제한을 확인하고, 최신 확정 Gold를 읽는 시장 상태 갱신 경로를 별도로 연결해야 합니다.
