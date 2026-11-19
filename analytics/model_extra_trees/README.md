# ExtraTrees 수익률 회귀

무작위 분할 트리의 평균으로 중심 수익률을 학습합니다. 2020~2022년의 정규화 잔차로 하단과 상단을 별도 보정해 예측구간을 만듭니다. 입력·분할·평가 코드와 비교 기준은 LightGBM 실험과 같습니다.

```powershell
.\.venv\Scripts\python.exe analytics/model_extra_trees/train_extra_trees.py --out analytics/outputs/model_extra_trees_rerun
```

기본 출력은 `analytics/outputs/model_extra_trees`입니다. 2023년 이후의 기존 평가 표본에서 사후 실현 충격을 입력하는 조건부 재구성 실험입니다.
