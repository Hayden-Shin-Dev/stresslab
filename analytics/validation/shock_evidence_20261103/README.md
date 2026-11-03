# 충격 데이터 근거 진단

[결과](결과.md)를 확인하세요. 새 모델을 학습하지 않고 실제 충격 분포와 저장된 외표본 결과를 분석했습니다. Azure와 Gold 계약은 변경하지 않았습니다.

shock_counts.csv는 충격 횟수, asset_observed_responses.csv는 종목별 관측 반응, historical_sensitivity.csv는 기간별 계수, shock_increment_by_asset.csv는 충격 추가 전후 비교입니다.

diagnose_shock_evidence.py는 기존 연구 폴더의 scripts에서 실행합니다. exports/seongjin_gold_v1_1, reports/model_redesign_20261103, reports/asset_feature_research_20261103, reports/selection_target_20261103과 data/research/official20_20261102/universe.json을 읽습니다. numpy와 pandas가 필요합니다. 원본 가격과 개별 평가 입력은 공개 저장소에 올리지 않았습니다.
