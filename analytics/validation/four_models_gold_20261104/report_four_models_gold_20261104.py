"""Verify and report four-model Gold-only research, without production promotion."""
import json,hashlib,importlib.metadata
import numpy as np
import pandas as pd
from four_models_gold_20261104 import OUT,ROOT,KINDS,FEATURES,score
def main():
    r=pd.read_parquet(OUT/'predictions.parquet');m=pd.read_csv(OUT/'metrics.csv').set_index('model')
    locked=pd.read_parquet(ROOT/'reports/gold20_locked_20261104/locked_baseline.parquet').sort_values(['asset','date'])
    schema=json.loads((OUT/'gold_schema_snapshot.json').read_text(encoding='utf8'));g=pd.read_parquet(ROOT/'exports/seongjin_gold_v1_1/gold_stress_daily.parquet')
    assert set(g.columns)==set(schema['items']['required']) and len(g.columns)==34
    for kind,z in r.groupby('model'):
        z=z.sort_values(['asset','date']);assert len(z)==2928 and z.asset.nunique()==20
        assert list(zip(z.asset,z.date))==list(zip(locked.asset,locked.date))
        assert np.array_equal(z.actual.to_numpy(),locked.actual.to_numpy())
        assert np.isfinite(z[['center','lo','hi','q05','es']]).all().all()
        assert (z.lo<=z.hi).all() and (z.q05<=z.lo).all() and (z.es<=z.q05+1e-10).all()
        recalculated=score(z)
        for key in ['direction','mae','coverage80','width80','interval_score80','lower_breach','var95_exceedance']:assert abs(recalculated[key]-m.loc[kind,key])<1e-10
    audit=pd.read_csv(OUT/'fit_audit.csv')
    assert (pd.to_datetime(audit.train_label_end)<pd.to_datetime(audit.cal_start)).all()
    assert (pd.to_datetime(audit.cal_label_end)<pd.to_datetime(audit.test_start)).all()
    dev=pd.read_csv(OUT/'development_metrics.csv');choices=json.loads((OUT/'frozen_configs.json').read_text(encoding='utf8'))
    for kind,k in choices.items():assert k==int(dev[dev.model==kind].sort_values(['mae','config']).iloc[0].config)
    scenario=pd.read_csv(OUT/'scenario_sensitivity.csv',dtype={'asset':str});saturation=[]
    for kind in KINDS:
        s=scenario[(scenario.model==kind)&scenario.scenario.isin(['fx2.5_rate50','fx5_rate100','fx10_rate200'])]
        ranges=s.groupby('asset').center.agg(lambda x:x.max()-x.min());saturation.append(dict(model=kind,unchanged_three_shock_levels=int((ranges<1e-8).sum()),stocks=20))
    pd.DataFrame(saturation).to_csv(OUT/'shock_saturation.csv',index=False)
    ss=scenario[(scenario.asset.isin(['005930','005380']))&(scenario.scenario=='fx5_rate100')].copy()
    ss['assumed_value_krw']=50_000_000;ss['hypothetical_pnl_krw']=ss.center/100*ss.assumed_value_krw
    ss.to_csv(OUT/'scenario_portfolio_components.csv',index=False)
    ss.groupby('model').hypothetical_pnl_krw.sum().to_csv(OUT/'scenario_portfolio_center_only.csv')
    per=pd.read_csv(OUT/'per_stock.csv',dtype={'asset':str});per['descriptive_width5_coverage80']=(per.width80<=5)&(per.coverage80>=.8);per.to_csv(OUT/'per_stock.csv',index=False)
    checks=dict(status='passed',gold_contract_columns=34,model_input_features=len(FEATURES),models=4,stocks=20,rows_per_model=2928,paired_targets_exact=True,time_boundaries_checked=True,metrics_recomputed=True,finite_ordered_risk_outputs=True,gold_schema_changed=False,production_promoted=False,blind=False)
    (OUT/'verification.json').write_text(json.dumps(checks,indent=2),encoding='utf8')
    rows=['| 모델 | 방향 일치율 | MAE (%p) | 80% 구간 포함률 | 평균 폭 (%p) | 구간 점수 | 하위 5% 경계 이탈률 |','| --- | ---: | ---: | ---: | ---: | ---: | ---: |']
    for kind in KINDS:
        x=m.loc[kind];rows.append(f'| {kind} | {x.direction*100:.2f}% | {x.mae:.3f} | {x.coverage80*100:.2f}% | {x.width80:.2f} | {x.interval_score80:.2f} | {x.var95_exceedance*100:.2f}% |')
    bmae=float(abs(locked.actual-locked['median']).mean());nz=locked.actual!=0;bdir=float((np.sign(locked.actual[nz])==np.sign(locked['median'][nz])).mean());cat=m.loc['catboost']
    ci=pd.read_csv(OUT/'paired_uncertainty.csv').set_index('model').loc['catboost']
    lines=[]
    for kind in KINDS:
        z=ss[ss.model==kind].set_index('asset');lines.append(f"| {kind} | {z.loc['005930','center']:+.2f}% | {z.loc['005380','center']:+.2f}% | {z.hypothetical_pnl_krw.sum():+,.0f}원 |")
    catrows=scenario[(scenario.model=='catboost')&scenario.asset.isin(['005930','005380'])&scenario.scenario.isin(['fx2.5_rate50','fx5_rate100','fx10_rate200'])]
    assert catrows.groupby('asset').center.agg(lambda x:x.max()-x.min()).lt(1e-8).all()
    text=f'''# Gold 계약 유지, 네 모델 동일 조건 비교

Gold는 기존 34개 컬럼 그대로 사용합니다. Fabric 담당자가 컬럼을 줄이거나 변경할 필요가 없습니다. ML에서 Gold의 가격과 거시 이력으로 기존 기준선의 18개 계산 입력을 만듭니다. 이번 연구에는 별도 수급, DART 재무비율, OHLC 자료를 넣지 않았습니다.

## 결과

20종목, 동일한 2,928개 종목별 표본을 비교했습니다. 평가 기간은 2023-01-02~2026-10-19입니다. 각 모델을 종목별로 따로 학습했습니다.

{chr(10).join(rows)}

MAE와 폭은 수익률 퍼센트포인트입니다. 방향은 실제 수익률 0인 경우를 제외한 부호 일치율입니다. 구간 점수는 폭과 구간 밖 오차를 함께 벌점으로 계산하며 낮을수록 좋습니다. 하위 5% 경계 이탈률의 명목 기준은 5%입니다.

이번 조건에서는 CatBoost의 중심값 MAE와 구간 점수가 가장 낮았습니다. 다만 네 모델 모두 평균 폭 5%p 이하와 포함률 80% 이상을 동시에 달성하지 못했습니다. CatBoost가 일반적으로 최적이라는 결론이나 최종 서비스 승인은 아닙니다.

초기 Gold CatBoost 중심값은 방향 {bdir*100:.2f}%, MAE {bmae:.3f}%p였습니다. 이번 CatBoost는 방향 {cat.direction*100:.2f}%, MAE {cat.mae:.3f}%p로, MAE가 {(bmae-cat.mae)/bmae*100:.2f}% 감소했습니다. 날짜 블록 재표본추출의 MAE 개선 95% 범위는 {ci.mae_gain_lo:.3f}~{ci.mae_gain_hi:.3f}%p입니다. 방향 개선 범위는 {ci.direction_gain_lo*100:.2f}~{ci.direction_gain_hi*100:.2f}%p로 0을 포함합니다. 방향 개선은 확실하다고 단정하지 않습니다.

초기 모델은 250회, 깊이 4의 다중 분위수 학습이었습니다. 이번 비교는 트리 세 모델을 중앙값 학습으로 맞추고, 개발 구간에서 선택된 150회, 깊이 3 설정을 사용했습니다. 알고리즘 이름을 그대로 둔 단순 재실행이 아닙니다. 깊고 긴 학습이 개발 MAE를 개선하지 않았습니다. Ridge는 평균을 학습하는 제곱오차 모델이며 이 차이를 숨기지 않습니다.

## 학습과 위험 구간

모델별 설정 세 가지를 2020~2021년 개발 표본에서 비교하고 MAE로 선정했습니다. 개발 표본은 당시 학습 가능한 18종목, 1,512개입니다. 이후 평가에는 20종목을 모두 포함했습니다. 새 상장 종목은 초기 기준선과 같은 날짜부터 평가했습니다.

연도마다 학습, 전년도 보정, 평가를 분리했습니다. 5거래일 정답 종료일에 20일 여유를 두었으며 평가 종목과 날짜를 기존 결과와 정확히 대조했습니다. 네 모델의 학습 정답은 동일한 사전 변동성으로 정규화했습니다. 모델마다 동일한 별도 보정 오차의 10%, 90% 분위수로 80% 구간을 만들었습니다. 전체 주가 변동성을 그대로 구간 폭으로 붙이거나 폭을 강제로 자르지 않았습니다.

보정 표본은 종목과 연도마다 {audit.cal_n.min()}~{audit.cal_n.max()}개입니다. 하위 5% ES 계산에 쓰인 오차는 2개뿐이므로 ES는 진단용입니다. `es_moment`는 하위 꼬리 보정 잔차의 평균이며 공식적인 검정 통과나 신뢰도 수치가 아닙니다. 이 연구만으로 ES를 정식 승인하지 않습니다.

실제 -5% 이하 급락은 390개입니다. CatBoost 중심값이 -5% 이하까지 내려간 것은 {int(cat.crash_center_caught)}개이며, 급락 때 80% 구간의 하한을 벗어난 비율은 {cat.crash_lower_breach*100:.2f}%입니다. 평균 MAE 개선과 급락 대응 완성은 별개입니다.

## 가상 충격 검사

아래는 2026-10-19 상태를 고정하고 환율 +5%, 미국 금리 +100bp, 유가 0%, VIX 0포인트를 넣은 연구 계산입니다. 현재 실시간 결과가 아닙니다. 0은 수준이 0이 된다는 뜻이 아니라 변화가 없다는 뜻입니다. 각 종목 5,000만원을 가정해 중심 수익률만 금액으로 환산했습니다. 개별 구간을 합쳐 포트폴리오 확률 구간으로 만들지 않았습니다.

| 모델 | 삼성전자 중심값 | 현대차 중심값 | 합산 가상 손익 |
| --- | ---: | ---: | ---: |
{chr(10).join(lines)}

**이 숫자는 검증된 손실 전망이 아닙니다.** 두 종목의 CatBoost는 환율 +2.5%와 금리 +50bp, +5%와 +100bp, +10%와 +200bp에서 각각 같은 중심값을 반환했습니다. 트리 분기 범위를 넘어가면 더 큰 입력에도 같은 잎에 도달할 수 있습니다. 역사적 평균 성능이 좋다고 충격 크기를 충분히 구분하는 것은 아닙니다.

이 조건에서 정해 둔 네 충격 허용 차이 안에 드는 학습 구간도 0개였습니다. 이는 이번 검색 기준의 결과이며 모든 형태의 관련 사례가 없다는 증명은 아닙니다. `shock_near_disjoint_windows`는 충격 근접도만 세며 시장 상태 유사성까지 검증한 수가 아닙니다. `shock_saturation.csv`와 `scenario_sensitivity.csv`에 20종목 전체 결과를 남겼습니다.

## Gold 계약 판단

기존 34개 컬럼으로 네 모델의 학습과 계산을 구현할 수 있습니다. 스키마를 18개로 바꿀 필요가 없습니다. 날짜, 종목코드, 출처, 품질은 데이터 연결과 검사에 사용하고 수치 이력에서 모델 입력을 계산합니다. `FEATURES`는 구현 코드와 `protocol.json`에 고정했습니다.

다만 현재 연구 파일은 가격 및 다섯 거시 요인의 available_at이 모두 NULL입니다. 형식상 허용되는 값이지만 당시 실제 공개 여부가 검증됐다는 뜻은 아닙니다. Fabric이 기존 시각 컬럼에 확인된 값을 채우고, 미확인 자료를 연구용으로 구분해야 합니다. 컬럼 추가 문제와 내용 품질 문제를 구분해야 합니다.

이전 추가 변수 연구가 동시 개선에 실패했다는 이유로 앞으로의 모든 변수가 불필요하다고 결론 내리지 않습니다. 현재는 계약을 유지하고, 추가 컬럼은 별도의 유용성 검증과 팀 합의 후 판단합니다.

## 적용 범위와 재현

이번 결과는 실제 발생한 미래 5거래일 충격을 사후 조건으로 넣은 역사적 재구성 평가입니다. 충격 발생 예측이나 인과효과 검증이 아닙니다. 평가 기간은 기존 연구에서 사용됐으므로 독립 블라인드 테스트가 아닙니다. 비교 과정의 시간 경계 검사는 통과했지만 원천 공표 시각의 한계를 대신하지 않습니다.

CatBoost는 후속 연구의 우선 비교 후보로 남깁니다. 운영 모델 승격, Azure 변경, Gold 계약 수정은 하지 않았습니다. 평균 폭 5%p 및 포함률 80% 목표와 강한 사용자 충격의 반응 타당성은 미해결입니다.

`STRESSLAB_AUDIT_ROOT`를 원본 로컬 프로젝트 경로로 지정하고 아래 순서로 실행합니다.

```powershell
python four_models_gold_20261104.py
python report_four_models_gold_20261104.py
```

입력은 `exports/seongjin_gold_v1_1/gold_stress_daily.parquet`와 `reports/gold20_locked_20261104/locked_baseline.parquet`입니다. 원본 데이터 및 인증정보는 저장소에 올리지 않습니다. `per_stock.csv`, `per_year.csv`, `per_regime.csv`에 세부 성능, `predictions.parquet`에 동일 표본의 실제 계산값을 보존했습니다. 초기 90% 구간과 이번 80% 구간의 폭을 직접 개선율로 비교하지 않습니다.
'''
    (OUT/'README.md').write_text(text,encoding='utf8')
    (OUT/'environment.json').write_text(json.dumps({k:importlib.metadata.version(k) for k in ['numpy','pandas','scikit-learn','catboost','lightgbm','xgboost','pyarrow']},indent=2),encoding='utf8')
    print(json.dumps(checks))
if __name__=='__main__':main()
