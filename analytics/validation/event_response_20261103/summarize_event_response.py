"""Directional accuracy, tail misses, false alarms and feature evidence."""
import json
import numpy as np
import pandas as pd
from event_response_research import OUT

def main():
    r=pd.read_parquet(OUT/'predictions.parquet');b=r[r.method.eq('baseline')]
    dates=np.array(sorted(r.date.unique()));n=len(dates);rng=np.random.default_rng(20261103)
    draws=np.array([np.concatenate([(s+np.arange(10))%n for s in rng.integers(0,n,size=(n+9)//10)])[:n] for _ in range(2000)])
    output=[]
    for name,z in r.groupby('method'):
        if name=='baseline':continue
        x=z.merge(b,on=['asset','date'],suffixes=('_new','_old'),validate='one_to_one')
        for metric in ['mae','direction','crash_recall','rally_recall']:
            q=x
            if metric=='mae':delta=q.mae_new-q.mae_old
            elif metric=='direction':
                q=q[q.actual_old.ne(0)];delta=(np.sign(q.center_new)==np.sign(q.actual_old)).astype(float)-(np.sign(q.center_old)==np.sign(q.actual_old)).astype(float)
            elif metric=='crash_recall':
                q=q[q.actual_old<=-5];delta=(q.center_new<=-5).astype(float)-(q.center_old<=-5).astype(float)
            else:
                q=q[q.actual_old>=5];delta=(q.center_new>=5).astype(float)-(q.center_old>=5).astype(float)
            num=delta.groupby(q.date).sum().reindex(dates,fill_value=0).to_numpy();den=q.groupby('date').size().reindex(dates,fill_value=0).to_numpy();ds=den[draws].sum(axis=1)
            sample=num[draws].sum(axis=1)/np.maximum(ds,1);lo,hi=np.quantile(sample[ds>0],[.025,.975])
            output.append(dict(method=name,metric=metric,n=len(q),delta=delta.mean(),ci_low=lo,ci_high=hi))
    pd.DataFrame(output).to_csv(OUT/'paired_uncertainty.csv',index=False)
    imp=pd.read_csv(OUT/'feature_permutation.csv',dtype={'asset':str})
    imp.groupby('feature').agg(mean_logloss_increase=('logloss_increase','mean'),positive_fold_fraction=('logloss_increase',lambda x:(x>0).mean())).sort_values('mean_logloss_increase',ascending=False).to_csv(OUT/'feature_summary.csv')
    imp.groupby(['asset','feature']).agg(mean_logloss_increase=('logloss_increase','mean'),positive_fold_fraction=('logloss_increase',lambda x:(x>0).mean())).to_csv(OUT/'feature_by_asset.csv')
    # Entire common event list, not selected illustrative successes.
    ev=b[b.actual.abs()>=5][['asset','date','actual','center']].rename(columns={'center':'baseline'})
    for name,z in r.groupby('method'):
        if name=='baseline':continue
        ev=ev.merge(z[['asset','date','center']].rename(columns={'center':name}),on=['asset','date'],validate='one_to_one')
    ev.to_csv(OUT/'all_extreme_cases.csv',index=False)
    m=pd.read_csv(OUT/'metrics.csv',dtype={'asset':str});s=m[m.asset.eq('ALL')]
    names={'baseline':'기존 중앙값','engineered_median':'추가 피처 중앙값','base_natural_mixture':'기존 피처 사건 혼합','base_natural_route':'기존 피처 사건 선택','engineered_natural_mixture':'추가 피처 사건 혼합','engineered_natural_route':'추가 피처 사건 선택','engineered_balanced_mixture':'급등락 균형 학습 혼합','engineered_balanced_route':'급등락 균형 학습 선택'}
    lines=['# 급락과 급등 반응 학습','',
    '선정 6종목의 같은 918개 평가 표본을 사용했습니다. 실제 이후 5거래일 충격을 사후 입력한 조건부 재구성입니다. 미래 충격 발생이나 인과효과를 평가한 것이 아닙니다. 2023~2026년을 이미 사용했으므로 독립 블라인드 검증이 아닙니다.', '',
    '## 무엇을 바꿨는가','',
    '기존 중앙값 회귀와 별도로 급락(-5% 이하), 보통, 급등(+5% 이상)을 학습했습니다. 사건 판별을 스트레스 계산의 보조 실험으로 추가한 것이며 서비스 목적을 주가 방향 예측으로 변경한 것은 아닙니다.', '',
    '추가 피처는 충격 4개와 시장 추세, 시장 변동성, 종목 추세, 종목 변동성, 시장 대비 상대수익률의 조합 20개입니다. 단기 및 장기 변동성 비율 2개, 추세 가속 2개도 추가했습니다. 해당 시점 이전 시장 상태와 조건으로 주어진 충격만 사용했습니다.', '',
    '사건 혼합은 세 사건의 학습 기간 대표 수익률을 분류 점수로 가중 평균합니다. 사건 선택은 가장 높은 점수의 사건 대표값을 사용하고, 보통이면 별도 중앙값 회귀를 사용합니다. 따라서 혼합값은 조건부 중앙값이 아니고, 선택값은 불연속적인 시나리오 대표값입니다. 분류 점수는 검증된 미래 발생 확률이 아닙니다.', '',
    '균형 학습은 학습 기간에서 드문 사건에 가중치를 줍니다. 평가 결과를 보고 임계값이나 가중치를 조정하지 않았습니다. 모델 종류와 피처 효과를 분리하기 위해 기존 피처 분류기와 추가 피처 분류기도 함께 비교했습니다.', '',
    '## 전체 결과','',
    '| 방법 | 방향 일치 | 중심 MAE | 급락 포착 | 급락 경고 적중 | 급등 포착 | 급등 경고 적중 |','|---|---:|---:|---:|---:|---:|---:|']
    for _,v in s.iterrows():lines.append(f'| {names[v.method]} | {v.direction_accuracy:.1%} | {v.mae:.2f}%p | {v.crash_recall:.1%} | {v.crash_precision:.1%} | {v.rally_recall:.1%} | {v.rally_precision:.1%} |')
    lines += ['',f'항상 상승이라고 할 때 방향 일치율은 {s.iloc[0].always_up_accuracy:.1%}입니다. 실제 수익률 0은 방향 평가에서 제외하고 direction_n에 분모를 기록했습니다. 종목별 결과와 상승 및 하락을 동일 비중으로 평가한 결과도 metrics.csv에 있습니다.', '',
    '급락 포착률은 실제 급락 중 중심값도 -5% 이하로 계산한 비율입니다. 경고 적중률은 -5% 이하로 계산한 것 중 실제 급락한 비율입니다. 급등도 같은 기준입니다. 이 기준은 위험 구간 하방 이탈률과 다릅니다. 극단 사건 표본은 종목별 관측이며 독립 사건 수가 아닙니다.', '',
    '폭은 기존 구간의 표본별 폭을 그대로 유지했습니다. 새 중심값만큼 평행 이동한 진단 결과이며 새로 보정한 80% 확률구간이 아닙니다. 중심값 ±2.5%p 포함률도 metrics.csv에 따로 기록했습니다.', '',
    '## 특징 분석을 읽는 방법','',
    'training_feature_contrasts.csv는 학습 기간에서 급락과 급등일 때 어떤 특징이 달랐는지 보여줍니다. feature_summary.csv와 feature_by_asset.csv는 평가 표본에서 피처를 섞었을 때 사건 분류가 얼마나 나빠지는지 보여줍니다. 값이 양수면 그 피처가 해당 평가에서 도움이 된 흔적입니다. 상관된 피처는 중요도가 분산되므로 경제적 원인이나 인과적 기여도로 해석하지 않습니다.', '',
    '평가 피처 중요도는 결과 진단용입니다. 이 값을 이용해 다시 피처를 선택하거나 모델을 재학습하지 않았습니다. 하나의 피처가 모든 종목과 모든 기간에 유효하다고 보장하지 않습니다. 공시, 뉴스, 당시 업종 지표가 없는 상태에서 분석하지 않은 특징까지 모두 분석했다고 주장하지 않습니다.', '',
    'all_extreme_cases.csv에는 성공 사례만 고르지 않고 실제 급등락 257개 관측 전부의 계산값을 넣었습니다. paired_uncertainty.csv는 전체 날짜 축에서 10개 평가 날짜 블록으로 2,000회 재표본추출한 비교입니다.', '',
    '## 이번 판단','',
    '추가 피처 사건 혼합은 전체 MAE가 4.124%p에서 4.010%p로 약 2.8% 줄었습니다. 날짜 블록 비교의 MAE 차이 구간은 -0.228~-0.013%p입니다. 다만 여러 개발 실험 중 얻은 결과이며 독립 검증이 아닙니다. 급락 중심값 오차는 7.51%p에서 7.93%p로 악화됐고, 방향 일치율 개선의 구간에는 0이 포함됐습니다. 전체 오차 개선 후보로만 남깁니다.', '',
    '급등락 균형 학습 선택은 급락 119개 중 39개, 급등 138개 중 56개를 포착했습니다. 기존은 각각 7개와 8개였습니다. 하지만 급락 경고 125개 중 86개, 급등 경고 221개 중 165개가 오경보였습니다. 전체 MAE도 4.12%p에서 4.99%p로 악화됐습니다. 더 큰 값을 자주 출력해서 포착률을 높인 측면이 있으므로 이 방식으로 중심값을 교체하지 않습니다.', '',
    '피처 진단에서는 최근 20일 환율 추세, 유가 충격, 시장 60일 추세, VIX 충격과 종목 변동성 조합 등이 상위에 나타났습니다. 다만 모든 종목과 기간에서 같은 효과가 유지되지는 않았습니다. 피처 중요도 순위를 보고 평가 기간에 맞게 모델을 다시 선택하지 않았습니다.', '',
    '기존 폭을 고정했으며, 중심값 ±2.5%p 진단 포함률도 가장 높은 이번 혼합 방식에서 약 45%입니다. 5%p 폭과 80% 포함률 목표를 충족하지 못했습니다. 급등락을 직접 학습하는 것은 구현됐으나 적중률까지 확보한 서비스 모델은 아닙니다. 실험 모델을 운영에 반영하지 않습니다.', '',
    '## 재실행 및 운영 범위','',
    '기존 exposure_universe_20261103의 learning_table.parquet, predictions.parquet, selected_assets.json을 사용합니다. scripts/event_response_research.py 실행 후 scripts/summarize_event_response.py를 실행합니다. asset_feature_research.py 등 기존 연구 의존 코드가 필요합니다.', '',
    '기존 출처와 학습 표를 유지했습니다. 공표 시각 및 과거 수정 이력의 미확인, 현재 종목 목록 기반 생존 편향, WTI 음수 가격 처리 한계도 남아 있습니다. Azure, Gold, 운영 모델은 변경하지 않았습니다. 코드 및 결과는 5dt024/ml에서 관리하고 자동 승격하지 않습니다.']
    (OUT/'결과.md').write_text('\n'.join(lines)+'\n',encoding='utf8')
if __name__=='__main__':main()
