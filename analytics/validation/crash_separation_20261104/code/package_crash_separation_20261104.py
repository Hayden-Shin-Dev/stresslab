import json,hashlib,shutil
from pathlib import Path
import pandas as pd
import numpy as np
from crash_separation_20261104 import ROOT,OUT

r=pd.read_parquet(OUT/'predictions.parquet');ev=r[r.fold>=2023];b=ev[ev.model=='baseline']
old=pd.read_parquet(ROOT/'reports/service_candidate_20261104/predictions.parquet')
q=b.merge(old,on=['asset','date'],suffixes=('','_old'),validate='one_to_one')
assert len(q)==2928
for col in ['actual','center','lo','hi']:np.testing.assert_allclose(q[col],q[col+'_old'],atol=1e-10)
for n,z in ev.groupby('model'):
    v=z.merge(b,on=['asset','date'],suffixes=('','_b'),validate='one_to_one');assert len(v)==2928
    np.testing.assert_array_equal(v.actual,v.actual_b)
    assert (v.lo<=v.hi).all() and np.isfinite(v[['center','lo','hi']]).all().all()
    if n.endswith('center_only'):np.testing.assert_allclose(v.hi-v.lo,v.hi_b-v.lo_b,atol=1e-10)
    if n.endswith('interval_only'):np.testing.assert_allclose(v.center,v.center_b,atol=1e-10)
audit=pd.read_csv(OUT/'temporal_audit.csv')
assert (pd.to_datetime(audit.train_label_end)<pd.to_datetime(audit.cal_label_end)).all()
assert (pd.to_datetime(audit.cal_label_end)<pd.to_datetime(audit.test_start)).all()
check=dict(status='completed',evaluation_rows_per_model=2928,dates=169,assets=20,variants=ev.model.nunique(),baseline_reproduced=True,same_width_center_ablation=True,same_center_interval_ablation=True,code_validation_is_not_performance_approval=True,production_promoted=False,gold_sha256=hashlib.sha256((ROOT/'exports/seongjin_gold_v1_1/gold_stress_daily.parquet').read_bytes()).hexdigest())
(OUT/'verification.json').write_text(json.dumps(check,indent=2))
md='''# 급락 실패 분리 검증

급락 누락 문제는 해결되지 않았습니다. 평균 오차가 조금 줄어도 급락 성능이 악화된 방법은 채택하지 않았습니다. Azure, Gold 계약, 운영 모델은 변경하지 않았습니다.

## 같은 조건에서 비교한 결과

20종목, 2023-01-02~2026-10-19의 169개 평가 날짜, 2,928개 종목 관측입니다. 실제 5거래일 수익률이 -5% 이하인 관측은 390개입니다. 동일 날짜 종목은 독립 사건이 아닙니다. 과거에 실제 발생한 네 충격을 사후 입력한 재구성 평가이며, 재사용한 연구 기간이므로 블라인드 테스트가 아닙니다.

| 방법 | 전체 MAE | 급락 MAE | 80% 포함률 | 평균 폭 | 급락 하단 이탈률 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 기존 중립 기준 팩터 | 4.467%p | 7.673%p | 79.51% | 14.21%p | 56.41% |
| 국내 시장 지표와 외표본 잔차로 중심만 보정 | 4.445%p | 7.970%p | 79.68% | 14.21%p | 58.97% |
| 중심 유지, 조건부 하단과 상단 학습 | 4.467%p | 7.673%p | 77.70% | 12.74%p | 65.64% |
| 시장 상태와 충격이 가까운 잔차로 구간 보정 | 4.467%p | 7.673%p | 81.49% | 14.94%p | 53.59% |

마지막 방법의 누락 감소는 폭 증가를 동반합니다. 중심 개선 방법은 급락 누락률을 2.56%p 악화시켰고, 날짜 월 블록 95% 구간도 악화 0.65~4.96%p였습니다. 전체 MAE의 0.021%p 개선은 불확실성 구간이 0을 포함합니다. 학습 방법과 보정 방법을 교차한 전체 16개 결과는 evaluation_metrics.csv에 있습니다.

## 무엇을 놓쳤는가

급락 390개에서 실제 평균은 -8.49%, 모델 중심은 -0.84%입니다. 중심이 상승으로 나온 경우는 127개입니다. 하단을 벗어난 220개 중 66개는 하단 자체가 -5% 이상이었습니다. 나머지는 하단이 -5% 아래여도 실제 하락을 충분히 담지 못했습니다. 이는 원인의 인과적 분해가 아니라 중심 오차와 하방 여유의 산술 비교입니다.

2026년에는 급락 중심 MAE가 10.42%p, 급락 하단 이탈률이 65.35%였습니다. 고변동성 구간 전체의 급락 이탈률은 60.74%입니다. 종목별로 KB금융 10/13건, 하나금융지주 12/16건, 셀트리온 9/12건, 기아 11/15건, 신한지주 11/15건에서 하단을 벗어났습니다. 표본이 작으므로 종목 순위를 일반화하지 않습니다.

2026-07-01 삼성전기는 실제 -32.93%, 중심 +1.44%, 하단 -11.34%였습니다. 같은 구간 코스피는 -12.73%였지만, 입력 충격은 환율 -2.22%, 미국 금리 +11bp, 유가 +1.37%, VIX -0.32포인트였습니다. 시작 시점의 코스피 최근 5일 수익률은 -1.98%였습니다. 네 거시 충격만으로 국내 급락을 대변하지 못한 구체적인 사례입니다. 미래 코스피 수익률은 진단에만 사용했고 학습 입력에 넣지 않았습니다.

## 무엇을 실제로 수정하고 검증했는가

기존 중립 팩터의 연도별 외표본 예측 오차를 다시 만들었습니다. 학습에 사용한 선형 모델의 인샘플 잔차를 사용하지 않았습니다. 이 잔차의 10%, 50%, 90% 분위수를 공동 학습했습니다. Gold 기존 피처와 국내 시장 최근 수익률, 낙폭, 하방 변동성 등 10개 추가 지표를 비교했습니다. 추가 지표도 기존 Gold에서 파생했으며 계약은 바꾸지 않았습니다.

중심만 변경할 때는 각 관측의 구간 폭을 정확히 유지했습니다. 구간만 변경할 때는 중심값을 정확히 유지했습니다. 이어서 최근 잔차, 비슷한 시장 상태의 잔차, 비슷한 상태와 충격의 잔차에 가중치를 주는 세 방법도 비교했습니다. 가중치는 평가 정답을 보지 않고 계산했습니다.

모든 선택은 2020~2021 개발 결과만 사용했습니다. 전체 MAE, 급락 MAE, 급락 이탈률, 구간 점수를 개선하고 폭이 늘지 않는 후보는 없었습니다. 따라서 평가 결과가 좋아 보이는 방법을 사후 선택하지 않았습니다.

## 서비스 적용 판단

현재 팩터의 충격 전후 차이는 가정에 따른 탐색값으로 제공할 수 있지만, 종목 총손실과 급락을 신뢰성 있게 추정하는 기능은 이번에도 확보하지 못했습니다. 이를 검증된 급락 방어선으로 표시해서는 안 됩니다.

남은 문제는 API 연결이 아니라 국내 시장 급락과 기업별 급변을 현재 입력이 충분히 설명하지 못한다는 점입니다. 미래 국내 시장 하락을 추가 조건으로 사용하면 다른 시나리오 모델이 되므로, 실제 미래 코스피 값을 몰래 넣어 성능을 높이지 않았습니다. 그 입력을 추가하려면 별도 가정과 검증이 필요합니다. 이번 결과로 모든 모델이 불가능하다고 결론내리지는 않습니다.

현재 데이터에는 공표 시각과 수정 이력 공백, 현재 종목 구성에 따른 생존 편향도 남아 있습니다. 19종목 하락 비율은 코스피 전체 하락 비율이 아닙니다. 연구 성능과 데이터 한계를 함께 해석해야 합니다.

## 파일과 재현

- crash_cases.csv: 급락 관측별 실제 수익률, 중심, 하단, 충격, 사전 시장 상태입니다.
- slices.csv: 종목, 업종, 연도, 시장 상태별 결과입니다.
- development_metrics.csv / evaluation_metrics.csv: 개발과 평가 결과입니다.
- monthly_block_ci.csv: 같은 달의 모든 종목을 함께 재표본추출한 2,000회 비교입니다.
- temporal_audit.csv: 학습 정답 종료, 보정 정답 종료, 평가 시작 시각입니다.
- predictions.parquet: 모든 방법의 관측별 계산값입니다.
- code: 실험, 검증, 패키징 코드입니다.

기존 pooled_hybrid_20261104의 연도별 팩터 캐시와 Gold 원본을 사용합니다. 캐시가 없다면 해당 연구의 run_pooled_hybrid_20261104.py부터 실행합니다. STRESSLAB_AUDIT_ROOT를 연구 루트로 지정한 뒤 crash_separation_20261104.py, crash_local_calibration_20261104.py, package_crash_separation_20261104.py 순서로 실행합니다. 원본 금융 데이터와 모델 캐시는 로컬에 보존합니다.
'''
(OUT/'README.md').write_text(md,encoding='utf8')
dest=ROOT.parent/'stresslab-team/analytics/validation/crash_separation_20261104';dest.mkdir(parents=True,exist_ok=True);(dest/'code').mkdir(exist_ok=True)
for p in OUT.iterdir():
    if p.is_file() and p.suffix in ['.csv','.json','.md','.parquet']:shutil.copy2(p,dest/p.name)
for name in ['crash_separation_20261104.py','crash_local_calibration_20261104.py','package_crash_separation_20261104.py','pooled_stress_core_20261104.py','run_pooled_hybrid_20261104.py','service_candidate_20261104.py','crash_cases_center_20261104.py','gold_quantile_benchmark.py','four_models_gold_20261104.py']:
    shutil.copy2(ROOT/'scripts'/name,dest/'code'/name)
print(json.dumps(check))

