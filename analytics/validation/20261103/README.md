# 로컬 검증 기록

결론은 [RESULT.md](RESULT.md)에 정리했습니다. 서비스에 배포하는 코드가 아닙니다.

`reference/stresslab`은 이번 평가에서 사용한 기존 구현의 복사본입니다. 기존 설정의 ETF 이름은 재현을 위해 보존했지만 평가 대상은 sample_counts.csv의 20종목이며, 실제 학습 평가는 18종목입니다.

실행에는 Python, numpy, pandas, scikit-learn, pyarrow가 필요합니다. `STRESSLAB_AUDIT_ROOT` 환경변수에 로컬 검증 작업 폴더를 지정하고 아래 순서로 실행하세요.

```
python validate_market_search_and_stress.py
python summarize_search_stress_validation.py
```

입력 파일은 해당 작업 폴더 아래의 `reports/official20_20261102/official_panel.parquet`, `reports/official20_20261102/predictions.parquet`, `exports/seongjin_gold_v1_1/gold_stress_daily.parquet`입니다. 원본 금융 데이터는 이 공개 폴더에 복제하지 않았습니다. 데이터 해시는 protocol.json에 있습니다. Gold 하나만으로 이 기존 평가 패널을 재현할 수 있다는 뜻은 아닙니다.

원본 단위 평가 결과는 로컬 `reports/search_stress_validation_20261103/predictions.parquet`에 있습니다. 비교 요약과 실행 코드는 이 폴더에 보존했습니다. 날짜를 묶어 재표집한 비교이며 종목별 결과를 독립 표본으로 취급하지 않습니다.
