import json
import numpy as np
import pandas as pd
from reselect_shock_direction import OUT

def main():
    r=pd.read_parquet(OUT/'predictions.parquet');new=r[r.selected];dates=np.array(sorted(new.date.unique()));n=len(dates);rng=np.random.default_rng(20261103)
    draws=np.array([np.concatenate([(s+np.arange(10))%n for s in rng.integers(0,n,size=(n+9)//10)])[:n] for _ in range(2000)])
    results=[]
    for model,base in [('all4_lgb','state_lgb'),('all4_direction_route','state_direction_route'),('focused_direction_route','state_direction_route')]:
        a=new[new.method.eq(model)];b=new[new.method.eq(base)];z=a.merge(b,on=['asset','date'],suffixes=('_a','_b'),validate='one_to_one')
        for scope,x in [('all',z),('selected_shock_events',z[z.event_a])]:
            for metric in ['direction','mae']:
                q=x[x.actual_a.ne(0)] if metric=='direction' else x
                delta=((np.sign(q.center_a)==np.sign(q.actual_a)).astype(float)-(np.sign(q.center_b)==np.sign(q.actual_b)).astype(float)) if metric=='direction' else (q.center_a-q.actual_a).abs()-(q.center_b-q.actual_b).abs()
                num=delta.groupby(q.date).sum().reindex(dates,fill_value=0).to_numpy();den=q.groupby('date').size().reindex(dates,fill_value=0).to_numpy();ds=den[draws].sum(axis=1);s=num[draws].sum(axis=1)/np.maximum(ds,1);lo,hi=np.quantile(s[ds>0],[.025,.975])
                results.append(dict(model=model,baseline=base,scope=scope,metric=metric,n=len(q),delta=delta.mean(),ci_low=lo,ci_high=hi))
    pd.DataFrame(results).to_csv(OUT/'paired_uncertainty.csv',index=False)
    sw=pd.read_csv(OUT/'shock_sweep.csv',dtype={'asset':str});sw['year']=pd.to_datetime(sw.date).dt.year;responses=[]
    for (asset,year),q in sw.groupby(['asset','year']):
        v=q.groupby('shock_value').up_score.mean().sort_index();responses.append(dict(asset=asset,year=year,shock=q.shock.iloc[0],score_shift=v.iloc[-1]-v.iloc[0],sign='positive' if v.iloc[-1]>v.iloc[0] else 'negative'))
    pd.DataFrame(responses).to_csv(OUT/'response_stability.csv',index=False)
    m=pd.read_csv(OUT/'metrics.csv',dtype={'group':str});sel=pd.read_csv(OUT/'selected_pairs.csv',dtype={'asset':str})
    lines=['# 충격 반응을 기준으로 종목 재선정','',
    '## 학습 정의','',
    '입력은 충격 직전 확정 일별 시장 상태와 이후 5거래일의 환율, 미국 금리, 유가, VIX 변화입니다. 정답은 같은 5거래일의 종목 전체 수익률입니다. 실제 발생한 충격을 사후 입력한 조건부 재구성이며 인과효과나 미래 충격 발생 예측은 아닙니다.', '',
    '충격 0을 넣는 것은 입력을 빼는 것이 아닙니다. 각 변수의 5거래일 변화가 0이라는 조건을 넣는 것입니다. 이것이 실제 무충격 세계의 정답이라는 뜻은 아닙니다. 이번 성능 비교는 0 충격 시나리오가 아니라 동일한 실제 과거 표본에서 수행했습니다.', '',
    '## 이전 선정과 다른 점','',
    '이전 선정은 실제 같은 기간 시장 수익률을 통제한 민감도를 진단했습니다. 시장 통제 후 반응이 일관적이어도 전체 종목 수익률 방향이 일관적이라는 뜻은 아닙니다. 이번에는 시장 전체 수익률을 미래 입력으로 사용하지 않고, 사전 시장 상태만 사용한 모델보다 충격을 추가한 모델이 실제 전체 종목 방향을 더 잘 설명하는지로 선정했습니다.', '',
    'KRX 후보 206개를 출발 목록으로 사용했고 기존 표본 수 및 가격 품질 기준을 통과한 종목에서 평가했습니다. 2019~2021년을 시간순 내부 검증에 사용하고 매년 그 이전 자료만 학습했습니다. 2022년 이후 결과는 선정에 사용하지 않았습니다. 각 충격의 큰 변화는 학습 기간 절대 변화량의 상위 25% 기준입니다.', '',
    '선정 최소 사건 표본 수 45개까지 충족한 후보는 없었습니다. 따라서 아래는 사전 규칙에 따라 상위 6개를 고른 탐색 후보입니다. 민감도가 검증된 최종 종목으로 표시하지 않습니다. 선택 과정의 여러 비교로 내부 성능이 부풀 수 있으므로 이후 기간 성능을 따로 평가했습니다.', '',
    '| 후보 | 우선 충격 | 내부 방향 일치 | 내부 사건 수 |','|---|---|---:|---:|']
    labels={'shock_vix':'VIX','shock_rate':'미국 금리','shock_fx':'환율','shock_oil':'WTI'}
    for _,a in sel.iterrows():lines.append(f'| {a["name"]} | {labels[a.shock]} | {a.accuracy:.1%} | {a.n} |')
    lines+=['','## 이후 기간 학습 및 평가','','KRX 공식 원본 55개 구간을 추가 확보했습니다. 기존 데이터와 연구 결과는 보존했습니다. 새로운 6종목과 기존 6종목을 재학습했고 기존 6종목 LightGBM 결과는 이전 값과 일치했습니다. 2023~2026년 6종목 각각 153개 평가 표본을 사용했습니다. 이 기간은 프로젝트 연구에서 사용한 기간이므로 독립 블라인드라고 부르지 않습니다.','',
    '| 비교 | 방향 일치 | 중심값 MAE |','|---|---:|---:|']
    for method in ['state_lgb','all4_lgb','state_direction_route','all4_direction_route']:
        a=m[(m.group=='selected6')&(m.method==method)&(m.scope=='selected_shock_events')].iloc[0]
        lines.append(f'| {method} | {a.direction_accuracy:.1%} | {a.mae:.2f}%p |')
    lines+=['','위 표는 선정한 충격의 큰 변화가 발생한 동일 231개 종목별 관측입니다. 보합을 제외한 방향 평가 분모는 227개입니다. 서로 다른 종목의 같은 날짜가 포함되므로 독립 충격 231건이 아닙니다.','',
    'LightGBM은 수익률을 직접 학습합니다. direction_route는 상승 및 하락을 분류한 후 학습 기간의 해당 방향 대표 수익률을 적용합니다. 따라서 방향 모델의 금액이 더 정확하다고 단정하지 않습니다. 분류 점수는 검증된 미래 확률이 아닙니다.','',
    '## 종목별 큰 충격 구간','','| 후보 | 관측 수 | 상태만 사용 | 네 충격 추가 |','|---|---:|---:|---:|']
    for _,a in sel.iterrows():
        q=m[(m.group==a.asset)&(m.scope=='selected_shock_events')].set_index('method');lines.append(f'| {a["name"]} | {int(q.loc["all4_lgb","n"])} | {q.loc["state_lgb","direction_accuracy"]:.1%} | {q.loc["all4_lgb","direction_accuracy"]:.1%} |')
    lines+=['','## 결론과 남은 한계','','새 후보에서 네 충격의 정보가 도움이 되는 근거는 나왔습니다. 그러나 삼성카드와 한화생명은 해당 충격 구간에서 LightGBM 방향 개선이 없었습니다. 이 결과를 보고 두 종목을 빼서 전체 성능을 다시 계산하지 않았습니다. 개별 종목 및 충격 범위를 좁힐 후보 근거로만 사용합니다.','',
    '모든 평가 구간에서는 새 6종목 LightGBM 방향 일치가 55.8%로, 기존 6종목의 58.5%보다 낮습니다. 종목 구성이 달라 직접적인 모델 개선으로 해석할 수 없습니다. 새 6종목 안에서 상태만 사용한 방향 일치 50.8%와 비교하면 개선됐습니다. 큰 충격 구간의 결과를 모든 조건에 일반화하지 않습니다.','',
    '급락 87개 중 중심값도 -5% 이하였던 것은 8개, 급등 122개 중 +5% 이상이었던 것은 6개입니다. 큰 충격 조건의 방향성이 좋아져도 급등락 손실 규모 문제는 해결된 것이 아닙니다. 5%p 전체 폭 진단 포함률도 약 49%여서 80% 목표에 미달했습니다. 폭 확대는 하지 않았습니다.','',
    '이번에는 특정 종목의 네 충격 전체 효과와 선정 충격 하나의 효과를 별도로 비교했습니다. 네 충격 모델이 좋아졌다고 그 개선 전부를 선정 충격 하나 때문이라고 주장하지 않습니다. focused 모델과 response_stability.csv를 함께 확인해야 합니다.','',
    '서비스 후보는 모든 종목 및 충격을 동일하게 신뢰하는 방식보다 종목과 조건별 검증 결과를 명시하는 방식입니다. 현재는 연구 계산과 과거 관측을 비교할 수 있으나 검증된 예상 손실이나 인과효과로 승인하지 않습니다. 운영 모델 자동 교체도 하지 않습니다.','',
    '공표 시각 및 데이터 개정 이력, 현재 종목 목록 기반 생존 편향, 기존 WTI 음수 가격 처리 한계는 남아 있습니다. 단일 선정 규칙과 재사용 평가 기간만으로 최종 승인하지 않습니다.','',
    '## 재실행','','scripts에서 reselect_shock_direction.py, collect_reselected_candidates.py --selected, evaluate_reselected_direction.py, summarize_reselection.py 순서입니다. 수집만 .venv-krx-batch, 나머지는 .venv를 사용했습니다. 기존 select_exposure_universe.py 및 asset_feature_research.py 의존 코드가 필요합니다.','',
    'all_pairs.csv는 전체 후보와 탈락 기준, selected_pairs.csv는 고정한 후보, metrics.csv는 전체 및 충격 구간별 성능, paired_uncertainty.csv는 날짜 10개 블록 2,000회 재표본추출입니다. 원천 데이터와 인증정보는 공개 저장소에 올리지 않습니다. Azure와 Gold 계약은 변경하지 않았습니다.']
    (OUT/'결과.md').write_text('\n'.join(lines)+'\n',encoding='utf8')
if __name__=='__main__':main()
