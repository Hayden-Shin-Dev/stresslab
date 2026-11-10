# 종목 선정과 학습 목표 검증

[결과](결과.md)를 먼저 확인하세요. Azure와 Gold 계약은 변경하지 않았습니다.

종목별 결과는 per_asset.csv, 선정 종목은 selections.csv, 충격별 계수와 안정성은 sensitivity.csv에 있습니다. 기존 20종목과 학습 자료로 선정한 종목군을 구분했습니다.

Python 3.10에서 requirements.txt를 설치하고 STRESSLAB_AUDIT_ROOT를 연구 자료 폴더로 설정하세요. selection_target_research.py, summarize_selection_target.py, audit_selection_inputs.py 순서로 실행합니다.

입력 경로는 exports/seongjin_gold_v1_1/gold_stress_daily.parquet, reports/model_redesign_20261103/learning_table.parquet, reports/asset_feature_research_20261103/predictions.parquet, data/research/official20_20261102/universe.json입니다. 마지막 predictions는 기존 모델이 그대로 재현되는지 비교하는 기준입니다. 원본 가격은 공개 저장소에 포함하지 않았습니다. 로컬 재현 ZIP에 입력 자료와 결과가 들어 있습니다.

실험 3과 4는 독립 종목 모델의 선정된 부분집합입니다. 평가 대상이 달라져 평균이 좋아진 것을 동일 종목 모델의 개선으로 설명하지 않습니다.
