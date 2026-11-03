"""Paired diagnostics on a frozen cohort, including negative results."""
import json
import numpy as np
import pandas as pd
from audit_center_training import OUT,SRC
from report_long_universe import metric

def main():
    assert json.loads((OUT/'progress.json').read_text())['status']=='complete'
    r=pd.read_parquet(OUT/'predictions.parquet');pairs=pd.read_csv(SRC/'eligible_pairs.csv',dtype={'asset':str})
    event=pd.Series(False,index=r.index)
    for _,p in pairs.iterrows():event |= r.asset.eq(p.asset)&r[p.shock+'_event']
    r['selected_event']=event
    months=pd.period_range(r.date.min(),r.date.max(),freq='M');n=len(months);rng=np.random.default_rng(20261103)
    draws=np.array([np.concatenate([(s+np.arange(3))%n for s in rng.integers(0,n,size=(n+2)//3)])[:n] for _ in range(2000)])
    base=r[r.method.eq('legacy_normalized')];uncertainty=[];paired=[]
    comparisons=[('legacy_normalized',m) for m in r.method.unique() if m!='legacy_normalized']+ [('clean_raw','selected_shocks_raw'),('clean_raw','prior_us_state_raw'),('state_raw','clean_raw')]
    for reference,method in comparisons:
        a=r[r.method.eq(method)];b=r[r.method.eq(reference)]
        z=a.merge(b,on=['asset','date'],suffixes=('_new','_base'),validate='one_to_one')
        assert len(z)==len(base) and np.allclose(z.actual_new,z.actual_base)
        for scope,q in [('all',z),('selected_shock_events',z[z.selected_event_new])]:
            for measure in ['mae_change','direction_gain']:
                h=q if measure=='mae_change' else q[q.actual_new.ne(0)]
                delta=(h.center_new-h.actual_new).abs()-(h.center_base-h.actual_base).abs() if measure=='mae_change' else (np.sign(h.center_new)==np.sign(h.actual_new)).astype(int)-(np.sign(h.center_base)==np.sign(h.actual_base)).astype(int)
                key=h.date.dt.to_period('M');num=delta.groupby(key).sum().reindex(months,fill_value=0).to_numpy();den=h.groupby(key).size().reindex(months,fill_value=0).to_numpy();ds=den[draws].sum(axis=1);v=num[draws].sum(axis=1)/np.maximum(ds,1);lo,hi=np.quantile(v[ds>0],[.025,.975])
                uncertainty.append(dict(reference=reference,method=method,scope=scope,metric=measure,n=len(h),change=delta.mean(),ci_low=lo,ci_high=hi))
        for asset,q in z.groupby('asset'):
            nz=q[q.actual_new.ne(0)]
            paired.append(dict(asset=asset,reference=reference,method=method,n=len(q),mae_change=float(((q.center_new-q.actual_new).abs()-(q.center_base-q.actual_base).abs()).mean()),direction_gain=float(((np.sign(nz.center_new)==np.sign(nz.actual_new)).astype(int)-(np.sign(nz.center_base)==np.sign(nz.actual_base)).astype(int)).mean())))
    pd.DataFrame(uncertainty).to_csv(OUT/'paired_uncertainty.csv',index=False);pd.DataFrame(paired).to_csv(OUT/'paired_asset_changes.csv',index=False)
    rows=[];dispersion=[]
    for (year,method),z in r.groupby([r.date.dt.year,'method']):rows.append(dict(year=year,method=method,**metric(z)))
    for method,z in r.groupby('method'):
        cr=z[z.actual<=-5];ra=z[z.actual>=5]
        dispersion.append(dict(method=method,center_std=z.center.std(),actual_std=z.actual.std(),center_actual_corr=z.center.corr(z.actual),crash_actual_mean=cr.actual.mean(),crash_center_mean=cr.center.mean(),rally_actual_mean=ra.actual.mean(),rally_center_mean=ra.center.mean(),observed_positive_fraction=z[z.actual.ne(0)].actual.gt(0).mean()))
    pd.DataFrame(rows).to_csv(OUT/'year_metrics.csv',index=False);pd.DataFrame(dispersion).to_csv(OUT/'center_compression.csv',index=False)
    metrics=pd.read_csv(OUT/'metrics.csv');allm=metrics[metrics.scope.eq('all')];ev=metrics[metrics.scope.eq('selected_shock_events')]
    excluded=pd.read_csv(OUT/'excluded_evaluation_rows.csv')
    lines=['# 종목별 중심 수익률과 학습 과정 점검','',f'기존 101종목을 고정했습니다. 과거 61거래일 입력 품질 문제로 기존 평가 {len(excluded)+len(base):,}개 중 {len(excluded):,}개를 공통 평가에서 제외했습니다. 실제 수익률이 크거나 틀렸다는 이유로 제외하지 않았습니다. 모든 방법은 남은 {len(base):,}개에서 비교했습니다.','',
    '## 확인한 문제','',
    '1. 기존 코드는 정답 구간의 가격 품질을 검사했지만 과거 추세와 변동성 입력 구간의 격리 값을 그대로 사용할 수 있었습니다. 과거 61거래일 품질 조건을 별도로 적용했습니다.','2. 수익률을 사전 변동성으로 나눈 뒤 같은 가중치로 학습하면 원래 수익률 기준으로 저변동성 관측의 오차가 상대적으로 크게 반영됩니다. 정규화 제거와 가중치 보정을 각각 비교했습니다.','3. 선정은 충격별 방향 분류로 했으나 최종 모델은 네 충격의 수익률 회귀입니다. 선정된 충격만 사용하는 회귀와 분류를 비교했습니다. 분류 모델의 대표 수익률은 상승 또는 하락 학습 표본의 중앙값이므로 수익률 회귀와 구분해야 합니다.','4. 공표 시각 필드는 전부 비어 있습니다. 미국 금리, WTI, VIX의 상태 입력을 이전 KRX 거래일 값으로 바꾼 민감도 실험을 추가했습니다. 실제 충격과 종목 정답은 유지했습니다. 이 실험도 정확한 공표 시각 검증을 대체하지 않습니다.','',
    '## 동일 표본 결과','', '| 방법 | 방향 일치율 | 중심 MAE | 고정 5%p 진단 포함률 |','|---|---:|---:|---:|']
    for _,v in allm.iterrows():lines.append(f'| {v.method} | {v.direction_accuracy:.2%} | {v.mae:.3f}%p | {v.fixed5_coverage:.2%} |')
    lines+=['','## 선정 충격이 큰 구간','', '| 방법 | 방향 일치율 | 중심 MAE |','|---|---:|---:|']
    for _,v in ev.iterrows():lines.append(f'| {v.method} | {v.direction_accuracy:.2%} | {v.mae:.3f}%p |')
    lines+=['','audit_center_inputs.py는 5거래일 정답과 충격 구간을 재계산하고, 2008년, 2020년, 2025년의 세 시점에서 미래 행을 제거해도 현재 상태가 동일한지 검사합니다. 결과는 shock_window_audit.csv와 feature_prefix_audit.json에 있습니다.','',
    '급등과 급락은 실제 5일 수익률 +5%, -5% 경계로 구분했습니다. metrics.csv의 crash/rally 범위와 center_compression.csv에서 실제 움직임 대비 중심값 크기를 확인할 수 있습니다. paired_uncertainty.csv는 같은 달의 종목을 함께 재표본추출한 3개월 블록 구간이며 여러 방법 비교에 대한 다중검정 보정은 하지 않았습니다. 탐색 결과입니다.','',
    '이 평가는 과거 실제 충격을 사후 입력한 반응 재구성입니다. 인과효과나 충격 발생 예측이 아닙니다. 평가 기간은 기존 연구에서 사용한 2023~2026년으로 독립 블라인드가 아닙니다. 표본 선정의 다중 비교와 생존 편향, 수정주가의 당시 버전, 실제 공표 시각까지 모두 검증됐다는 뜻이 아닙니다.','',
    '코드 수정과 성능 승인은 별개입니다. 기존 학습표와 결과를 보존했고 Azure, 운영 모델, Gold 계약은 변경하지 않았습니다. 폭을 넓히지 않았으며 고정 5%p 포함률은 진단값이지 승인된 확률 구간이 아닙니다.']
    capacity=pd.read_csv(OUT/'capacity_summary.csv')
    lines+=['','## 학습 자료에만 맞는지 확인','', '같은 101종목에서 2021년 이전 학습과 2022년 후속 검증을 나눴습니다. 아래 값은 종목별 지표의 평균입니다. 위 표의 2023~2026년 전체 관측 통계와 섞어 비교하지 않습니다.','', '| 모델 | 구간 | 방향 일치율 | 중심 MAE |','|---|---|---:|---:|']
    for _,v in capacity.iterrows():lines.append(f'| {v.model} | {v.scope} | {v.direction_accuracy:.2%} | {v.mae:.3f}%p |')
    lines+=['','## 판단','',
    '가격 입력 품질 점검은 필요하지만 이번 성능 부진의 주원인으로 확인되지는 않았습니다. 정답 계산과 네 충격의 5거래일 계산은 원본 값으로 재계산했을 때 일치했습니다. 미래 행을 제거한 세 시점의 시장 상태도 동일했습니다. 실제 공표 시각은 미확인 상태로 남습니다.','',
    '정규화 제거는 전체 중심 오차를 약 0.04%p 줄였으나 방향 일치율과 급락 규모 포착을 함께 개선하지 못했습니다. 선정된 충격만 넣는 방식도 네 충격 전체보다 낫지 않았습니다. 따라서 이 변경들을 서비스 성능 문제의 해결책으로 승인하지 않았습니다.','',
    '충격 변수의 정보는 있습니다. 동일한 원수익률 학습에서 시장 상태만 사용하는 경우보다 충격을 추가하면 전체 방향 일치율이 약 5.6%p, 선정 충격 구간에서 약 8.7%p 높아집니다. 반면 방향 80%에는 크게 못 미칩니다.','',
    '모델 복잡도를 높이면 학습 자료에는 훨씬 잘 맞지만 다음 해의 방향 일치율과 오차가 악화됐습니다. 단순히 나무 수를 늘리거나 학습 반복을 늘리는 방법은 채택하지 않습니다. 현재 피처와 모델이 이후 기간까지 유지되는 종목 반응을 충분히 설명하지 못하는 일반화 문제가 남았습니다. 이 실험만으로 설명 불가능한 본질적 한계라고 단정하지는 않습니다.','',
    '다음 성능 연구의 판단 기준은 종목 수나 학습 점수가 아니라 새로운 기간에서도 유지되는 조건별 설명력입니다. 현재 101종목은 고정한 연구 후보이며 모두 서비스 지원 종목으로 승인된 것이 아닙니다. 이번 평가에서 잘 나온 종목을 다시 골라 같은 평가로 성능을 주장하지 않습니다.']
    (OUT/'README.md').write_text('\n'.join(lines)+'\n',encoding='utf8')

if __name__=='__main__':main()
