"""Write conclusions from completed diagnostics and retain failed comparisons."""
import json
import pandas as pd
from tail_reliability_research import SRC,OUT

def table(d):
    return '\n'.join(['| '+' | '.join(d.columns)+' |','| '+' | '.join(['---']*len(d.columns))+' |']+['| '+' | '.join(map(str,r))+' |' for r in d.itertuples(index=False,name=None)])

def main():
    agg=pd.read_csv(OUT/'aggregate.csv');p=pd.read_csv(OUT/'per_asset.csv',dtype={'asset':str});pairs=pd.read_csv(SRC/'selected_asset_shock_pairs.csv',dtype={'asset':str});names=dict(zip(pairs.asset,pairs['name']))
    labels={'existing_all4':'기존 충격 모델','online_uniform':'완료된 잔차를 계속 추가','online_recent':'최근 잔차에 높은 가중치','online_conditional':'유사 상태와 충격의 잔차','direct_quantile_raw':'분위수 직접 학습','direct_quantile_recent':'분위수 학습 후 잔차 보정','residual_tail_guard':'하방 여유 유지 참고선','same_width_symmetric_control':'같은 폭의 양쪽 확대 비교안'}
    a=agg[agg.regime=='all'].copy();cr=agg[agg.regime=='asset_crash'].set_index('method')
    a['급락 하방 이탈률(%)']=a.method.map(cr.lower_breach*100).round(1);a['방법']=a.method.map(labels);a['포함률(%)']=(a.coverage*100).round(1);a['평균 폭(%p)']=a.width.round(2);a['구간 점수']=a.interval_score.round(2)
    small=a[['방법','포함률(%)','평균 폭(%p)','급락 하방 이탈률(%)','구간 점수']]
    s=p[(p.method=='residual_tail_guard')&(p.regime=='all')].copy();s['종목']=s.asset.map(names);s['포함률(%)']=(s.coverage*100).round(1);s['폭(%p)']=s.width.round(2)
    old=p[(p.method=='existing_all4')&(p.regime=='asset_crash')].set_index('asset');new=p[(p.method=='residual_tail_guard')&(p.regime=='asset_crash')].set_index('asset')
    s['급락 이탈률 이전(%)']=s.asset.map(old.lower_breach*100).round(1);s['급락 이탈률 수정(%)']=s.asset.map(new.lower_breach*100).round(1)
    failures=pd.read_csv(OUT/'failure_cases.csv',dtype={'asset':str}).head(3);failures['종목']=failures.asset.map(names)
    for k in ['actual','center','q10','guard_q10']:failures[k]=failures[k].round(2)
    text=f'''# 충격 추가 후 급락 포착이 나빠진 원인과 수정 결과

## 결론

급락 포착 악화의 주원인은 LightGBM 중심값보다 하방 잔차 구간의 축소였습니다. 중심값은 개선됐는데 손실 쪽 여유가 더 크게 줄었습니다. 그 축소를 제한하는 코드를 구현하고 같은 표본으로 검증했습니다.

전체 포함률은 78.87%에서 81.92%, 급락 표본의 하방 이탈률은 59.66%에서 47.90%로 개선됐습니다. 대신 폭은 12.91%p에서 13.96%p로 늘었고, 전체 구간 점수는 20.56에서 20.79로 악화됐습니다. 이 수정은 보수적인 하방 참고선을 만드는 개선이며, 더 정확한 80% 확률구간을 확보했다는 뜻은 아닙니다.

따라서 중심값은 기존 LightGBM을 유지하고, 보수적 하방 참고선은 별도 출력으로 추가했습니다. 최근 잔차 가중, 유사 조건 잔차, 직접 분위수 학습은 이번 결과로 채택하지 않았습니다. Azure와 운영 모델, Gold 계약은 변경하지 않았습니다.

## 1. 중심값과 잔차를 분리한 결과

선정 6종목의 같은 918개 종목-기간을 비교했습니다. 평가 시점은 종목별 153개이며 2023-01-02부터 시작하고 마지막 정답 종료일은 2026-10-26입니다. 실제 -5% 이하 급락 표본은 119개, 해당 평가 날짜는 68개입니다. 독립 사건 119개로 해석하지 않습니다.

급락 표본에서 충격을 넣으면 중심값은 평균 0.41%p 낮아졌고 중심 MAE도 7.94%p에서 7.51%p로 감소했습니다. 그러나 잔차의 하방 여유가 평균 1.23%p 줄어 최종 하단은 0.81%p 높아졌습니다.

| 중심값 | 하방 잔차 | 급락 하방 이탈률 |
| --- | --- | --- |
| 상태 모델 | 상태 모델 | 52.10% |
| 충격 모델 | 상태 모델 | 47.90% |
| 상태 모델 | 충격 모델 | 64.71% |
| 충격 모델 | 충격 모델 | 59.66% |

이 교차 조합은 원인을 분해하기 위한 진단입니다. 다른 모델의 잔차를 붙였다는 이유만으로 올바른 확률구간이 되는 것은 아닙니다. 두 변경의 순서를 평균한 분해에서 중심값은 이탈률을 4.62%p 줄이고 잔차 변경은 12.18%p 늘렸습니다.

이는 모델 계산 구조 안의 원인 분해이며 금융 충격의 인과효과를 증명한 결과가 아닙니다. 종목별 결과는 center_interval_by_asset.csv에 있습니다. DB손해보험처럼 잔차 축소가 작고 수정 효과도 거의 없는 종목도 있습니다.

## 2. 직접 비교한 수정안

중심 모델을 동일하게 유지해 구간 산정만 비교했습니다. 최근 오차는 정답 종료일에 20일을 더한 시점이 지나야 사용할 수 있습니다. 아직 결과가 완성되지 않은 표본은 잔차에 넣지 않았습니다. 학습, 보정, 평가의 시간 경계와 기존 예측값 재현을 코드로 검사했습니다.

최근 가중치의 반감기는 365일, 유사 조건 잔차는 60개 이웃을 기준으로 전체 잔차와 50%씩 섞도록 고정했습니다. 결과를 보고 이 숫자를 다시 조정하지 않았습니다. 하방 참고선 수정은 첫 비교 결과를 확인한 뒤 원인에 대응해 추가한 개발 검증입니다. 평가 기간이 반복 사용됐으므로 어느 방법도 독립 블라인드 검증이 아닙니다.

{table(small)}

구간 점수는 폭과 구간 밖 오차를 함께 벌점으로 계산하며 낮을수록 좋습니다. 최근 잔차를 쓰거나 직접 분위수를 학습한다고 자동으로 급락 포착이 좋아지지 않았습니다.

## 3. 하방 참고선은 어떻게 계산하는지

충격 모델의 중심값과 상단은 그대로 둡니다. 하방 잔차는 상태 전용 모델과 충격 모델 중 더 손실 쪽인 값을 사용합니다. 추가 여유는 두 모델의 기존 외표본 잔차에서 계산하며, 평가 정답을 보고 금액을 정하지 않습니다.

이 출력은 모델 불확실성을 보수적으로 반영한 손실 참고선입니다. 검증된 VaR, ES, 최악의 손실 또는 명목 80% 확률구간으로 표시하지 않습니다.

같은 총폭을 양쪽에 절반씩 추가한 비교안은 급락 이탈률이 54.62%였고 하방에 배분한 방식은 47.90%였습니다. 하방 배분의 효과는 있었지만, 전체 구간 점수는 같은 폭의 비교안보다도 조금 나빴습니다. 정밀도 전체가 개선됐다고 주장하지 않습니다.

10개 평가 날짜 단위 블록을 2,000회 재표본추출했습니다. 같은 날짜의 모든 종목을 함께 뽑고 급락 표본이 없는 날짜도 유지했습니다. 기존 방식 대비 급락 이탈률 차이는 -11.76%p, 95% 재표본 범위는 -19.23~-5.43%p입니다. 같은 폭 비교안 대비 차이는 -6.72%p, 범위는 -11.71~-2.06%p입니다. 이는 재사용한 연구 표본 안의 불확실성이며 새 데이터에 대한 보장이 아닙니다.

{table(s[['종목','포함률(%)','폭(%p)','급락 이탈률 이전(%)','급락 이탈률 수정(%)']])}

## 4. 여전히 해결되지 않은 부분

현재 중심값의 위아래 2.5%p만 허용하면 실제 포함률은 43.68%입니다. 따라서 잔차 보정만으로 현재 중심값을 유지하면서 폭 5%p와 포함률 80%를 동시에 얻었다고 할 수 없습니다. 이것이 모든 다른 5%p 구간의 수학적 불가능성을 증명한 것은 아닙니다.

급락 119개 중 42개에서는 네 충격 모두 해당 학습 기간 절대 변화량의 75% 분위수 안에 있었습니다. 네 충격이 크게 움직이지 않은 구간에서도 개별 종목은 급락했습니다. 이것만으로 특정 뉴스나 기업 사건이 원인이라고 단정할 수는 없지만, 현재 네 변수로 모든 급락을 설명하지 못하는 한계는 구분해야 합니다.

수정 후에도 다음 사례는 놓쳤습니다. 단위는 %입니다.

{table(failures[['종목','date','actual','center','q10','guard_q10']].rename(columns={'date':'평가 시점','actual':'실제 수익률','center':'중심값','q10':'기존 하단','guard_q10':'수정 참고선'}))}

2026년만 분리하면 참고선 방식의 포함률은 79.80%, 폭은 19.05%p입니다. 전체 평균으로 최근 구간의 한계를 숨기지 않습니다. 미국 지표의 공표 시각과 개정 이력 미확인, 음수 WTI의 기존 변화율 정의 등 이전 데이터 한계도 그대로 남습니다.

## 5. 서비스에 제공할 정보와 남은 조건

로컬 계산기에 다음 출력을 분리했습니다.

1. 입력한 충격에서의 종목별 모델 중심값과 보유금액 환산값입니다.
2. 같은 시장 상태에서 충격을 0으로 둔 경우와의 차이입니다. 전체 손익을 전부 충격의 영향이라고 설명하지 않습니다.
3. 보수적 하방 참고선입니다. 발생 확률이나 최대 손실로 표시하지 않습니다.
4. 실제 관측된 과거 사례의 충격과 수익률입니다. 사용자 조건과 동일한 사건으로 바꿔 설명하지 않습니다.
5. 학습 범위 밖 입력, 모델 버전, 시장 상태 기준일입니다.

tail_scenario_examples.py에 계산 코드를 두었습니다. 2026-10-30 확정 일별 상태와 종목별 100만 원이라는 설명용 보유금액으로 30개 결과를 생성했습니다. scenario_examples.json에서 입력 피처, 모델 해시, 요인별 모델 기여도, 과거 관측값을 확인할 수 있습니다. 요인 기여도는 모델 내부 입력 변경의 분해이며 인과적 기여도가 아닙니다.

예를 들어 대한항공은 다른 충격을 0으로 두고 환율 +1%를 입력하면 모델 중심값이 -0.99%에서 -2.20%로 바뀝니다. 총 가상 손익은 약 -22,010원, 충격 입력에 따른 모델값 차이는 약 -12,104원입니다. 이 둘을 구분해야 합니다. 보수적 하방 참고선은 -10.39%이며 그 손실의 발생 확률을 검증했다는 뜻은 아닙니다.

이 구조로 탐색용 서비스를 구현하는 작업은 진행할 수 있습니다. 다만 사용자가 믿을 만한 정밀 손실 추정 서비스로 주장하려면 별도 새 기간에서 현재 수정안을 고정해 검증하고, 종목별 실패 구간과 충격 지원 범위를 확인해야 합니다. 폭 5%p와 포함률 80%는 아직 달성하지 못했습니다. 추가적인 기업별 설명 변수가 필요한지는 실패 사례에 대해 공표 시각이 확인된 자료로 별도 검증해야 하며, 이번에 Gold를 임의로 확장하지 않았습니다.
'''
    (OUT/'결과.md').write_text(text,encoding='utf8')
    decision={'centre':'retain existing LGB for research exploration','interval_candidates_rejected':['online_uniform','online_recent','online_conditional','direct_quantile_raw','direct_quantile_recent'],
        'implemented_reference':'residual_tail_guard, explicitly conservative and not certified VaR/ES or80% probability interval','target_width5_coverage80_met':False,'production_model_changed':False,
        'verified_service_functions':['conditional scenario vs zero-shock comparison','model contribution sum identity','holding amount multiplication','separate historical observed responses','out-of-training-marginal-range flags','versioned state and model evidence'],
        'unresolved':['material crash misses remain','wide intervals','no independent new holdout','point-in-time macro releases not certified','joint shock support not certified']}
    (OUT/'service_decision.json').write_text(json.dumps(decision,indent=2),encoding='utf8')

if __name__=='__main__':main()
