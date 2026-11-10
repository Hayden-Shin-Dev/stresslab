# 종목별 모델 비교

[결과](결과.md)를 먼저 확인하세요. 운영 모델 승인 결과가 아닙니다.

실행은 Python 3.10 환경에서 requirements.txt를 설치한 뒤 진행합니다. STRESSLAB_AUDIT_ROOT를 로컬 연구 자료 폴더로 지정하세요. model_redesign_research.py, complete_redesign_sensitivity.py, summarize_model_redesign.py 순서입니다.

필요한 자료는 exports/seongjin_gold_v1_1/gold_stress_daily.parquet와 reports/asset_feature_research_20261103/predictions.parquet입니다. 요약 감사에는 data/v4/official/dart_industry_codes.json과 같은 상위 폴더의 stresslab-team/contracts/daily/schema.json도 사용합니다. 원본 자료는 공개 저장소에 포함하지 않았습니다. 로컬 재현 ZIP에 입력과 기존 비교 결과가 들어 있습니다.

학습 입력은 시장 상태, 종목별 추세와 변동성, 실제 발생한 5일 충격입니다. 정답은 같은 5일의 종목 수익률입니다. 실서비스에서는 실제 미래 충격 대신 사용자의 가정을 입력합니다. 공표 시각 누락과 반복 사용한 평가 기간의 한계가 있으므로 독립 블라인드 검증으로 표시하지 않습니다.
