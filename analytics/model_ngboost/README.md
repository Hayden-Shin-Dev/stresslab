# NGBoost 조건부 스트레스 모델

저장소 최상위에서 기존 analytics 환경으로 실행합니다.

```powershell
.\.venv\Scripts\python.exe -m pip install -r analytics/model_ngboost/requirements.txt
.\.venv\Scripts\python.exe analytics/model_ngboost/train.py
```

기본값은 1·5·20거래일 모델 세 개를 별도로 학습하고 `analytics/outputs/model_ngboost`에 기록합니다.
재실행할 때는 `--out`으로 새 디렉터리를 지정합니다. 5거래일만 실행하려면 `--horizons 5`를 지정합니다.
`--compare-tuned-e`를 추가하면 기존 튜닝 설정으로 Model E를 다시 학습해 같은 평가 행에서 비교합니다.
비교에는 해당 실험의 CatBoost 백엔드와 `analytics/outputs/model_de/tuning/best_params.json`이 필요합니다.

## 학습 입력과 분할

- Gold 로더, `features.py`, D/E의 `horizon_samples.py`와 `common.Context`를 공유합니다. 기본 Gold는 `data/dev_gold/gold_stress_daily.parquet`입니다.
- 입력 순서는 D/E와 같은 10개입니다. 원/달러·WTI 비율 변화(%), 미국 10년 금리 변화(bp), VIX 차이(포인트)를 각 예측 기간의 누적 충격으로 사용합니다. 상태는 코스피 20일 변동성·추세, VIX 수준, 미국 10년 금리 수준, 원/달러 20일 추세, WTI 수준입니다. 한국 3년 금리 피처는 공통 테이블에서 계산되며 D/E 기본 비교 입력은 10개를 사용합니다.
- 각 충격은 시점 t의 코스피 변동성 척도로 나눕니다. 정답은 한국 거래일 달력 기준 `100 × ln(close[t+h] / close[t])`이며 종목 변동성 척도로 나눠 학습합니다. 척도는 D/E처럼 20·60일 분산의 평균에 기간을 곱한 뒤 제곱근을 구하고 하한 0.05를 적용합니다. 출력은 종목 척도를 다시 곱한 로그수익률(%)입니다.
- 학습은 2020년 이전, 구간 보정은 2020~2022년, 평가는 2023년 이후입니다. 정답 종료일이 다음 구간으로 넘어가는 행은 제외합니다. 세 구간 공통 종목과 최소 학습 표본 조건도 D/E를 따릅니다. 공개 시각 검증 여부는 결과에 남고 미확인 자료는 연구용으로 취급합니다.
- 트리 깊이 3, 학습률 0.01, 자연 그래디언트와 로그 점수를 사용합니다. 반복 수 300은 초기 비교를 위해 고정했습니다. 80·90·95% 구간의 보정값은 보정 구간에서만 적합합니다. 정규분포의 손실 확률은 원분포 기준이며 CQR은 구간에만 적용합니다.

## 결과 읽는 법

- `metrics.csv`에서 MAE·RMSE, 포함률, 폭, 구간 점수, 하위 분위수 pinball loss를 확인합니다. NGBoost의 시장충격 유형별 지표와 저장된 D/E의 전체 지표가 들어갑니다. `paired_differences.csv`에서 양수는 NGBoost의 오차가 더 큰 경우입니다. 날짜·종목·정답·변동성 척도·충격이 일치하는 D/E 예측만 쌍대 비교합니다. 블록 부트스트랩 구간은 중첩을 고려하는 근사치입니다.
- `loss_calibration.csv`는 일반 수익률 기준 5%·10% 이상 손실 확률의 평균, 실현 빈도, Brier 점수를 기록합니다.
- `scenarios.csv`는 두 과거 시장 상태에 동일한 D/E 가상 충격을 넣은 종목별 결과입니다. 범위 표시는 충격별 학습 범위를 뜻하며 조합 자체의 관측 빈도는 별도 검증이 필요합니다.
- `ngboost_<기간>d.joblib`에는 학습 모델, 입력 순서, 대상 종목, 보정값이 들어갑니다. 동일 환경에서 신뢰할 수 있는 로컬 파일을 로드하고 `train.predict_distribution(package, frame)`을 호출합니다. 입력 행에는 `asset_id`, D/E 입력 10개, `scale_kospi`, `asset_scale`이 필요합니다.
- `run_info.json`, `split_keys.parquet`, `split_asset_counts.csv`로 실행 환경과 분할을 확인합니다. `shock_observation_dates.parquet`에는 한국 거래일 양 끝에 연결된 각 공급자의 실제 관측일이 들어갑니다. 이 평가는 과거 실현 충격을 넣는 조건부 재구성이고 평가 구간은 기존 실험에 노출되어 있습니다. 종목별 분포를 추정하므로 공동 하락을 반영하는 포트폴리오 표본에는 별도 종목 간 의존성 모델이 필요합니다.
