# 충격 국면별 분위수 혼합

종목 상태 CatBoost와 코스피 요인 분해 CatBoost의 원시 분위수, 기존 Huber 중심값을 입력으로 받습니다. 기반 모델은 2020년 이전으로 훈련되어 있습니다. 피처는 세 기반 모델의 피처를 사용하며 국면 분류를 위해 입력의 네 시장충격을 한 번 더 평가합니다.

- 2020년 이전 학습 표본에서 각 충격의 1%·99% 경계값을 계산합니다. 네 충격 중 하나라도 이 경계 밖인 행을 극단 국면으로 분류합니다.
- 2020~2021년에는 국면마다 세 중심값의 혼합 비중을 MAE로, 두 CatBoost 분위수의 혼합 비중을 pinball loss로 맞춥니다. 0.25 단위 가중치 격자를 사용합니다. 350행 또는 25개 기준일에 못 미치는 국면은 전체 표본 가중치를 사용합니다.
- 2022년에는 예측구간 위·아래를 각각 보정합니다. 같은 표본 수 기준으로 국면별 표본이 부족하면 전체 보정 구간의 값을 사용합니다.
- 2023년 이후에는 고정한 가중치와 보정값으로 평가합니다. 기준일과 정답 종료일이 분할 경계를 가로지르면 학습·보정의 앞 단계에서 해당 행을 제외합니다. 평가 충격은 과거 실현값입니다.

```powershell
.\.venv\Scripts\python.exe analytics/model_shock_gated_quantiles/train_shock_gated.py --out analytics/outputs/model_shock_gated_quantiles_rerun
```

결과는 기본값으로 `analytics/outputs/model_shock_gated_quantiles`에 저장됩니다. `run_info.json`은 선택된 국면별 가중치, `paired_differences.csv`는 전체 및 극단 국면의 동일 행 쌍대 비교를 담습니다.
