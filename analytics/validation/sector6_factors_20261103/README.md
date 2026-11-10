# 항공, 정유, 화학 공식 데이터 검증

[결과](결과.md)를 확인하세요. 기존 20종목은 보존하고 새 6종목을 별도로 평가했습니다. 운영 모델이나 Gold 계약을 변경하지 않았습니다.

수집은 별도 pykrx 환경에서 collect_sector6_krx.py로 실행합니다. 승인된 로컬 .env의 KRX_ID와 KRX_PW를 읽으며 인증값은 출력하지 않습니다. KRX 외 도메인은 차단합니다.

학습 환경은 requirements.txt를 사용합니다. 파일을 연구 폴더의 scripts에 두고 evaluate_sector6_factors.py, summarize_sector6_factors.py, audit_sector6_oil.py 순서로 실행합니다. 첫 스크립트는 종목별 작업을 4개 로컬 프로세스로 나눕니다. 체크포인트는 동일 자료와 설정의 중단 재개용입니다. 설정이나 입력을 바꿨다면 기존 결과를 보존하고 별도 실행 폴더를 사용하세요.

입력은 data/research/sector6_20261103의 공식 원본, exports/seongjin_gold_v1_1/gold_stress_daily.parquet, reports/model_redesign_20261103/learning_table.parquet, reports/asset_feature_research_20261103/predictions.parquet 및 center_ablations.csv, data/research/official20_20261102/universe.json입니다. 원본 가격은 공개 저장소에 포함하지 않았으며 로컬 재현 ZIP에 보관했습니다.

per_asset_metrics.csv는 종목별 오차와 구간, factor_comparisons.csv는 변수 하나씩 추가하거나 제외한 결과입니다. mode=single은 상태에 하나 추가, mode=drop은 다른 세 충격에 해당 변수를 추가한 비교입니다. improvement_pct가 양수면 오차 감소, 음수면 악화입니다. bh_q_global은 전체 416개 비교에 대한 탐색적 다중 비교 보정값입니다.

new6_common_date_reactions.csv는 같은 날짜의 실제 반응이고 new6_sensitivity.csv는 학습 기간의 통제 회귀입니다. 두 자료 모두 인과효과나 미래 확률을 의미하지 않습니다.
