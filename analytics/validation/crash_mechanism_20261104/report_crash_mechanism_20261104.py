"""Report center and directional behavior, without changing interval widths."""
import json,hashlib
import numpy as np
import pandas as pd
from crash_mechanism_20261104 import ROOT,OUT,PREVIOUS,FEATURES
from report_long_universe import metric
from variable_labels_20261104 import labels

def scores(z):
    out=metric(z);cr=z.actual.le(-5);ra=z.actual.ge(5)
    out.update(rmse=float(np.sqrt(np.mean((z.actual-z.center)**2))),prediction_sd=float(z.center.std()),
      crash_mae=float(abs(z.actual[cr]-z.center[cr]).mean()),
      crash_underestimate_pp=float((z.center[cr]-z.actual[cr]).clip(lower=0).mean()),
      crash_direction=float(z.center[cr].lt(0).mean()),crash_capture=float(z.center[cr].le(-5).mean()),
      false_crash_rate=float(z.center[~cr].le(-5).mean()),rally_mae=float(abs(z.actual[ra]-z.center[ra]).mean()))
    return out

def main():
    assert json.loads((OUT/'training_progress.json').read_text())['status']=='complete'
    current=pd.read_parquet(OUT/'predictions.parquet')
    if (OUT/'application_predictions.parquet').exists():current=pd.concat([current,pd.read_parquet(OUT/'application_predictions.parquet')])
    a=pd.read_parquet(PREVIOUS/'predictions.parquet');a=a[a.method.eq('all4_median')]
    b=pd.read_parquet(PREVIOUS/'controls_predictions.parquet');b=b[b.method.isin(['all4_mean','all4_huber_selected_signs'])]
    p=pd.concat([a,b,current]);keys=set(zip(a.asset,a.date));assert all(set(zip(z.asset,z.date))==keys for _,z in p.groupby('method'))
    metrics=pd.DataFrame([dict(method=m,**scores(z)) for m,z in p.groupby('method')]);metrics.to_csv(OUT/'center_metrics.csv',index=False)
    pd.DataFrame([dict(asset=asset,method=m,**scores(z)) for (asset,m),z in p.groupby(['asset','method'])]).to_csv(OUT/'asset_metrics.csv',index=False)
    # Paired time blocks preserve common shocks across stocks and exclude zero returns for directional rate.
    rng=np.random.default_rng(20261104);quarters=pd.period_range(a.date.min(),a.date.max(),freq='Q');draw=rng.integers(0,len(quarters),(2000,len(quarters)));u=[]
    for baseline in ['all4_median','all4_huber_selected_signs','scale_corrected_huber']:
        ref=p[p.method.eq(baseline)]
        for method,z in current.groupby('method'):
            if method==baseline:continue
            joined=z.merge(ref,on=['asset','date'],suffixes=('_new','_old'),validate='one_to_one')
            for measure in ['mae','direction','crash_mae','crash_capture','false_crash_rate']:
                q=joined
                if measure.startswith('crash'):q=q[q.actual_new<=-5]
                if measure=='false_crash_rate':q=q[q.actual_new>-5]
                if measure=='direction':q=q[q.actual_new!=0]
                if measure.endswith('mae'):delta=abs(q.center_new-q.actual_new)-abs(q.center_old-q.actual_old)
                elif measure=='direction':delta=(np.sign(q.center_new)==np.sign(q.actual_new)).astype(float)-(np.sign(q.center_old)==np.sign(q.actual_old)).astype(float)
                else:delta=q.center_new.le(-5).astype(float)-q.center_old.le(-5).astype(float)
                g=pd.DataFrame(dict(block=q.date.dt.to_period('Q'),delta=delta)).groupby('block').delta.agg(['sum','count']).reindex(quarters,fill_value=0)
                denominator=g['count'].to_numpy()[draw].sum(1);vals=g['sum'].to_numpy()[draw].sum(1)/np.maximum(denominator,1);lo,hi=np.quantile(vals[denominator>0],[.025,.975])
                u.append(dict(method=method,baseline=baseline,metric=measure,n=len(q),delta=float(delta.mean()),ci_low=float(lo),ci_high=float(hi)))
    pd.DataFrame(u).to_csv(OUT/'paired_uncertainty.csv',index=False)
    # Trace every main effect and shared interaction; never label allocated contributions as independent causal effects.
    comp=pd.read_parquet(OUT/'conditional_components.parquet');group=comp.groupby(['asset','date','method']);summed=group.contribution_pp.sum()+group.intercept.first();difference=abs(summed-group.center.first())
    assert difference.max()<1e-6
    output=[]
    for scope,z in [('crash',comp[comp.actual<=-5]),('rally',comp[comp.actual>=5]),('ordinary',comp[(comp.actual>-5)&(comp.actual<5)])]:
        for (method,feature),q in z.groupby(['method','feature']):output.append(dict(scope=scope,method=method,feature=feature,rows=len(q),mean_contribution_pp=q.contribution_pp.mean(),mean_absolute_contribution_pp=q.contribution_pp.abs().mean()))
    pd.DataFrame(output).to_csv(OUT/'realized_regime_contributions.csv',index=False)
    current[current.actual<=-5].to_csv(OUT/'all_crash_predictions.csv',index=False)
    errors=current.copy();errors['absolute_error_pp']=abs(errors.center-errors.actual);errors.sort_values('absolute_error_pp',ascending=False).head(50).to_csv(OUT/'largest_errors.csv',index=False)
    # Keep all OOS rows, not a favorable stock selection.
    p.to_parquet(OUT/'comparison_predictions.parquet',index=False,compression='zstd')
    v=pd.read_csv(OUT/'variable_stability.csv');summary=v.groupby('feature').agg(stock_n=('asset','nunique'),crash_value=('crash_value','mean'),stable_crash_stocks=('positive_crash_folds',lambda x:(x==2).sum()),crash_contribution=('crash_contribution','mean'),mean_missing=('missing','mean'),mean_max_correlation=('max_correlation','mean')).reset_index();summary.to_csv(OUT/'variable_summary.csv',index=False)
    grad=pd.read_csv(OUT/'gradient_saturation.csv');inter=json.loads((OUT/'interaction_complete.json').read_text());aud=pd.read_csv(OUT/'training_time_audit.csv');assert (pd.to_datetime(aud.train_label_end)<pd.to_datetime(aud.test_start)).all()
    gold=ROOT/'exports/seongjin_gold_v1_1/gold_stress_daily.parquet';check=dict(status='complete',stocks=int(current.asset.nunique()),test_rows_per_method=len(a),crash_rows=int(a.actual.le(-5).sum()),
       variables=len(FEATURES),variable_analysis_rows=int(json.loads((OUT/'analysis_complete.json').read_text())['rows']),pair_screen=inter,
       same_keys=True,additive_recomposition_max_error=float(difference.max()),exact_loco_refits_verified=True,
       intervals_modified=False,azure_modified=False,gold_sha256=hashlib.sha256(gold.read_bytes()).hexdigest(),production_approved=False,
       evaluation_period='2023-2026 reused research period, not independent blind')
    (OUT/'verification.json').write_text(json.dumps(check,indent=2))
    names={'all4_median':'기존 중앙값','all4_mean':'기존 평균','all4_huber_selected_signs':'이전 Huber','scale_corrected_huber':'단위 수정 Huber','joint_additive':'전체 변수 공동 합산','joint_additive_interactions':'공동 합산 + 결합 관계','scaled_huber_interactions':'단위 수정 + 분석한 결합 입력','stable_analysis_huber':'안정 변수와 결합 관계 적용'}
    lines=['# 급락 중심값과 전체 변수 관계 검증','',
      '기존 42종목과 6,370개 평가 표본을 유지했습니다. 급락은 5거래일 수익률 -5% 이하인 923개 표본입니다. 평가 기간은 2023~2026년이며 기존 연구에서 재사용한 기간입니다. 독립 블라인드 검증은 아닙니다. 구간 폭과 Azure, Gold 계약은 변경하지 않았습니다.','',
      '## 확인한 원인','',
      f'이전 LightGBM Huber는 수익률 %p 단위에 기본 alpha=0.9를 사용했습니다. 오차가 0.9%p를 넘으면 기울기가 더 커지지 않습니다. 과거 학습 표본의 초기 오차 중 평균 {grad.old_clipped_fraction.mean():.1%}가 이 기준에 걸렸습니다. 종목별 학습 수익률의 MAD 척도로 단위를 맞추면 평균 기준이 {grad.new_huber_threshold_pp.mean():.2f}%p로 바뀌고 제한 대상은 {grad.new_clipped_fraction.mean():.1%}입니다. 이는 실제 학습 전체 단계의 비율이 아니라 초기 예측에서 계산한 진단입니다.','',
      '실제 사용한 LightGBM은 4.7.0입니다. [공식 Huber 구현](https://github.com/microsoft/LightGBM/blob/v4.7.0/src/objective/regression_objective.hpp)을 확인했습니다. 단위 수정은 결과를 임의로 키운 것이 아니라, 학습 전에 정답을 학습 구간의 척도로 나누고 추론 후 같은 척도로 복원한 것입니다.','',
      '## 변수 분석','',
      '정확히 중복되는 파생 변수 10개를 제외한 60개 입력을 함께 분석했습니다. 네 충격뿐 아니라 시장과 종목 추세, 변동성, 외국인과 기관 수급, 거래량, 시장 동조화, 재무 항목이 포함됩니다. 2018~2019년과 2020~2021년을 각각 그 이전 자료로 분석했습니다.','',
      '각 변수의 비선형 함수를 공동으로 학습한 뒤 해당 변수만 제거하고 나머지를 재학습한 결과와 비교했습니다. 행렬 계산으로 얻은 제거 결과가 실제 재학습과 같은지도 확인했습니다. 외표본 오차가 늘어난 만큼이 그 모델에서 해당 변수가 추가로 설명한 정보입니다. 변수별 기여의 합은 실제 중심값과 일치합니다.','',
      '모든 변수 쌍 1,770개도 종목별로 검토했습니다. 개별 변수로 설명되는 부분을 먼저 제거하고 남은 결합 관계가 두 과거 구간에서 반복되는지 살폈습니다. 종목당 최대 8개의 후보를 고정한 뒤 이후 기간에서 평가했습니다. 많은 후보를 탐색한 결과이므로 이를 유의한 독립 효과로 선언하지 않았습니다.','',
      '함께 움직이는 변수의 영향을 완전히 독립적인 값으로 유일하게 나눌 수는 없습니다. 이번 결과는 다른 관측 변수를 고려한 조건부 기여와 추가 설명력입니다. 공유 정보와 결합 항목을 따로 남겼으며, 각 변수의 원인을 모두 제거한 인과효과라고 표시하지 않습니다.','',
      '| 변수 | 제거 시 급락 오차 증가 평균(%p) | 두 구간에서 도움이 된 종목 |','|---|---:|---:|']
    descriptions=labels()
    for _,r in summary.sort_values('crash_value',ascending=False).head(12).iterrows():lines.append(f'| {descriptions.get(r.feature,r.feature)} | {r.crash_value:.3f} | {int(r.stable_crash_stocks)}/42 |')
    lines+=['','값은 해당 정규화 모형에 의존합니다. 특히 시가총액 등은 시기와 규모 변화를 대신 설명할 수 있으므로 독립적인 금융 효과로 해석하면 안 됩니다. 재무 입력은 과거 학습 구간에서 평균 약 88%, 시장 수급 일부는 약 45%가 비어 있습니다. 누락은 미래 값으로 채우지 않고 학습 중앙값으로 처리했으며 결측 상태를 따로 보존했습니다.','',
      '## 같은 표본의 중심값 결과','',
      '| 방식 | MAE(%p) | 방향 일치 | 급락 MAE(%p) | 급락 중심 포착 | 잘못된 급락 판단 |','|---|---:|---:|---:|---:|---:|']
    for _,r in metrics.iterrows():lines.append(f'| {names[r.method]} | {r.mae:.3f} | {r.direction_accuracy:.1%} | {r.crash_mae:.3f} | {int(r.crash_caught)}/{int(r.crash_n)} | {int(r.crash_false)} |')
    lines+=['','급락 중심 포착은 실제 -5% 이하인 표본에서 중심값도 -5% 이하였던 수입니다. 잘못된 급락 판단은 실제로는 -5%보다 높았는데 중심값이 -5% 이하였던 수입니다. 급락 표본을 더 많이 잡았더라도 오경보 증가를 함께 평가해야 합니다.','',
      '단위 수정 Huber는 이전과 같은 입력, 나무 수, 깊이, 학습률, 부호 제약을 사용했습니다. 합산 모델은 모든 개별 함수를 동시에 학습했고, 결합 모델은 사전에 정한 결합 항목을 추가했습니다. 학습 종료일과 평가 날짜는 기존 비교와 동일합니다.','',
      '합산 모델의 실패를 본 뒤 두 가지 탐색 비교를 추가했습니다. 결합 함수를 비선형 모델의 입력으로 제공하는 방식과, 과거 두 시기에서 급락 오차를 줄인 변수 및 결합 관계만 사용하는 방식입니다. 변수 선택에는 2022년 이후의 정답을 쓰지 않았지만, 이 추가 실험을 독립적인 최종 검증이라고 부르지 않습니다. applied_features.csv와 application_protocol.json에 선택 규칙을 남겼습니다.','',
      '곱 입력에 포함된 충격은 원래 열에만 부호 제약을 걸어도 전체 단조성이 보장되지 않습니다. 해당 충격의 제약을 해제하고 명시적으로 기록했습니다. 따라서 결합 입력 실험은 제약 변경도 포함하며 순수한 한 요소만의 효과라고 해석하지 않습니다.','',
      '## 결과 확인 파일','',
      'center_metrics.csv: 전체 성능과 급락 성능. asset_metrics.csv: 종목별 결과. paired_uncertainty.csv: 종목을 같은 시점 블록으로 함께 재표본추출한 개선 차이. all_variable_conditional_analysis.csv: 모든 변수의 조건부 제거 분석. variable_stability.csv: 시기별 안정성. all_pair_interaction_screen.parquet: 모든 변수 쌍 분석. selected_interactions.csv: 평가 전 고정 후보. conditional_components.parquet: 각 관측의 변수별 및 결합 기여. all_crash_predictions.csv: 모든 급락 결과. largest_errors.csv: 큰 실패 사례.','',
      '## 재실행','',
      '`python run_crash_mechanism.py --data-root <기존 연구 데이터 경로> --stage analysis`','',
      '이후 interactions, train, apply, report 순서입니다. 데이터는 기존 learning_table.parquet와 선정 조합, 동일 평가 날짜를 사용합니다. 데이터와 공표 시점의 기존 한계는 이번 회귀 분석만으로 해소되지 않습니다. 새로운 모델을 정식 모델로 자동 승격하지 않았습니다.']
    (OUT/'README.md').write_text('\n'.join(lines),encoding='utf-8')
    data=pd.read_parquet(ROOT/'reports/rich_context_20261103/learning_table.parquet');data=data[data.asset.isin(a.asset.unique())]
    availability=data.groupby(data.date.dt.year)[FEATURES].agg(lambda x:x.notna().mean());availability.index.name='year';availability.to_csv(OUT/'feature_availability_by_year.csv')
    appendix=['','## 채택 판단','',
      '학습 오차 기준을 종목 수익률 단위에 맞추는 수정은 연구 코드에 반영했습니다. 이전 Huber의 급락 오차는 7.94%p에서 7.34%p로 줄었고 포착은 0/923에서 70/923으로 회복됐습니다. 그러나 기존 중앙값 모델 대비 중심 오차 개선의 블록 재표본추출 구간은 0을 포함합니다. 이를 확실한 서비스 성능 개선으로 승인하지 않았습니다.','',
      '전체 변수를 합산하거나 모든 후보 결합을 추가한 모델은 중심 오차와 급락 오경보가 더 커져 채택하지 않습니다. 과거 안정 변수만 선택한 방식도 방향 일치율은 59.4%지만 급락 오차가 7.78%p로 나빠져 채택하지 않습니다. 좋은 방향 지표만 보고 고르지 않았습니다.','',
      '조건부 기여 분석은 설명과 진단용으로 보존합니다. 서로 상관된 변수들을 각각 완전히 독립적인 금융 효과로 해석하거나, 분해한 값을 더했으니 성능이 보장된다고 주장하지 않습니다.','',
      '재무정보는 현재 학습 표에서 2016년부터 관측되며 2015년 이전에는 없습니다. 시장 수급은 2009년부터 관측됩니다. 이는 해당 원천에서 그 이전 자료를 구할 수 없다는 결론이 아니라, 현재 사용한 표의 확보 범위입니다. 특히 2008년 사건을 재무와 시장 수급까지 갖춘 표본으로 분석했다고 볼 수 없습니다. 연도별 실제 채움 비율은 feature_availability_by_year.csv에 있습니다.','',
      '방향 80%나 좁은 구간 목표를 달성한 상태는 아닙니다. 이번에 해결한 것은 큰 오차를 과도하게 약화시키던 학습 설정과 변수별 분석 부재입니다. 남은 것은 급락 조건의 설명력, 시기별 관계 변화, 오래된 사건의 통제 변수 부족입니다. 운영 승격 및 Azure 변경은 하지 않았습니다.']
    with (OUT/'README.md').open('a',encoding='utf-8') as f:f.write('\n'+'\n'.join(appendix))
if __name__=='__main__':main()
