# 종목 상태와 거시 민감도를 활용하는 CatBoost

기존 시장 상태와 네 충격에 한국 국고채 3년물, 종목 변동성, 추세·낙폭, 종목 식별자·업종, 코스피와 거시 변수에 대한 최근 민감도를 추가합니다. 종목 피처는 유효한 수정주가를 한국 거래일 달력에 맞춰 기준 거래일까지 계산합니다. 신호가 부족한 구간의 추가 수치는 CatBoost의 결측 처리를 사용합니다.

1·5·20거래일 각각에 대해 7개 분위수를 학습합니다. 2017~2019년 데이터로 반복 수를 선택한 뒤 2020년 이전 전체에서 재학습합니다. 2020~2022년에는 구간의 두 꼬리를 각각 보정합니다. 2023년 이후는 기존 개발 평가 표본으로, 실제 관측 충격을 입력하는 조건부 재구성입니다. 거시 자료의 과거 공개 시각 검증 여부는 기존 Gold의 제한을 따릅니다.

```powershell
.\.venv\Scripts\python.exe analytics/model_catboost_asset_state/train_asset_catboost.py --out analytics/outputs/model_catboost_asset_state_rerun
```

기본 출력은 `analytics/outputs/model_catboost_asset_state`입니다. `metrics.csv`는 종합 및 충격 국면별 점수, `paired_differences.csv`는 동일 평가 행의 모델 간 오차 차이와 블록 부트스트랩 구간입니다. 재학습한 튜닝 Model E와 저장된 NGBoost·Huber·LightGBM을 비교합니다. 음의 차이는 새 모델의 해당 손실이 더 낮았음을 뜻합니다.
