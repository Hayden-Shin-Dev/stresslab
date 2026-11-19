# Huber 회귀와 시장 상태·충격 상호작용

기존 10개 입력과 시장 상태 6개 × 충격 4개의 상호작용을 사용합니다. 학습 구간에서만 표준화와 Huber 회귀를 적합하고, 2020~2022년 정규화 잔차로 비대칭 예측구간을 보정합니다.

```powershell
.\.venv\Scripts\python.exe analytics/model_huber_interactions/train_huber_interactions.py --out analytics/outputs/model_huber_interactions_rerun
```

기본 출력은 `analytics/outputs/model_huber_interactions`입니다. 2023년 이후의 기존 평가 표본에 사후 실현 충격을 넣어 조건부 반응을 평가합니다.
