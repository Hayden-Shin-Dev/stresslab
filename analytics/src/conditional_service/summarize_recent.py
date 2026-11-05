"""Publish reproducible diagnosis tables, preserving the local service artifact."""
import json,hashlib,shutil
from pathlib import Path
import joblib,numpy as np,pandas as pd

def main():
    out=Path('reports/recent_support_scope_20261105');diagnosis=Path('reports/recent_diagnosis_20261105')
    module=Path(__file__).parent;bundle=joblib.load('reports/service_scope_20261105/final_service_bundle.joblib')
    p=pd.read_parquet(out/'predictions.parquet');recent=p[p.year>=2025]
    table=[]
    d=pd.read_parquet(diagnosis/'data_ablation.parquet')
    c=pd.read_csv(diagnosis/'coefficient_stability.csv',dtype={'asset':str});c=c[c.model=='baseline']
    for a,z in recent.groupby('asset'):
        q=d[(d.asset==a)&(d.year>=2025)]
        r=dict(asset=a,name=bundle['names'][a],observations=len(z),dates=z.date.nunique(),
            baseline_mae_pp=float(abs(z.actual-z.baseline).mean()),selected_mae_pp=float(abs(z.actual-z.selected_fixed_train).mean()),
            zero_mae_pp=float(abs(z.actual).mean()),data_correction_delta_mae_pp=float(abs(q.actual-q.corrected_all).mean()-abs(q.actual-q.old_all).mean()))
        for s in ['fx_pct','us_rate_bp','wti_pct','vix_points']:
            r[s+'_coefficient_sign_changes']=int(c[(c.asset==a)&(c.shock==s)].sign_changes.iloc[0])
        table.append(r)
    stocks=pd.DataFrame(table);stocks.to_csv(out/'recent_stock_summary.csv',index=False)
    metrics=pd.read_csv(out/'metrics.csv');allm=metrics[metrics.period=='all'].set_index('model');rm=metrics[metrics.period=='2025_2026'].set_index('model')
    improved=bool(allm.loc['selected_fixed_train','mae_pp']<allm.loc['baseline','mae_pp'] and
                  rm.loc['selected_fixed_train','mae_pp']<rm.loc['baseline','mae_pp'] and
                  rm.loc['selected_fixed_train','crash_underestimate_pp']<=rm.loc['baseline','crash_underestimate_pp'])
    assert not improved,'Review new results explicitly before changing this documented decision'
    decision=dict(local_service_model_replaced=False,reason='No joint MAE and downside improvement; retain corrected service model, not old uncertified model.',
                  tested_configs=18,grid_selection='Past validation only; served-stock scope corrected',
                  evaluation_not_blind=True,intervals_widened=False,azure_changed=False,gold_changed=False,
                  model_sha256=hashlib.sha256(Path('reports/service_scope_20261105/final_service_bundle.joblib').read_bytes()).hexdigest())
    (out/'adoption_decision.json').write_text(json.dumps(decision,indent=2),encoding='utf8')
    evidence=module/'service_evidence/recent_diagnosis';evidence.mkdir(exist_ok=True)
    for name in ['protocol.json','metrics.csv','choices.json','splits.json','inner_validation.csv','stock_metrics.csv','coefficient_stability.csv','uncertainty.json','verification.json','recent_stock_summary.csv','adoption_decision.json']:
        shutil.copy2(out/name,evidence/name)
    for name in ['data_effect_summary.json','data_effect_by_stock.csv','center_diagnosis.json','explained_failures.csv']:
        shutil.copy2(diagnosis/name,evidence/name)
    comparison='\n'.join(f"| {label} | {rm.loc[key,'mae_pp']:.3f} | {rm.loc[key,'direction']*100:.1f}% | {rm.loc[key,'crash_underestimate_pp']:.3f} |" for key,label in [('baseline','기존 정정 모델'),('selected_fixed_train','과거 검증으로 설정 선택'),('baseline_refit','직전 연도까지 갱신'),('selected_refit','설정 선택 후 갱신'),('zero','항상 0 수익률'),('sector','기존 업종 충격 Ridge')])
    worst=stocks.assign(extra=lambda x:x.baseline_mae_pp-x.zero_mae_pp).nlargest(5,'extra')
    stocktext='\n'.join(f"| {r['name']} | {r['baseline_mae_pp']:.3f} | {r['zero_mae_pp']:.3f} | {r['data_correction_delta_mae_pp']:+.3f} |" for r in worst.to_dict('records'))
    report=f'''# 2025~2026년 오차 원인과 제한적 개선 결과

기존 정정 모델을 보존합니다. 정규화와 학습 기간을 바꿔 실제 재학습했지만, 평균 오차와 급락 대응을 함께 개선한 후보는 없었습니다. 모델이 학습됐다는 사실만으로 개선 완료로 처리하지 않습니다.

## 같은 조건의 백테스트

기존 50종목, 같은 85개 날짜와 4,150개 종목 관측을 그대로 비교했습니다. 최근 2025~2026년은 43개 날짜, 2,057개 관측입니다. 실제 발생한 네 충격을 사후 입력한 반응 재구성 평가입니다. 가상 사건의 정확도나 인과효과 검증이 아닙니다.

학습 정답은 평가 전에 끝나며 20일 간격을 둡니다. 설정 선택은 평가 전년도 검증에서만 합니다. 같은 날짜의 종목을 묶어 4개 날짜 블록으로 불확실성을 계산했습니다. 이 기간을 반복 연구했으므로 독립 블라인드 결과가 아닙니다.

| 최근 기간 비교 | MAE %p | 방향 일치율 | 급락 손실 과소평가 %p |
| --- | ---: | ---: | ---: |
{comparison}

급락은 실제 5거래일 수익률 -5% 이하인 412개 관측입니다. 과소평가는 max(모델값-실제값, 0)의 평균입니다. 항상 0인 모델의 방향 일치율은 실제 수익률도 0인 경우만 맞춘 것이므로 방향 기준선으로 해석하지 않습니다.

## 데이터 정정의 영향

같은 최근 평가 표본에서 이전 값과 같은 Ridge 설정으로 다시 학습하면 MAE는 5.545%p입니다. 이것도 0 기준선 5.285%p보다 나쁩니다. 따라서 정정만으로 성능 부진을 설명할 수 없습니다.

| 정정 순서 | MAE %p | 직전 단계 대비 |
| --- | ---: | ---: |
| 이전 학습 표본과 값 | 5.545 | 기준 |
| 정정 후와 같은 학습 행만 유지 | 5.631 | +0.087 |
| 학습 값 정정, 평가 입력은 이전 값 | 5.504 | -0.128 |
| 평가 시장 상태도 정정 | 5.511 | +0.008 |
| 평가 충격 값까지 정정 | 5.657 | +0.145 |

순서에 따른 계산 분해이며 독립적인 인과 기여도가 아닙니다. 학습 값 정정 자체는 오히려 개선했습니다. 표본 제외와 충격 관측 구간의 변경이 오차를 늘렸습니다. 이전 값은 당시 사용 가능성이 확인되지 않은 진단 대조군이며 다시 서비스에 쓰지 않습니다.

## 계수와 중심값에서 확인한 문제

연도별 재학습 계수 부호가 바뀐 종목은 환율 14개, 미국 금리 18개, WTI 12개입니다. VIX는 0개지만 부호가 같다고 손실 크기를 설명하는 것은 아닙니다. 전체 계수와 종목별 변화는 `coefficient_stability.csv`에 있습니다.

최근 급락 표본의 실제 평균은 -9.379%, 모델 평균은 -0.209%입니다. 무충격 기준값은 +0.247%이고 네 충격의 합계 변화는 약 -0.456%p입니다. 급등 표본에서도 실제 평균 +10.939%에 모델은 -0.317%였습니다. 작은 충격 계수와 시장 상태 항의 잘못된 중심값이 함께 문제입니다.

시장 상태 항만 사후 제거하면 최근 MAE는 5.657에서 5.388%p로 줄지만, 급락 MAE는 9.452에서 9.611%p로 나빠집니다. 따라서 평가 결과를 보고 이 항을 무조건 지우지는 않았습니다. 최근 2,057개 관측 중 411개는 적어도 하나의 상태 피처가 학습 범위를 벗어났고, 100개는 충격이 범위를 벗어났습니다. 이는 변수별 범위 검사이며 다변량 지원 범위의 증명은 아닙니다.

종목별로 0 기준선 대비 악화가 컸던 예입니다. 정정 영향은 같은 표본에서 정정 전후 MAE 차이입니다.

| 종목 | 기존 정정 MAE | 0 기준선 | 데이터 정정 영향 |
| --- | ---: | ---: | ---: |
{stocktext}

예를 들어 2025-01-02 SKC의 실제 5거래일 반응은 +47.31%, 모델은 -0.68%였습니다. 2025-06-13 NAVER는 실제 +34.41%, 모델 -3.14%였습니다. 해당 사례의 시장 상태와 충격별 계산 항은 `explained_failures.csv`에 있습니다. 이 오차를 특정 기업 사건 때문이라고 원인 확정한 것은 아닙니다.

## 수정하고 비교한 부분

Ridge alpha 300/3000, 종목 편차 규제 3/10/30, 전체/최근 5년의 12개 설정을 비교했습니다. 시장 상태 계수와 충격 계수의 규제를 분리한 6개 설정도 추가했습니다. 변수와 가산형 계산식은 유지했습니다.

전체 학습 집단으로 설정을 고르던 부분은 실제 해당 모델이 서비스하는 종목의 검증 점수로 고치었습니다. 공동 학습에는 기존 18종목/68종목 집단을 유지합니다. 검증에서 평균 오차가 줄어도 급락 과소평가가 기존보다 5% 넘게 악화된 설정은 제외했습니다.

직전 1년의 보정 자료로 계수를 다시 갱신하는 방법도 별도 비교했습니다. 최근 MAE가 5.829%p로 악화돼 채택하지 않았습니다. 오래된 계수라는 사실만으로 갱신 효과를 단정할 수 없었습니다.

최종 선택 정책의 최근 개선은 약 0.002%p에 그쳤고 급락 과소평가는 소폭 악화됐습니다. 날짜 블록 신뢰구간도 개선을 확정하지 못합니다. 구간을 넓히거나 평가 수익률을 보고 계수를 수동 변경하지 않았습니다.

## 채택 판단과 재현

18개 설정 안에서 과거 검증으로 선택한 정책은 기존보다 우수하다고 판단할 근거가 없습니다. 기존 정정 서비스 모델과 API는 유지하고 새 설정은 연구 결과로 보존합니다. 업종 Ridge는 비교 평균이 더 낮지만 이것만으로 종목별 민감도를 대체하거나 평가 결과에 맞춰 승격하지 않습니다. 현재 모델의 탐색용 표시도 유지합니다.

Azure, Gold, 기존 모델 파일과 지원 50종목은 변경하지 않았습니다. 입력 원본 해시, 동일 평가 표본, 기준선 재현 검사는 `verification.json`에서 확인할 수 있습니다.

연구 폴더에서 팀 저장소 `analytics/src`를 PYTHONPATH로 지정한 뒤 실행합니다.

```powershell
$env:STRESSLAB_DIAGNOSIS_PHASE = "1"
python -m conditional_service.diagnose_recent
python -m conditional_service.explain_recent_failures
$env:STRESSLAB_DIAGNOSIS_PHASE = "2"
python -m conditional_service.diagnose_recent
$env:STRESSLAB_DIAGNOSIS_PHASE = "3"
python -m conditional_service.diagnose_recent
python -m conditional_service.summarize_recent
```

원본 연구 자료와 고정 모델이 필요합니다. 상세 계산은 로컬 `reports/recent_diagnosis_20261105`, 최종 비교는 `reports/recent_support_scope_20261105`에 저장합니다. 저장소의 [검증 자료](service_evidence/recent_diagnosis)에는 종목별 성능, 정정 영향, 실패 사례와 선택 기준을 제공합니다.
'''
    (module/'RECENT_DIAGNOSIS.md').write_text(report,encoding='utf8')
    print(json.dumps(decision))

if __name__=='__main__':main()
