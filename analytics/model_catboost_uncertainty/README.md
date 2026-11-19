# CatBoost 수익률 분포

저장소 루트에서 아래 명령으로 실행합니다.

```powershell
.\analytics\model_ngboost\.venv\Scripts\python.exe analytics/model_catboost_uncertainty/train_uncertainty.py --out analytics/outputs/model_catboost_uncertainty_rerun
```

기존 D/E의 입력 10개, 변동성 정규화, 1·5·20거래일 표본과 시간 분할을 사용합니다. CatBoost `RMSEWithUncertainty`로 평균과 표준편차를 학습합니다. 원분포는 정규분포이고, 경험분포는 2020~2022년의 표준화 잔차로 꼬리와 손실 확률을 보정합니다.

기본 결과 폴더는 `analytics/outputs/model_catboost_uncertainty`입니다. 비교 기준은 보고서의 튜닝 설정을 같은 데이터에 다시 적용한 Model E와 저장된 NGBoost입니다. 쌍대 비교 차이는 후보에서 기준을 뺀 값입니다. 평가는 과거에 실현된 시장충격을 넣는 조건부 재구성이며 기존에 사용한 평가 구간입니다.
