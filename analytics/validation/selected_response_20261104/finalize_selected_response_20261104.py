"""Combine fixed comparison and explicitly exploratory follow-up without promoting a winner."""
import json
import numpy as np
import pandas as pd
from train_selected_response_20261104 import ROOT,OUT,score

def main():
    p=pd.concat([pd.read_parquet(OUT/'predictions.parquet'),pd.read_parquet(OUT/'controls_predictions.parquet')])
    s=pd.concat([pd.read_parquet(OUT/'shock_interventions.parquet'),pd.read_parquet(OUT/'controls_interventions.parquet')])
    names=['all4_median','selected_median','selected_mean','selected_monotone_mean','all4_mean','all4_huber','all4_huber_selected_signs']
    base=p[p.method.eq('all4_median')];keys=set(zip(base.asset,base.date));assert all(set(zip(p[p.method.eq(m)].asset,p[p.method.eq(m)].date))==keys for m in names)
    agg=pd.DataFrame([dict(method=m,**score(p[p.method.eq(m)])) for m in names]);agg.to_csv(OUT/'final_aggregate.csv',index=False)
    quarters=pd.period_range(base.date.min(),base.date.max(),freq='Q');rng=np.random.default_rng(20261104);draw=rng.integers(0,len(quarters),(2000,len(quarters)));rows=[]
    comparisons=[(m,'all4_median') for m in names[1:]]+[('all4_huber_selected_signs','all4_huber'),('selected_mean','all4_mean')]
    for new,reference in comparisons:
        t=p[p.method.eq(new)].merge(p[p.method.eq(reference)],on=['asset','date'],suffixes=('_new','_base'),validate='one_to_one')
        for measure in ['mae','direction']:
            q=t if measure=='mae' else t[t.actual_new.ne(0)]
            delta=abs(q.center_new-q.actual_new)-abs(q.center_base-q.actual_base) if measure=='mae' else (np.sign(q.center_new)==np.sign(q.actual_new)).astype(float)-(np.sign(q.center_base)==np.sign(q.actual_base)).astype(float)
            g=pd.DataFrame(dict(block=q.date.dt.to_period('Q'),delta=delta)).groupby('block').delta.agg(['sum','count']).reindex(quarters,fill_value=0)
            boot=g['sum'].to_numpy()[draw].sum(1)/g['count'].to_numpy()[draw].sum(1);lo,hi=np.quantile(boot,[.025,.975])
            rows.append(dict(method=new,reference=reference,measure=measure,delta=delta.mean(),ci_low=lo,ci_high=hi))
    pd.DataFrame(rows).to_csv(OUT/'final_uncertainty.csv',index=False)
    pd.DataFrame([dict(asset=a,method=m,**score(z)) for (a,m),z in p[p.method.isin(names)].groupby(['asset','method'])]).to_csv(OUT/'final_asset_metrics.csv',index=False)
    summary=s.groupby(['asset','shock','method']).agg(n=('response_pp','size'),mean_response_pp=('response_pp','mean'),positive_fraction=('response_pp',lambda x:(x>1e-8).mean()),negative_fraction=('response_pp',lambda x:(x<-1e-8).mean())).reset_index();summary.to_csv(OUT/'final_response_summary.csv',index=False)
    pairs=pd.read_csv(OUT/'frozen_pairs.csv',dtype={'asset':str});events=[];data=pd.read_parquet(ROOT/'reports/rich_context_20261103/learning_table.parquet')
    for _,r in pairs.iterrows():
        history=data[data.asset.eq(r.asset)&data.end_date.lt(pd.Timestamp('2021-12-12'))];low,high=history[r.feature].quantile([.25,.75])
        for m,z in p[p.asset.eq(r.asset)&p.method.isin(names)].groupby('method'):
            q=z[(z[r.feature]<=low)|(z[r.feature]>=high)];events.append(dict(asset=r.asset,shock=r.feature,method=m,scope='shock_tail',**score(q)))
        z=s[s.asset.eq(r.asset)&s.shock.eq(r.feature)&s.method.eq('all4_huber_selected_signs')]
        assert (z.response_pp*r.sign>=-1e-8).all()
    pd.DataFrame(events).to_csv(OUT/'final_shock_event_metrics.csv',index=False)
    crash=p[p.method.eq('all4_huber_selected_signs')&p.actual.le(-5)].copy();crash.to_csv(OUT/'followup_all_crash_cases.csv',index=False)
    a=agg.set_index('method').loc['all4_median'];b=agg.set_index('method').loc['all4_huber_selected_signs']
    appendix=['','## 추가 원인 분리와 최종 판단','',
      '첫 비교에서 선정되지 않은 충격을 빼면 성능이 나빠졌습니다. 통제 변수로서의 역할을 확인하기 위해 네 충격을 모두 유지하고, 평균 학습과 이상치에 덜 끌리는 Huber 학습을 추가했습니다. 부호 제약은 앞에서 고정한 49개 조합에만 적용했습니다. 이 추가 비교는 첫 결과를 본 뒤 수행한 탐색이며 새로운 블라인드 평가가 아닙니다.','',
      '| 방식 | MAE(%p) | 방향 일치 | 80% 포함률 | 폭(%p) | 급락 하방 이탈 | 급락 중심 포착 |','|---|---:|---:|---:|---:|---:|---:|']
    labels={'all4_median':'네 충격 중앙값','selected_median':'선정 충격 중앙값','selected_mean':'선정 충격 평균','selected_monotone_mean':'선정 충격 평균 + 부호','all4_mean':'네 충격 평균','all4_huber':'네 충격 Huber','all4_huber_selected_signs':'네 충격 Huber + 선정 부호'}
    for _,r in agg.iterrows():appendix.append(f'| {labels[r.method]} | {r.mae:.3f} | {r.direction_accuracy:.1%} | {r.coverage80:.1%} | {r.width_pp:.2f} | {r.crash_lower_breach:.1%} | {int(r.crash_caught)}/{int(r.crash_n)} |')
    appendix += ['',f'Huber와 선정 부호를 결합하면 기준선 대비 MAE가 {(1-b.mae/a.mae):.1%} 줄고 방향 일치율은 {(b.direction_accuracy-a.direction_accuracy)*100:.2f}%p 높아졌습니다. 그러나 급락 시 하방 이탈은 {a.crash_lower_breach:.1%}에서 {b.crash_lower_breach:.1%}로 악화됐고, 중심값으로 -5% 이하 급락을 잡은 건 {int(b.crash_caught)}건입니다. 전체 오차의 개선을 스트레스 분석 개선으로 승인하지 않았습니다. 목표인 평균 폭 5%p와 포함률 80%에도 미달합니다.','',
      '단조 제약을 추가한 효과와 Huber 학습 자체의 효과는 final_uncertainty.csv에서 분리했습니다. 부호를 강제한 것만으로 예측 정보가 늘었다고 주장하지 않습니다. 기존 운영 모델과 선정 규칙은 그대로 유지합니다.','',
      '대한항공의 유가 입력을 낮은 학습 분위수에서 높은 분위수로 바꿨을 때 기존 모델은 평가 상태의 92.2%에서 하락 반응을 계산했습니다. S-Oil은 99.3%에서 상승 반응을 계산했습니다. 이는 모델의 입력 변화 반응이며 실제 방향 적중률이 아닙니다. 관계가 아예 반영되지 않았던 것이 아니라, 반응의 평균 차이만으로 개별 5일 수익률의 큰 변동을 설명하지 못한 것입니다.','',
      '## 네 충격과 시장 상태의 합산','',
      '기존 공동 잔차 모델도 직접 확인했습니다. 시장 상태로 설명되는 수익률과 네 충격을 과거 외표본에서 각각 계산하고, 설명되지 않은 네 충격을 동시에 넣어 잔여 수익률을 학습하고 있었습니다. 환율과 유가를 따로 회귀해서 결과를 무작정 합치는 구조는 아닙니다.','',
      '`종목 수익률 = 시장 상태의 평균 반응 + Σ 계수 × (사용자 충격 - 해당 상태의 평균 충격)`','',
      '시장 상태 평균에 이미 포함된 충격 부분을 빼고 사용자 충격을 더하므로 중복을 방지합니다. 사용자에게는 이를 0충격 기준 수익률과 네 충격의 추가 기여도로 다시 나눌 수 있습니다. four_shock_decomposition.csv는 보존된 2026년 모델의 실제 합산입니다. recomposition_check.csv에서 42종목의 기존 계산과 일치함을 검증했습니다. 이 모델은 이번 동일 학습 구간 모델들과 학습 종료일이 달라, 추가 성능 비교에는 섞지 않았습니다.','',
      '이 분해는 관측한 변수에 대한 통계적 분해입니다. 누락 변수, 비선형 관계, 공표 시각 문제를 모두 없앤 순수한 인과효과는 아닙니다. 이미 수집한 모든 변수의 영향까지 완전히 설명했다고 주장하지 않습니다.','',
      '## 충격 0과 미입력의 차이','',
      '금리 +1bp는 금리 4.20%를 4.21%로 바꾸는 뜻입니다. 나머지 충격 0은 환율, 유가, VIX의 기존 수준 유지입니다. 수준을 0으로 만드는 것이 아닙니다. shock_semantics_check.json에서 계산을 검증했습니다.','',
      '0은 향후 5거래일 누적 변화가 0이라는 뜻입니다. 기간 중 전혀 움직이지 않는 경로를 학습한 모델은 아닙니다.','',
      '기존 웹앱 엔진은 요청에서 빠진 요인을 과거 관측값으로 주변화합니다. 따라서 금리만 보내는 요청과 나머지 세 충격을 모두 0으로 보낸 요청은 다릅니다. 연구 시나리오 도우미는 네 변화량을 전부 요구하며 누락을 거절합니다. 이번 연구에서는 웹앱, API, Azure 설정을 바꾸지 않았으므로 웹앱의 미입력 동작은 여전히 남아 있습니다.','',
      '추가 재실행 단계: followup, joint-audit, finalize. 모델을 서비스로 자동 승격하지 않습니다.']
    path=OUT/'README.md';text=path.read_text(encoding='utf-8').split('\n## 추가 원인 분리와 최종 판단')[0];path.write_text(text+'\n'+'\n'.join(appendix),encoding='utf-8')
    verification=json.loads((OUT/'verification.json').read_text());verification.update(followup_complete=True,followup_identical_keys=True,models=len(names),test_rows_per_model=len(base),
      joint_recomposition_max_error=float(pd.read_csv(OUT/'recomposition_check.csv').max_recomposition_error.max()),
      zero_shock_semantics_checked=True,web_omitted_shock_semantics_not_changed=True,tail_safety_passed=False,production_approved=False)
    (OUT/'verification.json').write_text(json.dumps(verification,indent=2))
if __name__=='__main__':main()
