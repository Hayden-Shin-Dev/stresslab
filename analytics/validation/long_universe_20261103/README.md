# 장기 이력 수집 및 종목 재선정

현재 수집 중입니다. 학습 및 성능 검증 완료 보고서가 아닙니다.

2000년부터 2026-10-30까지 KRX 공식 가격을 확보합니다. 이후 상장 종목은 실제 관측 시작일부터 사용합니다. 206개는 조사 후보이며 모두 학습 대상으로 채택하는 것이 아닙니다. 이전 101종목 선정은 최종 목록으로 사용하지 않습니다.

수집 완료 후 2021년까지의 자료만으로 충격 반응의 반복성, 방향 일관성, 충격 추가의 설명력, 데이터 품질을 확인합니다. 사전 기준을 통과한 종목과 충격 조합을 모두 선택하며 상위 개수를 억지로 채우지 않습니다. 2023~2026년 평가 결과로 종목을 다시 고르지 않습니다.

실행 순서는 collect_long_universe.py --selected, select_long_universe.py, train_long_universe.py, report_long_universe.py입니다. 현재 run_long_universe_pipeline.py가 수집 완료를 기다렸다가 나머지를 실행합니다. 수집 실패 또는 기준 통과 종목이 없으면 학습을 강행하지 않습니다.

로컬 reports/long_universe_20261103/collection_progress.json에서 수집 진행을, pipeline_status.json에서 전체 단계를 확인할 수 있습니다. 기존 원본, 모델, 평가 결과는 보존합니다. Azure, Gold, main은 변경하지 않습니다.

기존 연구 코드 asset_feature_research.py, select_exposure_universe.py, reselect_shock_direction.py가 필요합니다. 원천 데이터와 인증정보는 저장소에 올리지 않습니다.
