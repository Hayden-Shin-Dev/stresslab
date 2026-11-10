"""Report matched stock-level benchmark without selecting on evaluation results."""
import json
from pathlib import Path
import numpy as np
import pandas as pd
from gold_quantile_benchmark import ROOT,FEATURES
from compare_gold20_locked_20261104 import OUT,GROUPS,metrics
NAMES={'baseline':'초기 Gold CatBoost 재현','raw_target':'동일 CatBoost, 수익률 정규화 제거','lgb_same_features':'동일 18개 입력, LightGBM 중앙값','flows':'CatBoost + 수급','liquidity':'CatBoost + 가격과 거래대금','peers':'CatBoost + 20종목 동조화','company':'CatBoost + 재무비율','all_added':'CatBoost + 추가 변수 전체','prior_selected':'개발 구간에서 사전 선정','stock_selected':'종목별 개발 구간 선정(후속 탐색)','fixed_blend':'기준선 50% 고정 결합(후속 탐색)'}
STOCKS={'000270':'기아','000660':'SK하이닉스','005380':'현대차','005930':'삼성전자','005935':'삼성전자우','006400':'삼성SDI','009150':'삼성전기','012330':'현대모비스','012450':'한화에어로스페이스','028260':'삼성물산','032830':'삼성생명','034020':'두산에너빌리티','034730':'SK','055550':'신한지주','068270':'셀트리온','086790':'하나금융지주','105560':'KB금융','207940':'삼성바이오로직스','373220':'LG에너지솔루션','402340':'SK스퀘어'}

def table(df,fields,labels):
    lines=['| '+' | '.join(labels)+' |','| '+' | '.join(['---']*len(fields))+' |']
    for _,r in df.iterrows():lines.append('| '+' | '.join(str(r[f]) for f in fields)+' |')
    return '\n'.join(lines)

def main():
    m=pd.read_csv(OUT/'metrics.csv').set_index('method');b=m.loc['baseline'];selection=json.loads((OUT/'frozen_selection.json').read_text());chosen=selection['chosen']
    s=m.loc[chosen];ci=pd.read_csv(OUT/'paired_block_bootstrap.csv').set_index('method')
    passes=bool(chosen!='baseline' and s.mae<b.mae and s.direction>=b.direction and s.crash_mae<=b.crash_mae)
    status='제한된 연구 개선 후보입니다. 운영 모델로 승격하지 않았습니다.' if passes else '최종 평가에서 방향과 중심값 및 급락 오차의 동시 개선 조건을 통과하지 못했습니다. 초기 기준선을 유지합니다.'
    (OUT/'decision.json').write_text(json.dumps(dict(preselected=chosen,passes_point_direction_crash_guard=passes,retained_research_method=chosen if passes else 'baseline',production_promoted=False,interval_modified=False),indent=2),encoding='utf8')
    pred=pd.read_parquet(OUT/'predictions.parquet');audit=pd.concat([pd.read_csv(p,dtype={'asset':str}) for p in (OUT/'evaluation').glob('*.csv')],ignore_index=True);audit.to_csv(OUT/'fit_audit.csv',index=False)
    centers=[]
    for method,z in pred.groupby('method'):
        cr=z[z.actual<=-5];up=z[z.actual>=5]
        centers.append(dict(method=method,actual_std=z.actual.std(),center_std=z.center.std(),actual_positive_fraction=z.actual.gt(0).mean(),center_positive_fraction=z.center.gt(0).mean(),crash_actual_mean=cr.actual.mean(),crash_center_mean=cr.center.mean(),surge_actual_mean=up.actual.mean(),surge_center_mean=up.center.mean(),actual_center_correlation=z[['actual','center']].corr().iloc[0,1]))
    centers=pd.DataFrame(centers).set_index('method');centers.to_csv(OUT/'center_diagnostics.csv')
    assert audit.baseline_reproduction_max_error.dropna().max()<1e-7
    a=pred[pred.method=='baseline'][['asset','date','actual','center']].rename(columns={'center':'baseline_center'})
    changes=pred[pred.method==chosen].merge(a,on=['asset','date','actual'],validate='one_to_one');changes['absolute_error_change']=abs(changes.actual-changes.center)-abs(changes.actual-changes.baseline_center)
    changes.sort_values('absolute_error_change',ascending=False).head(30).to_csv(OUT/'failure_examples.csv',index=False)
    rows=[]
    for method,r in m.iterrows():rows.append(dict(method=NAMES[method],mae=f'{r.mae:.3f}',direction=f'{r.direction*100:.2f}%',gain=f'{(b.mae-r.mae)/b.mae*100:+.2f}%',crash=f'{r.crash_mae:.3f}',caught=f'{int(r.crash_caught)}/{int(r.crash_n)}',false=int(r.false_crash)))
    per=pd.read_csv(OUT/'per_stock.csv',dtype={'asset':str});rows2=[]
    for asset in sorted(STOCKS):
        old=per[(per.asset==asset)&(per.method=='baseline')].iloc[0];new=per[(per.asset==asset)&(per.method==chosen)].iloc[0]
        rows2.append(dict(asset=asset,name=STOCKS[asset],n=int(old.n),before=f'{old.mae:.3f}',after=f'{new.mae:.3f}',direction0=f'{old.direction*100:.1f}%',direction1=f'{new.direction*100:.1f}%'))
    per['asset_name']=per.asset.map(STOCKS);per.to_csv(OUT/'per_stock.csv',index=False)
    improvements=int(sum(float(r['after'])<float(r['before']) for r in rows2))
    train=audit.groupby('method').agg(train_mae=('train_mae','mean'),missing=('added_train_missing','mean')).reset_index();train.to_csv(OUT/'fit_gap_summary.csv',index=False)
    avail=pd.read_csv(OUT/'feature_availability_by_period.csv')
    report=f'''# 초기 Gold CatBoost와 20종목 동일 조건 비교

기존 20종목, 2,928개 종목별 평가값을 고정했습니다. 평가일은 2023-01-02부터 2026-10-19까지이며, 169개 날짜입니다. 상장 이력이 짧은 종목은 최초 기준선에 결과가 존재하는 날짜만 사용했습니다. 모든 방법에서 종목과 날짜가 같습니다.

## 결과

{table(pd.DataFrame(rows),['method','direction','mae','gain','crash','caught','false'],['방법','방향 일치율','중심값 MAE(%p)','기준선 대비 MAE 개선','급락 MAE(%p)','급락 중심값 포착','오경보'])}

급락은 실제 5거래일 수익률이 -5% 이하인 경우입니다. 포착은 모델 중심값도 -5% 이하인 경우이고, 오경보는 실제 급락이 아닌데 중심값이 -5% 이하인 경우입니다. 방향 일치율에서는 실제 수익률이 정확히 0인 표본만 제외했습니다. 구간을 넓혀 개선하지 않았습니다.

## 실제 적용 후보

2020~2021년 개발 구간에서 선정된 방법은 **{NAMES[chosen]}**입니다. 선정은 2023년 이후 평가를 실행하기 전에 파일로 고정했습니다. 조건은 개발 MAE 1% 이상 개선, 방향 일치율 유지, 급락 MAE 유지, 두 개발 연도 모두 MAE 악화 없음입니다. 통과한 변수군이 없으면 초기 기준선을 유지합니다. 개발 구간에는 당시 학습 가능한 18종목의 1,512개 표본이 있습니다. LG에너지솔루션과 SK스퀘어는 이 선정 과정에서 검증되지 않았으며, 이후 20종목 평가에 포함했습니다.

**판단: {status}**

이 사전 선정 결과의 평가 MAE는 {b.mae:.3f}에서 {s.mae:.3f}%p, 방향 일치율은 {b.direction*100:.2f}%에서 {s.direction*100:.2f}%입니다. 종목별 MAE가 감소한 종목은 {improvements}/20개입니다. 평가 결과를 보고 가장 좋은 방법을 다시 골라 적용하지 않았습니다.

전체 결과를 확인한 뒤 두 가지 후속 탐색도 수행했습니다. 첫째는 2020~2021년 정보만으로 종목별 변수군을 선택하는 방식, 둘째는 초기 기준선 50%에 네 변수군 모델을 각각 12.5% 결합하는 방식입니다. 결합 가중치는 평가값에 맞춰 최적화하지 않았습니다. 두 방식 모두 방향과 MAE를 동시에 개선하지 못했습니다. 이 후속 설계는 전체 평가 결과를 본 뒤 진행했으므로 별도의 사전 등록 또는 블라인드 검증으로 표현하지 않습니다. 모든 실패 결과를 표와 코드에 포함했습니다.

날짜 블록 재표본추출로 계산한 MAE 개선의 95% 범위는 {ci.loc[chosen,'mae_gain_lo']:.3f}~{ci.loc[chosen,'mae_gain_hi']:.3f}%p입니다. 방향 일치율 개선 범위는 {ci.loc[chosen,'direction_gain_lo']*100:.2f}~{ci.loc[chosen,'direction_gain_hi']*100:.2f}%p입니다. 0을 포함하면 개선이 확실하다고 판단할 수 없습니다.

## 왜 이전 비교로는 변수 추가 효과를 판단할 수 없었는가

1. 초기 Gold는 변동성으로 나눈 수익률을 학습한 CatBoost였습니다. 후속 연구는 원래 수익률, LightGBM, Huber 손실, 다른 종목 선정이 함께 섞여 있었습니다. 이번에는 같은 CatBoost에서 정규화만 제거한 결과와 같은 입력의 LightGBM 결과를 따로 비교했습니다. LightGBM 비교는 알고리즘과 학습 손실이 함께 바뀐 패키지 비교입니다.
2. 기존 확장 학습표에는 초기 20종목 중 7종목이 없었습니다. 해당 종목의 공식 KRX 수급 98개 기간 요청을 완료하고, 보관된 DART 자료를 연결했습니다. 수급이 없는 날짜를 삭제하던 조건도 제거해 기존 표본을 유지했습니다. 결측값을 수급 0으로 바꾸지 않았습니다.
3. 시장 수급은 2009년 이전, 재무비율은 2016년 이전 학습 구간에 정보가 없습니다. 재무비율의 관측 비율은 2016~2022년 약 {avail.loc[avail.period=='2016-2022','debt_assets'].iloc[0]*100:.1f}%, 2023~2026년 약 {avail.loc[avail.period=='2023-2026','debt_assets'].iloc[0]*100:.1f}%입니다. 최근 데이터에 변수가 있다고 긴 학습 기간 전체에서도 학습할 수 있는 것은 아닙니다.
4. 추가 변수 전체가 유용하다는 가정은 하지 않았습니다. 수급, 가격과 거래대금, 동조화, 재무비율을 따로 학습해 어느 집단이 악화시키는지 분리했습니다. 원인 판단은 이 통제 비교의 범위이며, 각 변수의 독립적인 인과효과를 밝혔다는 뜻은 아닙니다.

이번 통제 비교에서도 전체 변수를 추가하면 학습 MAE 평균은 3.293에서 3.230%p로 낮아졌지만 평가 MAE는 4.583에서 4.640%p로 높아졌습니다. 학습 자료에서 좋아진 관계가 이후 기간에 그대로 유지되지 않는 패턴입니다. LightGBM도 학습 MAE는 2.960%p로 낮지만 평가 MAE는 4.629%p입니다. 모델이 학습 데이터를 더 잘 맞춘 것과 실제 평가 개선은 달랐습니다.

전체 변수 추가 시 상승으로 계산한 비율은 51.4%에서 41.5%로 줄었습니다. 실제 상승 비율은 52.9%였습니다. 급락 중심값 포착은 17건에서 41건으로 늘었지만, 급락 오경보도 20건에서 44건으로 늘었고 급등 MAE는 9.640에서 10.351%p로 악화했습니다. 급락 반응을 강화한 대신 반대 방향을 더 놓친 것이 이번 악화의 구체적인 모습입니다.

초기 저장 예측과 새로 재학습한 기준선의 최대 차이는 {audit.baseline_reproduction_max_error.dropna().max():.12g}%p입니다. 기준선 자체가 다른 문제는 배제했습니다.

급락 표본의 실제 평균 수익률은 {centers.loc['baseline','crash_actual_mean']:.2f}%입니다. 이 표본에서 초기 중심값 평균은 {centers.loc['baseline','crash_center_mean']:.2f}%, 사전 선정 방법은 {centers.loc[chosen,'crash_center_mean']:.2f}%입니다. 급락 중심값이 실제 손실에 얼마나 못 미치는지는 구간 폭과 별개로 이 값에서 확인할 수 있습니다. 상세한 중심값 분산과 급등 반응은 `center_diagnostics.csv`에 있습니다.

## 20종목별 비교

아래 개선 방법은 위에서 사전 선정한 동일 방법입니다. 평가를 보고 종목별로 유리한 모델을 고른 표가 아닙니다.

{table(pd.DataFrame(rows2),['asset','name','n','before','after','direction0','direction1'],['코드','종목','표본','기존 MAE','선정 MAE','기존 방향','선정 방향'])}

## 검증 범위

실제로 발생한 이후 5거래일 충격을 사후 입력한 조건부 재구성 평가입니다. 가상 충격의 정답이나 인과효과를 검증한 것은 아닙니다. 2023~2026년은 이미 여러 연구에서 사용했으므로 독립 블라인드 검증이 아닙니다. 원래 Gold의 공표 시각과 데이터 수정 이력도 완전히 확인되지 않아 운영 승인 근거로 단독 사용하지 않습니다.

확장 변수는 로컬 연구용입니다. 현재 20종목으로 계산한 동조화를 코스피 전체나 공식 업종 지표로 표현하지 않습니다. Azure, 운영 모델, Fabric Gold 계약은 변경하지 않았습니다. 포트폴리오 성능으로 종목별 성능을 대신하지 않았습니다.

가격과 거래대금 변수는 KRX 일봉의 고가와 저가 폭, 종가 위치, 시가 갭 변동성, 거래대금/시가총액 비율과 시가총액입니다. 분봉을 일봉 모델에 넣은 것이 아닙니다. 수급은 KRX, 재무비율은 DART 보관 원본을 별도로 읽었습니다. 이 추가 입력은 기존 Gold 테이블에 모두 들어 있는 컬럼이 아닙니다. 로컬에서 연결해 검증했으며, 서비스에 채택하려면 필요한 원천 필드의 전달 방식을 별도로 합의해야 합니다. 이번 작업에서 계약을 임의로 변경하지 않았습니다.

## 재현

`STRESSLAB_AUDIT_ROOT`를 원본 데이터가 있는 로컬 프로젝트 경로로 지정한 뒤 순서대로 실행합니다.

```powershell
python build_gold20_locked_20261104.py
python compare_gold20_locked_20261104.py
python select_gold20_by_stock_20261104.py
python blend_gold20_locked_20261104.py
python report_gold20_locked_20261104.py
python verify_gold20_locked_20261104.py
python export_gold20_locked_20261104.py
```

필요한 입력과 해시는 `protocol.json`, 비교 표본은 `locked_baseline.parquet`, 전체 계산값은 `predictions.parquet`, 종목별 지표는 `per_stock.csv`, 연도별 지표는 `per_year.csv`에 있습니다. `fit_audit.csv`는 학습 종료일, 표본 수, 결측 비율과 재현 오차를 기록합니다. `failure_examples.csv`는 사전 선정 방식에서 오차가 악화한 사례입니다. 원본 공급자 데이터와 인증정보는 저장소에 올리지 않습니다.
'''
    (OUT/'README.md').write_text(report,encoding='utf8')
    print(json.dumps(dict(chosen=chosen,baseline_mae=b.mae,selected_mae=s.mae,baseline_direction=b.direction,selected_direction=s.direction,improved_stocks=improvements),ensure_ascii=False))

if __name__=='__main__':main()
