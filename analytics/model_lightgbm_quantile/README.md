# LightGBM 분위수 회귀

LightGBM으로 분위수 일곱 개를 학습하고 2020~2022년 표본에서 분할 conformal 보정을 적용합니다. D/E의 동일한 10개 입력과 변동성 정규화를 사용합니다. 저장된 기본 E와 NGBoost에 대해 동일한 평가 행을 확인한 후 쌍대 비교를 수행합니다. 튜닝된 E의 지표는 기존 실험의 집계값을 기록합니다.

```powershell
.\.venv\Scripts\python.exe analytics/model_lightgbm_quantile/train_lightgbm_quantile.py --out analytics/outputs/model_lightgbm_quantile_rerun
```

기본 출력은 `analytics/outputs/model_lightgbm_quantile`입니다. 2023년 이후의 기존 평가 표본에서 사후 실현 충격을 입력하는 조건부 재구성 실험입니다.
