import json
import numpy as np
import pandas as pd
from research_shock_context import OUT,SRC

def main():
    assert json.loads((OUT/'progress.json').read_text())['status']=='complete'
    r=pd.read_parquet(OUT/'predictions.parquet');base=r[r.method.eq('baseline')]
    months=pd.period_range(r.date.min(),r.date.max(),freq='M');n=len(months);rng=np.random.default_rng(20261103)
    ix=np.array([np.concatenate([(s+np.arange(3))%n for s in rng.integers(n,size=(n+2)//3)])[:n] for _ in range(2000)])
    rows=[]
    for method,z in r.groupby('method'):
        if method=='baseline':continue
        q=z.merge(base,on=['asset','date'],suffixes=('_new','_old'),validate='one_to_one')
        for name in ['mae_change','direction_gain']:
            h=q if name=='mae_change' else q[q.actual_new.ne(0)]
            delta=(h.center_new-h.actual_new).abs()-(h.center_old-h.actual_old).abs() if name=='mae_change' else (np.sign(h.center_new)==np.sign(h.actual_new)).astype(int)-(np.sign(h.center_old)==np.sign(h.actual_old)).astype(int)
            key=h.date.dt.to_period('M');num=delta.groupby(key).sum().reindex(months,fill_value=0).to_numpy();den=h.groupby(key).size().reindex(months,fill_value=0).to_numpy();ds=den[ix].sum(axis=1);v=num[ix].sum(axis=1)/np.maximum(ds,1);lo,hi=np.quantile(v[ds>0],[.025,.975])
            rows.append(dict(method=method,metric=name,change=delta.mean(),ci_low=lo,ci_high=hi,n=len(h)))
    pd.DataFrame(rows).to_csv(OUT/'paired_uncertainty.csv',index=False)
    c=pd.read_csv(OUT/'validation_choices.csv');choice=c[c.chosen].method.value_counts();choice.to_csv(OUT/'chosen_method_counts.csv')
    names=pd.read_csv(SRC/'eligible_pairs.csv',dtype={'asset':str}).drop_duplicates('asset').set_index('asset')['name']
    am=pd.read_csv(OUT/'asset_metrics.csv',dtype={'asset':str})
    a=am[am.method.eq('validation_selected')].merge(am[am.method.eq('baseline')],on='asset',suffixes=('_new','_base'))
    chosen=c[c.chosen].copy();chosen['asset']=chosen.asset.astype(str).str.zfill(6)
    a=a.merge(chosen[['asset','method']],on='asset',validate='one_to_one');a['name']=a.asset.map(names)
    compact=a[['asset','name','method','n_new','direction_accuracy_base','direction_accuracy_new','mae_base','mae_new','crash_caught_base','crash_caught_new']].copy()
    compact.columns=['종목코드','종목명','2022년선택방식','평가관측수','기존방향일치율','선택방식방향일치율','기존중심오차pp','선택방식중심오차pp','기존급락포착수','선택방식급락포착수']
    compact.to_csv(OUT/'종목별_개선결과.csv',index=False,encoding='utf-8-sig')
    hist=pd.read_csv(OUT/'historical_response_map.csv',dtype={'asset':str});flips=[]
    for (a,s,sign),z in hist[(hist.period=='pre2022')&(hist.n>=30)].groupby(['asset','shock','shock_direction']):
        flips.append(dict(asset=a,shock=s,shock_direction=sign,supported_regimes=len(z),min_median=z.actual_median.min(),max_median=z.actual_median.max(),direction_changes_across_regimes=bool(z.actual_median.min()<0<z.actual_median.max())))
    pd.DataFrame(flips).to_csv(OUT/'regime_direction_changes.csv',index=False)
    metrics=pd.read_csv(OUT/'metrics.csv');lines=['# 충격과 시장 상황의 관계 분석','', '기존 101종목은 고정했습니다. 가격 품질 조건과 5거래일 목표를 유지하고, 과거 시장 민감도, 상관관계, 하락 변동성, 변동성 비율, 추세 가속도, 직전 거시 흐름과 충격의 상호작용을 추가했습니다. 종목이나 틀린 결과를 평가 후 제거하지 않았습니다.','',
    '2022년 검증에서 기존 모델보다 방향, 중심 오차, 급락 오차가 모두 같거나 좋아진 방법만 선택했습니다. 선택은 2023년 이후 평가 전에 고정했습니다. 이후 평가 결과로 다시 선택하지 않았습니다. 연구 전체에서 평가 기간은 재사용했으므로 독립 블라인드라고 부르지 않습니다.','',
    '## 전체 비교','', '| 방법 | 표본 | 방향 일치 | 중심 MAE | 고정 5%p 진단 포함률 |','|---|---:|---:|---:|---:|']
    for _,v in metrics[metrics.scope.eq('all')].iterrows():lines.append(f'| {v.method} | {v.n} | {v.direction_accuracy:.2%} | {v.mae:.3f}%p | {v.fixed5_coverage:.2%} |')
    lines+=['','baseline은 기존 피처의 원수익률 LightGBM, context는 추가 상태 및 상호작용 피처, recent5는 같은 추가 피처에 최근 5년 학습, ridge_context는 추가 피처의 Ridge, validation_selected는 2022년에 고정한 종목별 선택입니다.','',
    '## 충격 구간 비교','', '| 방법 | 방향 일치 | 중심 MAE |','|---|---:|---:|']
    for _,v in metrics[metrics.scope.eq('selected_shock_events')].iterrows():lines.append(f'| {v.method} | {v.direction_accuracy:.2%} | {v.mae:.3f}%p |')
    lines+=['','## 파일','',
    '- historical_response_map.csv: 같은 충격의 상승과 하락을 직전 추세와 변동성으로 나눈 실제 종목 반응입니다. 30개 미만은 sparse로 표시했습니다. 다른 동시 충격을 통제한 인과효과가 아닙니다.',
    '- regime_direction_changes.csv: 학습 기간에서 30개 이상 관측된 시장 상태별 중앙 반응이 반대로 나타난 조합입니다.',
    '- context_importance.csv: 2022년 검증에서 해당 정보 묶음을 섞었을 때 증가한 오차입니다. 양수이면 모델이 그 정보에 의존해 성능을 얻었다는 의미입니다. 음수나 작은 값도 그대로 남겼습니다.',
    '- validation_choices.csv: 종목별 사전 선택과 실패한 후보를 포함합니다.',
    '- asset_metrics.csv, metrics.csv: 종목별 및 전체 결과와 급등, 급락 성능입니다.',
    '- paired_uncertainty.csv: 3개월 시간 블록으로 재표본추출한 개선의 불확실성입니다. 다중 비교 보정은 하지 않은 탐색 결과입니다.','',
    '공표 시각과 당시 수정주가 버전은 완전히 검증되지 않았고, 업종 및 기업 실적 데이터는 현재 학습표에 없습니다. 새로운 원천 정보를 검증 없이 만들지 않았습니다. 일별 피처만 사용했으며 장중 시세를 같은 피처로 섞지 않았습니다. Azure, 운영 모델, Gold 계약은 변경하지 않았습니다. 고정 폭 포함률은 가능성 진단이지 승인된 확률 구간이 아닙니다.']
    lines+=['','## 이번 판단','',
    '추가 상태와 상호작용은 평균 오차를 4.542%p에서 4.523%p로 줄였지만, 시간 블록 불확실성 구간에 개선 없음이 포함되고 방향 일치율도 개선되지 않았습니다. 안정적인 성능 개선으로 채택하지 않습니다. 최근 5년만 사용하거나 2022년 성적에 따라 종목별 방식을 고르는 방법은 이후 성능이 더 나빴습니다.','',
    '2022년 정보 섞기 검사에서 VIX를 섞으면 평균 오차가 약 0.300%p, 환율은 0.089%p 증가했습니다. 종목 과거 이력은 0.061%p, 거시 과거 이력은 0.028%p, 유가와 금리 및 시장 과거 이력은 약 0.012~0.015%p입니다. 이 수치는 해당 검증 기간과 모델에서의 정보 의존도이며, 충격의 경제적 효과 크기나 확정적인 중요도 순위가 아닙니다.','',
    '같은 방향의 충격이어도 시장 상황에 따라 실제 반응이 달라진 조합이 있었습니다. 이를 모두 같은 방향으로 학습하도록 강제하지 않았습니다. 관측이 적은 세부 조건은 별도로 표시했습니다.','',
    'remaining_error_market_diagnostic.csv는 실제 시장 수익률과 남은 오차의 사후 연관성입니다. 실제 미래 시장 수익률을 모델 입력에 넣지 않았고 초과수익률 모델을 다시 학습하지도 않았습니다. 종목별 사후 선형 연관성 R²의 중앙값은 약 0.082입니다. 오차를 전부 시장 움직임 하나로 설명할 수 있다는 근거도 확인되지 않았습니다.','',
    '다음에 검증할 데이터는 당시 업종 분류와 업종 흐름, 실적 발표 및 공시 시각, 기업별 환율·원재료 노출 같은 종목별 정보입니다. 현재 학습표에는 없으므로 이번 연구에서 검증했다고 주장하지 않습니다. 사후 기업 실적이나 현재 업종 분류를 과거에 덮어쓰는 방식은 사용하지 않습니다. 기존 네 충격과의 설명력 차이는 이후 같은 시간순 기준으로 확인해야 합니다.']
    (OUT/'README.md').write_text('\n'.join(lines)+'\n',encoding='utf8')

if __name__=='__main__':main()
