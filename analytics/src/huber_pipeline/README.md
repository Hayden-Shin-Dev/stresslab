# Fabric Gold 기반 Huber 로컬 실행

현재 운영 파이프라인을 바꾸지 않고, Gold 읽기부터 학습과 AI 전달 결과까지 로컬에서 검증하는 코드입니다. 기존 `conditional_service`와 성진 담당 노트북은 수정하지 않습니다.

2026-11-11 정정: PR12는 Huber 계산식만 옮겼고 충격 입력과 학습 표본까지 동일하게 옮기지 못했습니다. 현재 코드는 원 관측자료, 초기 학습 준비 구간, 오전 8시 30분 조건을 복원했습니다. 이후 구간 계산도 기존 B152 비교 실험 방식으로 복원했습니다. [구간 계약과 고정 날짜 비교](../../validation/huber_interval_contract_20261111/README.md)를 최종 기준으로 확인하세요.

## 입력

`lh_whatif.gold_stress_daily`의 고정 Delta 버전을 읽습니다. 같은 게시 버전의 Gold 사본, provenance, 입력 적합성 표, 인증 파일을 함께 확인합니다. 원본 데이터와 모델은 Git에 넣지 않습니다.

결측을 0이나 미래 값으로 채우지 않습니다. 전체 거래일에서 시차 피처와 1일/5일 정답을 먼저 만든 뒤 학습 적합성 조건을 적용합니다. 한국 3년 금리는 현재 Gold 계약의 선택 입력입니다. 종목 가격과 수익률은 수정주가 기준이며, 정확한 가격 공표 시각과 과거 수정본까지 검증됐다는 뜻은 아닙니다.

## 실행

Python 3.11에서 `requirements.lock.txt`를 설치하고 저장소 루트에서 실행합니다.

```powershell
$env:PYTHONPATH = 'analytics/src'
python -m huber_pipeline.snapshot --workspace 2c303c0d-6c10-4988-91cb-856fe5f56071 --lakehouse 93432592-8620-411e-808f-b91678bf78d2 --output data/huber/gold_snapshot
python -m huber_pipeline.shocks --download-legacy data/huber/factor_observations.parquet
python -m huber_pipeline.run --snapshot data/huber/gold_snapshot --observations data/huber/factor_observations.parquet --reference-inputs "$env:USERPROFILE/.cache/stress-native-intervals-v162/inputs.parquet" --output outputs/huber/run_001
python -m huber_pipeline.verify_outputs --snapshot data/huber/gold_snapshot --output outputs/huber/run_001 --evidence-file services/debate/src/evidence.py
python -m pytest analytics/tests/test_huber_pipeline.py -q
```

출력 폴더는 새 경로를 사용합니다. `models.json`, `features.parquet`, `backtest.parquet`, `metrics.csv`, `scenario_examples.json`과 검증 근거를 저장합니다. 스냅샷 수집에는 Azure CLI 로그인이 필요합니다. 토큰은 파일에 저장하지 않습니다.

## 모델과 충격 정의

`model.py`는 기존 로컬 B152 symmetric Huber 학습과 추론 계산식을 옮긴 것입니다. 상태 피처는 `ret20_z`, `vol_ratio`이고, 종목별 변동성으로 정규화합니다. 종목별로 1일/5일 모델을 따로 학습합니다.

Gold의 거시 값은 발표 시점 기준의 시장 상태입니다. 이 값의 차분을 B152 시나리오 충격으로 사용하지 않습니다. 종목 가격과 상태 피처, 수익률 정답은 현재 Gold를 사용하되, 충격은 Fabric에 보관된 원 관측자료를 읽어 계산합니다. 원본과 같은 해시를 검사하며 새 원천 데이터 버전은 별도 대조가 필요합니다.

각 한국 거래일보다 관측일이 앞선 최근 값을 선택하고, 관측 나이가 7일을 넘으면 제외합니다. 이 값의 일별 차이를 계산한 뒤 다음 거래일 충격으로 이동합니다. 원 자료가 끝난 뒤 확인할 수 없는 날짜를 0 충격으로 연장하지 않습니다. 이는 가정 또는 사후 관측 충격을 주어진 입력으로 쓰는 방식입니다. 실제 당시 입수한 관측값이라는 의미가 아니며, 학습 시각에 쓰는 `policy_available_at`도 원본의 연구용 발표 가정입니다.

기존 피처 계산식과 같은 가중치를 사용한 추론의 동일성을 검사합니다. 최신 Gold로 다시 학습하면 학습 표본과 계수가 달라지므로 이전 모델과 출력이나 성능까지 같다는 뜻은 아닙니다.

원본의 초기 252행 준비 조건과 학습 후보 시작 분기를 복원했습니다. 분기 학습일의 오전 8시 30분보다 발표 정책 시점이 앞서고 수익률 정답이 완성된 표본 중 최근 2,520행을 사용합니다. 현재 Gold의 거시 상태 적합성으로 과거 사후 충격 학습 표본까지 삭제하지 않습니다. 구간은 B152의 기존 v173 비교 실험을 그대로 사용합니다. 종목과 기간별로 학습 마감 전에 정답과 충격 정책 시점이 확정된 과거 예측 중 최근 252개를 선택합니다. 단순수익률 절대오차를 당시 변동성 scale로 나누고, ceil((n+1)*0.9)번째 값에 현재 scale을 곱한 반폭을 중심값 양쪽에 붙입니다. 최소 60개가 필요하며, 초기 과거 구간은 원본에서 사용한 B147 반폭을 해시 검증된 보관 자료에서 가져옵니다. 초기 자료가 없으면 임의 대체하지 않고 중단합니다. 따라서 고정 과거 재현에는 위 reference-inputs 파일도 필요합니다. 현재 20종목 서비스 패키지는 모두 60개 이상의 과거 오차를 사용합니다.

## AI 전달

입력 `shocks`는 환율 %, 미국 10년 금리 bp, WTI %, VIX pt입니다. WTI는 해당 Gold 기준 유가로 달러 차이로 바꿔 Huber에 넣습니다. 환율도 모델 내부 로그변화로 변환합니다. 변환 전후 값을 모두 결과에 남깁니다.

`conditional_center_return_pct`는 충격 조건의 전체 대표 수익률이고 `scenario_difference_pp`는 추가 충격 0 대비 변화입니다. 사용자 기존 수익률은 입력하지 않습니다. 손익은 보유금액에 전체 수익률을 적용하며, 충격만의 추가 손익은 별도 필드입니다.

요인별 기여도는 16개 충격 조합을 이용한 정확한 Shapley 분해입니다. 합계는 추가 영향과 같으며 인과 추정값이라는 의미는 아닙니다. q05~q95는 기존 90% 목표 대칭 구간을 그대로 전달합니다. q10~q90은 같은 오차 표본에 80% 순위식을 적용한 추가 출력이며 별도 성능 승인을 의미하지 않습니다. 필드명은 AI 입력 계약을 따른 것으로, 비대칭 분포의 분위수를 따로 학습했다는 의미는 아닙니다. 보수적 하단은 기존 q05입니다. 형식 변환 전후 중심값과 구간 하단 및 상단이 동일한지 검사합니다. 현재 AI 근거 조립기는 q10, q90, 보수적 하단을 읽으며 q95는 읽지 않습니다. 이 작업에서는 AI 코드를 수정하지 않았습니다.

과거 사례는 같은 종목과 기간에서 기준일 전에 끝난 실제 사례 중 입력한 활성 충격의 방향이 같고 크기 차이가 허용 범위인 사례를 최대 2개 선택합니다. 기간이 겹치는 사례는 제외합니다. 사례가 없으면 빈 배열을 반환합니다. 가까운 사례가 있다는 사실을 검증된 인과효과로 표시하지 않습니다.

포트폴리오는 보유금액과 종목별 손익을 합산합니다. 별도 포트폴리오 ML, VaR, ES, 종목 구간을 더한 포트폴리오 구간은 만들지 않습니다. 시장 상태 정보는 AI 설명용이며 Huber의 두 상태 피처를 추가로 바꾸지 않습니다.

## Fabric 이식 시

기존 노트북에서 Gold와 게시 근거, 원 관측자료를 읽고 `features.build(gold, provenance, observations)`를 호출한 뒤 `training.train_and_backtest`를 실행합니다. 원 관측자료가 없으면 중단하며 Gold 차분으로 자동 대체하지 않습니다. `result.scenario`는 같은 패키지와 전처리 코드를 서비스에서도 사용합니다. 현재 자동 배포나 운영 노트북 교체는 하지 않았습니다. 이후 정기 학습에는 원 관측자료의 갱신 연결이 필요하며, 현재 보관 파일은 원본 재현용 고정 버전입니다.

모델 패키지와 데이터 버전, 라이브러리를 고정해 동일 입력 결과를 비교한 다음 연결해야 합니다. 현재 학습 결과는 자동 운영 승인 대상이 아닙니다. 백테스트 지표를 AI 근거에 추가하는 작업은 후속 범위입니다.

## 고정 평가

기본 metrics는 원본 132,394개 종목/기간/날짜 키만 사용합니다. development는 2017년 이전, evaluation은 2017년 이후, recent는 2022년 이후이며 각 기간에서 전체 날짜와 큰 충격을 따로 집계합니다. 종목별 지표를 먼저 계산한 뒤 20종목을 동일 가중 평균합니다. 새 날짜를 과거 성능 평균에 몰래 추가하거나 최근 큰 충격 평균으로 대표 수치를 바꾸지 않습니다.

```powershell
python -m huber_pipeline.verify_interval_contract --output outputs/huber/run_001 --reference-inputs "$env:USERPROFILE/.cache/stress-native-intervals-v162/inputs.parquet" --reference-forecasts "$env:USERPROFILE/.cache/stress-lightgbm-research-v173/forecasts.parquet" --report outputs/huber/verified_001
```

검증기는 원본 파일 해시, 평가 키, 학습일, 보정 표본 수, 충격 분류, 중심값과 90% 구간 양끝을 모두 검사합니다. 새 날짜의 전진 평가는 별도 이름으로 기록하며 이 고정 비교표를 덮어쓰지 않습니다. 기존 compare_alignment는 PR14 당시의 다른 구간 규칙을 분석한 역사적 진단 도구이며 현재 승인된 구간 계산이나 대표 성능 집계에 사용하지 않습니다.
