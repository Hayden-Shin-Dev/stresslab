"""Report all prespecified comparisons, including failed sign constraints."""
import json, hashlib
import numpy as np
import pandas as pd
from train_selected_response_20261104 import ROOT,OUT,score,METHODS

def main():
    assert json.loads((OUT/'verification.json').read_text())['status']=='complete'
    p=pd.read_parquet(OUT/'predictions.parquet');extra=pd.read_parquet(OUT/'air_oil_control.parquet');p=pd.concat([p,extra])
    s=pd.concat([pd.read_parquet(OUT/'shock_interventions.parquet'),pd.read_parquet(OUT/'air_oil_control_responses.parquet')])
    pairs=pd.read_csv(OUT/'frozen_pairs.csv',dtype={'asset':str})
    response=s.groupby(['asset','shock','method','selected']).agg(n=('response_pp','size'),mean_response_pp=('response_pp','mean'),median_response_pp=('response_pp','median'),positive_fraction=('response_pp',lambda x:(x>1e-8).mean()),negative_fraction=('response_pp',lambda x:(x<-1e-8).mean()),flat_fraction=('response_pp',lambda x:(abs(x)<=1e-8).mean()),mean_low=('low_prediction','mean'),mean_high=('high_prediction','mean')).reset_index()
    response.to_csv(OUT/'response_summary.csv',index=False)
    checks=[]
    for _,r in pairs.iterrows():
        z=s[s.asset.eq(r.asset)&s.shock.eq(r.feature)&s.method.eq('selected_monotone_mean')]
        checks.append(dict(asset=r.asset,shock=r.feature,n=len(z),violations=int((z.response_pp*r.sign < -1e-8).sum())))
    assert sum(v['violations'] for v in checks)==0
    pd.DataFrame(checks).to_csv(OUT/'constraint_verification.csv',index=False)
    # Stock-specific uncertainty is exploratory, not post-test stock selection.
    u=[]
    for asset,z in p[p.method.isin(METHODS)].groupby('asset'):
        base=z[z.method.eq('all4_median')];quarters=pd.period_range(base.date.min(),base.date.max(),freq='Q');rng=np.random.default_rng(20261104);draw=rng.integers(0,len(quarters),(2000,len(quarters)))
        for method in METHODS[1:]:
            t=z[z.method.eq(method)].merge(base,on=['asset','date'],suffixes=('_new','_base'),validate='one_to_one')
            delta=abs(t.center_new-t.actual_new)-abs(t.center_base-t.actual_base)
            g=pd.DataFrame(dict(block=t.date.dt.to_period('Q'),delta=delta)).groupby('block').delta.agg(['sum','count']).reindex(quarters,fill_value=0)
            b=g['sum'].to_numpy()[draw].sum(1)/g['count'].to_numpy()[draw].sum(1);lo,hi=np.quantile(b,[.025,.975])
            u.append(dict(asset=asset,method=method,mae_delta=delta.mean(),ci_low=lo,ci_high=hi))
    pd.DataFrame(u).to_csv(OUT/'asset_uncertainty.csv',index=False)
    named=p[p.asset.isin(['003490','010950'])]
    metrics=pd.DataFrame([dict(asset=a,method=m,**score(v)) for (a,m),v in named.groupby(['asset','method'])]);metrics.to_csv(OUT/'named_asset_metrics.csv',index=False)
    # Export every failure, not a favorable subset.
    f=p[p.method.eq('selected_monotone_mean')].copy();f['absolute_error_pp']=abs(f.actual-f.center);f['lower_miss_pp']=(f.lower-f.actual).clip(lower=0)
    f.sort_values('absolute_error_pp',ascending=False).head(50).to_csv(OUT/'largest_errors.csv',index=False)
    f[f.actual<=-5].to_csv(OUT/'all_crash_cases.csv',index=False)
    baseline=pd.read_parquet(ROOT/'reports/variable_analysis_20261104/predictions.parquet');baseline=baseline[baseline.method.eq('baseline')&baseline.asset.isin(pairs.asset)]
    from report_long_universe import metric
    (OUT/'original_baseline_context.json').write_text(json.dumps(dict(**metric(baseline),note='Original 98-feature model trained one year more recently. Context only; causal ablations use retrained all4_median with identical training/calibration.')))
    agg=pd.read_csv(OUT/'aggregate.csv');unc=pd.read_csv(OUT/'uncertainty.csv');diag=pd.read_csv(OUT/'oil_period_diagnosis.csv',dtype={'asset':str})
    names={'all4_median':'네 충격 중앙값 기준선','selected_median':'선정 충격만 중앙값','selected_mean':'선정 충격만 평균','selected_monotone_mean':'선정 충격 반응 방향 반영','air_oil_diagnostic':'대한항공 유가 하락 방향 추가','air_oil_unconstrained':'대한항공 유가 추가, 방향 자유','air_other_signs_only':'대한항공 유가 추가, 다른 충격만 방향 반영'}
    lines=['# 종목과 충격 조합을 고정한 반응 학습','',
      f'2022년 이전 근거로 {pairs.asset.nunique()}종목 {len(pairs)}개 조합을 선정했습니다. 이후 평가 결과로 목록이나 부호를 바꾸지 않았습니다. Azure, Gold 계약, 운영 모델은 변경하지 않았습니다.','',
      '## 무엇을 바꿨는지','',
      '관련 변수를 넣는 것에서 그치지 않고, 선정된 충격의 반응 방향을 학습 제약으로 적용했습니다. 예를 들어 S-Oil 유가 반응을 양수로 선정했다면, 같은 시장 상태와 다른 충격을 고정한 상태에서 유가만 올릴 때 계산 수익률이 낮아지지 않도록 했습니다. 수익률 자체를 양수로 강제하지는 않습니다. 이 제약은 검증할 통계적 가정이며 인과 법칙이 아닙니다.','',
      '네 충격 중앙값 기준선, 선정 충격 중앙값, 선정 충격 평균, 반응 방향을 반영한 평균 모델을 비교했습니다. 중앙값과 평균의 차이, 변수 제외 효과, 반응 제약 효과를 구분합니다. LightGBM의 동일한 깊이와 학습 횟수를 사용했습니다.','',
      '## 왜 앞선 분석과 성능이 달랐는지','',
      '1. 앞선 값은 유가 상승군과 하락군의 평균 차이입니다. 특정 충격에서 개별 종목 수익률을 맞힌 성능이나 1% 충격의 계수가 아닙니다. 기존 모델은 중앙값을 학습했습니다.','2. 대한항공은 장기 평균 유가 반응이 음수지만, 2016~2021년 다른 변수를 고려한 잔차 회귀에서는 기울기가 +0.0175이고 유의하지 않았습니다. 따라서 안정적인 독립 반응이라고 선정할 수 없습니다. S-Oil 유가 조합은 같은 엄격한 기준을 통과했습니다.','3. 기존 적용은 입력 변수 선택이었고, 분석에서 확인한 방향을 실제 학습 조건으로 사용하지 않았습니다. 이번에는 그 부분을 직접 반영하고 효과를 분리했습니다.','4. 같은 충격군 안에서도 수익률의 분산과 반대 방향 사례가 큽니다. 반응 차이가 존재하는 것과 개별 구간 방향을 80% 맞히는 것은 다른 문제입니다.','',
      '## 선정 기준','',
      '통제 변수 평균 균형 통과, 두 과거 시기 ALE 반응 부호 일치, 균형 비교와 ALE 부호 일치, 평균 대비 1%p 이상의 반응 차이, 잔차 회귀 부호 일치, BY 보정 q<0.05, 연도별 부호 일관성 80% 이상을 모두 요구했습니다. 기존 분석 결과를 활용한 탐색적 선정이며 독립 검증으로 볼 수 없습니다. 부호 일관성만으로 인과관계나 전체 조건의 단조성을 증명하지는 않습니다.','',
      '환율 12개, 유가 5개, VIX 32개 조합입니다. 미국 금리는 통과 조합이 없습니다. 모델에 넣지 않은 충격을 바꿔도 계산이 바뀌지 않으며, 이는 영향이 없다는 결론이 아니라 해당 모델의 지원 범위 밖이라는 뜻입니다.','',
      '## 동일 표본 결과','',
      '| 방식 | 표본 | MAE(%p) | 방향 일치 | 80% 구간 포함 | 평균 폭(%p) | 급락 하방 이탈 |','|---|---:|---:|---:|---:|---:|---:|']
    for _,r in agg.iterrows():lines.append(f'| {names[r.method]} | {int(r.n)} | {r.mae:.3f} | {r.direction_accuracy:.1%} | {r.coverage80:.1%} | {r.width_pp:.2f} | {r.crash_lower_breach:.1%} |')
    lines+=['','급락은 실제 5거래일 수익률 -5% 이하입니다. 급락 하방 이탈은 해당 표본 중 실제 수익률이 구간 하한보다 낮았던 비율입니다. 폭을 5%p로 강제하지 않았습니다.','',
      '## 대한항공과 S-Oil','',
      '| 종목 | 방식 | MAE(%p) | 방향 일치 | 포함률 | 폭(%p) |','|---|---|---:|---:|---:|---:|']
    for _,r in metrics.iterrows():lines.append(f'| {"대한항공" if r.asset=="003490" else "S-Oil"} | {names[r.method]} | {r.mae:.3f} | {r.direction_accuracy:.1%} | {r.coverage80:.1%} | {r.width_pp:.2f} |')
    lines+=['','대한항공 유가 조합은 선정 기준에서 탈락했습니다. 사용자 지정 진단 대상으로만 유가 하락 방향을 강제로 추가한 결과까지 남겼습니다. 이를 정식 선정에 포함하거나 좋은 결과만 남기지 않았습니다.','',
      '학습 기간 전체의 균형 비교에서 대한항공 유가 상승군의 상승 빈도는 약 42%, S-Oil은 약 56%입니다. 평균 차이는 각각 -3.04%p, +2.40%p지만 반복 방향의 확률을 보장하지 않습니다. 최근 기간을 따로 나눈 비교는 통제 변수 균형 기준을 충족하지 못해 원인 판단 근거로 승인하지 않았습니다. oil_period_diagnosis.csv의 supported를 함께 확인해야 합니다.','',
      '## 검증 범위','',
      '2023~2026년의 기존 평가 날짜를 그대로 사용했습니다. 매년 이전 연도 시작 20일 전까지 정답이 끝난 자료로 학습하고, 직전 연도 중 정답이 평가 시작 20일 전에 끝난 표본으로 잔차 구간을 보정했습니다. 보정 표본은 매 여섯 번째 관측을 사용합니다. 학습, 보정, 평가의 정답 기간을 분리했습니다. time_audit.csv에 실제 시각과 표본 수가 있습니다.','',
      '실제 이후 5거래일 충격을 사후 입력한 조건부 재구성입니다. 평가 기간을 이미 여러 연구에서 사용했으므로 독립 블라인드가 아닙니다. 일부 공표 시각과 거시 데이터 빈티지는 추가 검증이 필요합니다.','',
      'shock_interventions.parquet는 같은 입력 행에서 한 충격만 학습 구간 25% 및 75% 분위수로 바꾼 모델 계산입니다. 실제 반사실 정답이 아니며, 주변 충격과의 공동 관측 범위까지 보장하지 않습니다. evaluation_contrasts.csv의 실제 상승군/하락군 비교는 별도의 관측 집단 비교입니다. 둘을 같은 효과라고 해석하면 안 됩니다.','',
      'uncertainty.csv는 동일 시점의 모든 종목을 함께 묶은 분기 블록 재표본추출 2,000회의 차이 구간입니다. asset_uncertainty.csv는 종목별 탐색 결과이며 이후 종목을 다시 고르는 데 사용하지 않았습니다.','',
      '## 재실행','',
      '`python run_selected_response.py --data-root <기존 연구 데이터 경로> --stage train`','',
      '이후 stage를 diagnosis, air-control, report 순서로 실행합니다. 입력은 reports/rich_context_20261103/learning_table.parquet, effect_atlas_20261104 분석 자료와 기존 평가 날짜입니다. 원천 데이터와 API 키는 공개 저장소에 포함하지 않습니다.','',
      '## 파일','',
      'frozen_pairs.csv: 선정 목록과 과거 근거. selection_audit.csv: 전체 404개 조합의 통과 및 탈락 이유. predictions.parquet: 같은 표본의 모든 모델 결과. pair_metrics.csv: 조합별 전체 및 큰 충격 표본 결과. response_summary.csv: 실제 계산의 충격 반응. largest_errors.csv와 all_crash_cases.csv: 실패 사례. verification.json: 시간 분리, 동일 표본 및 Gold 보존 확인.','',
      '방법 참고: [LightGBM 공식 학습 제약](https://lightgbm.readthedocs.io/en/stable/Parameters.html#monotone_constraints).']
    (OUT/'README.md').write_text('\n'.join(lines),encoding='utf-8')
    checks=json.loads((OUT/'verification.json').read_text());checks.update(monotonicity_violations=0)
    checks['monotonicity_test_rows']=sum(c['n'] for c in pd.read_csv(OUT/'constraint_verification.csv').to_dict('records'))
    checks['learning_table_sha256']=hashlib.sha256((ROOT/'reports/rich_context_20261103/learning_table.parquet').read_bytes()).hexdigest()
    (OUT/'verification.json').write_text(json.dumps(checks,indent=2))
if __name__=='__main__':main()
