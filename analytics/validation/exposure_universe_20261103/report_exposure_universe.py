"""Write factual research tables after evaluation, without changing selection."""
import json
import pandas as pd
from select_exposure_universe import OUT,SRC

def table(frame):
    cols=list(frame.columns)
    return '\n'.join(['| '+' | '.join(cols)+' |','| '+' | '.join(['---']*len(cols))+' |']+['| '+' | '.join(str(x) for x in row)+' |' for row in frame.itertuples(index=False,name=None)])

def main():
    p=pd.read_csv(OUT/'selected_asset_shock_pairs.csv',dtype={'asset':str})
    e=pd.read_csv(OUT/'eligibility.csv',dtype={'asset':str})
    m=pd.read_csv(OUT/'per_asset_metrics.csv',dtype={'asset':str})
    a=pd.read_csv(OUT/'scope_metrics.csv')
    c=pd.read_csv(OUT/'shock_added_comparison.csv',dtype={'asset':str})
    o=pd.read_csv(OUT/'selected_direction_oos.csv',dtype={'asset':str})
    matched=pd.read_csv(OUT/'matched_date_composition.csv')
    regimes=pd.read_csv(OUT/'selected_regime_metrics.csv')
    ablation=pd.read_csv(OUT/'selected_factor_ablation.csv',dtype={'asset':str})
    summary=json.loads((OUT/'result_summary.json').read_text(encoding='utf8'))
    shocks={'shock_fx':'환율','shock_rate':'미국 10년 금리','shock_oil':'WTI','shock_vix':'VIX'}
    p['충격']=p.shock.map(shocks);p['방향']=p['sign'].map({'positive':'양','negative':'음'})
    p['기간 일치율']=(p.period_sign_agreement*100).round(1).astype(str)+'%'
    p['사건 방향 일치율']=(p.direction_agreement*100).round(1).astype(str)+'%'
    p['계수']=p.coefficient.round(4)
    p['전체수익률 방향']=p.total_return_association_sign.map({'positive':'양','negative':'음'})
    selected_table=p[['name','asset','충격','방향','전체수익률 방향','계수','기간 일치율','사건 방향 일치율','event_n']].rename(columns={'name':'종목','asset':'코드','event_n':'충격 표본'})
    def fmtmetrics(z,scope=True):
        z=z.copy();z['포함률']=(z.coverage*100).round(1);z['하방 이탈률']=(z.lower_breach*100).round(1);z['MAE']=z.mae.round(3);z['폭']=z.width.round(3)
        cols=(['scope'] if scope else ['name'])+['model','spec','n','MAE','포함률','폭','하방 이탈률']
        return z[cols].rename(columns={'scope':'대상','name':'종목','model':'모델','spec':'입력','n':'평가 수'})
    direction=p[['asset','name','shock','sign']].merge(o[['asset','shock','sign','oos_same_sign','direction_agreement','n']],on=['asset','shock'],suffixes=('_train','_test'))
    direction['충격']=direction.shock.map(shocks)
    direction.to_csv(OUT/'direction_comparison.csv',index=False)
    count=p.groupby(['충격','방향']).size().reset_index(name='선정 관계 수')
    primary=a[(a.scope=='selected')&(a.model=='lgb')&(a.spec=='all4')].iloc[0]
    state=a[(a.scope=='selected')&(a.model=='lgb')&(a.spec=='state_only')].iloc[0]
    gain=100*(1-primary.mae/state.mae)
    drop=ablation[(ablation.model=='lgb')&(ablation['mode']=='drop_from_all4')].copy()
    drop['충격']=drop.shock.map(shocks);drop['MAE 개선율(%)']=drop.gain_pct.round(2);drop['보정 q값']=drop.bh_q_diagnostic_family.round(3)
    matched_display=matched[matched.scope.isin(['selected','original20'])].copy();matched_display['spec']='all4'
    oos=o.copy();oos['충격']=oos.shock.map(shocks);oos['학습 방향']=oos.train_sign.map({'positive':'양','negative':'음'});oos['평가 방향']=oos['sign'].map({'positive':'양','negative':'음'});oos['평가 기간 부호 일치율']=(oos.period_sign_agreement*100).round(1)
    text=f'''# 206개 후보 종목 선정 및 종목별 스트레스 모델 검증

## 결론

선정 6종목에서 LightGBM에 네 충격을 함께 넣으면 시장 상태만 사용한 경우보다 중심 오차가 {gain:.2f}% 감소했습니다. 그러나 포함률은 {state.coverage*100:.2f}%에서 {primary.coverage*100:.2f}%로 떨어졌고 하방 이탈률은 {state.lower_breach*100:.2f}%에서 {primary.lower_breach*100:.2f}%로 늘었습니다. 평균 폭은 {primary.width:.2f}%p로 목표 5%p를 넘었습니다.

종목 선별로 기존 20종목보다 중심 오차와 폭이 작은 구성을 찾았지만, 좁고 신뢰할 수 있는 위험 구간까지 확보하지는 못했습니다. 이번 6종목은 학습 기간 기준의 연구 후보입니다. 정식 서비스 종목이나 승인 모델로 전환하지 않았습니다.

## 확인한 범위

206개 후보를 모두 조회하고 같은 선정 기준으로 평가했습니다. 학습 표본과 가격 품질 기준을 통과한 종목은 {int(e.eligible.sum())}개입니다. 선정 조건을 통과한 종목은 {summary['selected']}개, 종목과 충격의 조합은 {len(p)}개입니다. 기준을 통과한 종목은 전부 포함했고, 평가 성능을 보고 추가하거나 빼지 않았습니다.

선정은 2016~2021년 자료만 사용했습니다. 5거래일 정답 종료일은 2021-12-12 이전입니다. 평가 구간은 2023년부터 2026-10-30까지 확보한 자료 안의 완결된 5거래일 구간입니다. 해당 평가 기간은 이전 연구에도 사용했으므로 독립 블라인드 테스트가 아닙니다.

{table(count)}

## 어떤 종목을 선정했는지

방향은 충격이 증가할 때의 통계적 반응입니다. 시장 전체 수익률과 다른 충격을 통제한 계수로 선정했습니다. 따라서 양의 계수라고 해서 주가 자체가 언제나 상승한다는 뜻은 아닙니다. 시장 수익률을 통제하지 않은 전체 수익률의 관계 방향도 별도로 표시했습니다.

계수 단위는 환율과 WTI 변화 1%p, 미국 금리 변화 1bp, VIX 변화 1포인트당 종목 수익률 %p입니다. 인과효과로 해석하지 않습니다.

{table(selected_table)}

세 기간의 계수 부호가 같고, 충격 표본 방향 일치율 60% 이상, 효과 크기와 다중 비교 보정 기준 등을 통과해야 선정했습니다. 전체 기준은 selection_protocol.json에 있습니다. 206개 각각의 제외 이유는 all_candidate_decisions.csv에 있습니다.

## 학습과 평가

종목별 Ridge와 LightGBM을 다시 학습했습니다. 시장 상태만 사용하는 경우와 같은 상태에 네 충격을 추가하는 경우를 비교했습니다. 기존 모델 설정을 고정했고 이번 결과로 튜닝하지 않았습니다. 기존 26종목의 입력과 예측값은 이전 실험과 일치하는지 별도로 확인했습니다.

학습, 보정, 평가를 시간순으로 나눴습니다. 정답 종료일에 20일 간격을 적용했고 보정과 평가 표본의 5거래일 정답 구간이 겹치지 않도록 했습니다. 구간은 이전 모델의 외표본 잔차로 만들었습니다. 실제로 발생한 향후 충격을 사후 입력한 반응 재구성 평가이며, 충격 발생을 미리 예측하는 실험은 아닙니다.

MAE와 폭의 단위는 %p, 포함률과 하방 이탈률의 단위는 %입니다. 목표는 80% 포함률과 평균 전체 폭 5%p 이하입니다.

{table(fmtmetrics(a[a.scope.isin(['original20','prior6','selected'])]))}

## 선정 종목별 결과

{table(fmtmetrics(m[(m.selected)&(m.regime=='all')],False))}

목표를 동시에 충족한 선정 종목과 모델의 조합은 {len(summary['target_met_selected_all4'])}개입니다. 고변동성과 실제 5% 이상 급락 구간은 per_asset_metrics.csv의 high_vol과 asset_crash 행으로 구분했습니다. 평균만으로 급락 위험 성능을 승인하지 않았습니다.

## 기존 20종목과 어떻게 비교했는지

종목 구성이 다르면 변동성 자체가 달라집니다. 따라서 위 평균 차이를 같은 모델의 개선이라고 단정하지 않습니다. 동일 날짜로 맞춘 구성 비교는 matched_date_composition.csv, 같은 종목에서 충격을 추가한 효과는 shock_added_comparison.csv에 있습니다. 후자는 시간 블록 재표본추출의 95% 범위와 다중 비교 보정값을 포함합니다.

다음 표는 모든 비교 종목의 평가값이 있는 공통 63개 날짜만 사용했습니다. 기존 20종목과 선정 6종목에 겹치는 종목은 없습니다. 따라서 서로 다른 종목 구성의 비교입니다.

{table(fmtmetrics(matched_display))}

선정한 {len(direction)}개 관계 중 평가 기간의 통제 회귀에서도 같은 부호를 보인 관계는 {int(direction.oos_same_sign.sum())}개입니다. direction_comparison.csv에 종목별 결과가 있습니다. 이 확인 결과로 선정 목록을 다시 바꾸지 않았습니다. 모델 자체의 충격 민감도는 학습 자료의 중앙 관측 범위 안에서 한 충격씩 바꾼 model_shock_responses.csv로 구분했습니다.

{table(oos[['name','충격','학습 방향','평가 방향','평가 기간 부호 일치율']].rename(columns={'name':'종목'}))}

전체 평가 기간의 계수 부호가 같아도 세부 기간마다 방향이 바뀔 수 있습니다. 평가 자료를 세 부분으로 나눠도 원래 방향이 유지된 것은 대한항공과 DB손해보험입니다. 평가 기간 회귀의 개별 계수 p값은 여섯 관계 모두 0.05보다 컸으므로, 방향 유지 자체를 확실한 통계적 재확인으로 해석하지 않습니다.

## 선정한 충격 자체가 도움이 됐는지

네 충격을 함께 넣은 효과와 선정 근거가 된 개별 충격의 효과를 구분하기 위해 추가 진단을 했습니다. 아래 값은 나머지 세 충격을 둔 상태에서 해당 충격을 추가했을 때의 LightGBM MAE 개선율입니다. 음수이면 오차가 커졌습니다. 이 추가 진단으로 종목을 다시 선정하지 않았습니다.

{table(drop[['name','충격','MAE 개선율(%)','보정 q값']].rename(columns={'name':'종목'}))}

추가 진단의 24개 비교를 보정한 후 q값 0.05 미만으로 오차 개선이 확인된 관계는 없습니다. 선정 단계의 민감도와 외표본 모델의 유용성은 같은 기준이 아닙니다.

## 급락 구간

실제 종목 수익률이 -5% 이하였던 119개 종목-기간 표본에서 LightGBM의 하방 이탈률은 상태 전용 52.10%, 네 충격 추가 59.66%였습니다. 119개는 독립 사건 119개라는 뜻이 아니며 68개 평가 날짜에 걸친 종목별 표본입니다. 급락 구간만을 조건으로 한 진단이므로 전체 명목 이탈률 10%와 직접 동일시하지 않습니다. 다만 같은 급락 표본에서 기존 방식보다 악화됐으므로 개선으로 승인하지 않았습니다.

## 해석과 적용 한계

현재 상장 종목에서 후보를 만들었으므로 과거 상장폐지 종목까지 포함한 생존편향 없는 검증은 아닙니다. 현재 업종에 대한 경제적 설명은 후보 가설이고, 과거 업종 구성 전체를 인증한 자료는 아닙니다. 과거 공표 시각과 개정 이력도 완전하지 않습니다.

선정 단계에서는 WTI가 0 이하인 구간을 제외했습니다. 모델 비교는 기존 기준선과 같은 정의를 유지하므로 과거 음수 WTI에 대한 백분율 충격 정의의 한계가 남습니다. 학습 기간 선택과 실제 시장 수익률 통제 여부에 따라 민감도 해석이 달라질 수 있습니다.

일반적인 외표본 성능이 환율 +5%, 금리 +100bp 같은 희소한 복합 충격을 승인하는 근거는 아닙니다. 새 결과는 연구 결과로 보존했고 Azure, Fabric 계약, 운영 모델은 변경하지 않았습니다.
'''
    (OUT/'결과.md').write_text(text,encoding='utf8')
    print('Report written; inspect actual metrics before final conclusions.')

if __name__=='__main__':main()
