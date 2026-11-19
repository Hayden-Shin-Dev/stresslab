# CatBoost 손실확률 분류

저장소 루트에서 아래 명령으로 실행합니다.

```powershell
.\analytics\model_ngboost\.venv\Scripts\python.exe analytics/model_catboost_loss_classifier/train_loss_classifier.py --out analytics/outputs/model_catboost_loss_classifier_rerun
```

D/E와 같은 10개 입력과 1·5·20거래일 표본을 사용합니다. 일반 수익률이 −5%, −10% 이하인 사건을 각각 분류하고, 2020~2022년 보정 구간에서 로지스틱 보정을 적합합니다. 두 사건 확률의 순서가 뒤집힌 경우 같은 중간값으로 조정합니다.

기본 결과 폴더는 `analytics/outputs/model_catboost_loss_classifier`입니다. 기존 NGBoost와 학습 구간 평균 발생률을 Brier 점수, 로그 손실, ROC AUC로 비교합니다. 평가는 과거에 실현된 시장충격을 넣는 조건부 재구성이며 기존에 사용한 평가 구간입니다.
