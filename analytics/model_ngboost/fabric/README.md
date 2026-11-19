# Fabric에서 NGBoost 학습

`NB_Model_NGBoost_Train.ipynb`를 Fabric Spark 노트북으로 열고 위에서부터 실행합니다. 노트북에는 학습 소스와 Gold v1.1 계약 스키마가 포함돼 있습니다.

1. 설정에서 Gold 경로, 데이터셋 버전, 예측 기간과 분할을 확인합니다. 기본값은 기존 20종목 Fabric D/E 실험과 같은 학습 2023년까지, 보정 2024년, 평가 2025년 이후입니다. 로컬 D/E 분할을 쓰려면 보정 시작을 2020-01-01, 평가 시작을 2023-01-01로 설정합니다. 동일한 Gold 스냅샷을 쓸 때만 결과를 직접 대조할 수 있습니다.
2. 기본 Lakehouse로 `LH_StressLab_ML`을 연결하세요. 기본 입력은 이 Lakehouse의 `Files/gold/gold_stress_daily_reconciled_v142_20261105/gold_stress_daily.parquet`입니다. 실행 전에 해당 파일이 있는지 확인하세요. 다른 계약 적합 Gold를 같은 Lakehouse에 보관 중이라면 `GOLD_SOURCE`, `GOLD_FORMAT`, `DATASET_VERSION`을 그 입력에 맞춥니다. Spark에서 계약 컬럼을 선택한 뒤 기존 Gold 로더로 검증합니다.
3. Fabric 드라이버 전용 가상환경에서 NGBoost를 설치하고 1·5·20거래일을 학습합니다. 패키지 설치에는 Fabric 작업 영역에서 PyPI 또는 설정된 패키지 저장소에 접근할 수 있어야 합니다. 기본 설정은 같은 Gold와 분할로 튜닝 Model E도 재학습합니다.
4. `LH_StressLab_ML`의 `Files/stresslab/model_ngboost/runs/<실행 ID>`에서 모델과 결과를 확인합니다. `run_info.json`이 저장된 실행이 완료된 실행입니다.

출력은 연구용입니다. 평가에는 과거에 실현된 시장충격을 입력합니다.
