import json
import numpy as np
import pandas as pd
from fresh_center_audit import OUT,SRC

def main():
    r=pd.read_parquet(OUT/'predictions.parquet');base=r[r.method.eq('old_stale')]
    dates=np.array(sorted(r.date.unique()));n=len(dates);rng=np.random.default_rng(20261103)
    draws=np.array([np.concatenate([(s+np.arange(10))%n for s in rng.integers(0,n,size=(n+9)//10)])[:n] for _ in range(2000)])
    ci=[]
    for name,z in r.groupby('method'):
        if name=='old_stale':continue
        x=z.merge(base,on=['asset','date'],suffixes=('_new','_old'),validate='one_to_one')
        for scope,q in [('all',x),('shock_events',x[x.event_old])]:
            for metric in ['mae','direction']:
                a=q[q.actual_old.ne(0)] if metric=='direction' else q
                delta=a.mae_new-a.mae_old if metric=='mae' else a.direction_correct_new.astype(float)-a.direction_correct_old.astype(float)
                num=delta.groupby(a.date).sum().reindex(dates,fill_value=0).to_numpy();den=a.groupby('date').size().reindex(dates,fill_value=0).to_numpy();ds=den[draws].sum(axis=1);s=num[draws].sum(axis=1)/np.maximum(ds,1);lo,hi=np.quantile(s[ds>0],[.025,.975]);ci.append(dict(method=name,scope=scope,metric=metric,n=len(a),delta=delta.mean(),ci_low=lo,ci_high=hi))
    pd.DataFrame(ci).to_csv(OUT/'paired_uncertainty.csv',index=False)
    metrics=pd.read_csv(OUT/'metrics.csv',dtype={'asset':str});s=metrics[(metrics.asset=='ALL')&(metrics.scope=='all')]
    names={'old_stale':'原設定（旧）','fresh_annual':'학습 공백 제거, 연간 갱신','fresh_quarter':'학습 공백 제거, 분기 갱신','clean_quarter':'분기 갱신 + WTI 정리','clean_recent8':'최근 8년 학습','clean_recent8_raw':'최근 8년 원수익률 학습','clean_recent8_state':'최근 8년 시장 상태만','clean_recent8_direction':'최근 8년 방향 분류'}
    names['old_stale']='기존 설정'
    lines=['# 학습 시점과 충격 정의 점검','',
    '방향 판단과 종목별 중심 수익률 개선만 검증했습니다. 스트레스 엔진, 확률구간, Azure, Gold는 변경하지 않았습니다. 새 6종목과 평가 표본 918개를 고정했습니다. 2023~2026년을 재사용한 개발 검증입니다.', '',
    '## 확인하고 수정한 부분','',
    '기존 학습은 직전 연도를 구간 보정용으로 남기면서 중심값 학습에서도 제외했습니다. 2026년 모델은 2024년 12월까지 학습했습니다. 확률구간 보정을 수행하지 않는 이번 중심값 비교에서는 이 1년 공백이 불필요하므로 제거했습니다. 학습 시점보다 정답 관측 종료가 20일 이상 앞선 자료만 사용했습니다.', '',
    '분기 갱신은 평가 중 이미 정답 관측이 끝난 과거 자료를 이후 분기의 학습에 포함합니다. 이 규칙은 실행 전에 고정했습니다. 현재 평가 대상의 미래 정답이나 평가 결과에 따른 파라미터 변경은 없습니다. 매년 또는 분기별로 동일한 규칙을 적용했습니다.', '',
    'WTI가 0 이하인 관측을 포함한 5거래일 구간은 일반적인 유가 변화율 해석에 적합하지 않아 학습에서 제외했습니다. 제외 전후를 따로 비교했고 평가 표본은 삭제하지 않았습니다. 최근 8년만 학습하는 방식, 원수익률 학습, 방향 분류도 고정 조건으로 비교했습니다.', '',
    '## 결과','',
    '| 방법 | 전체 방향 일치 | 전체 MAE | 큰 충격 방향 일치 | 큰 충격 MAE |','|---|---:|---:|---:|---:|']
    for _,a in s.iterrows():
        ev=metrics[(metrics.asset=='ALL')&(metrics.scope=='shock_events')&(metrics.method==a.method)].iloc[0]
        lines.append(f'| {names[a.method]} | {a.direction_accuracy:.1%} | {a.mae:.2f}%p | {ev.direction_accuracy:.1%} | {ev.mae:.2f}%p |')
    lines+=['','전체 방향 분모는 보합을 제외한 900개, 큰 충격 방향 분모는 227개입니다. 손익 오차는 보합을 포함한 각각 918개와 231개입니다. 큰 충격 집합은 이전 연구에서 학습 기간 기준으로 정의한 그대로 유지했습니다. 결과를 보고 재선정하지 않았습니다.','',
    '## 관측 시각 점검','',
    '미국 금리, WTI, VIX의 날짜가 한국 장 마감 때 이용 가능했다는 뜻은 아닙니다. 해당 자료를 이전 한국 거래일 관측으로 옮긴 뒤 시장 상태와 충격 양 끝을 다시 계산하는 별도 민감도 실험을 수행했습니다. 종목 정답과 평가 날짜는 같지만 조건으로 입력한 실제 충격의 관측 시각이 달라지므로 동일 입력의 모델 성능 비교와는 구분합니다.','']
    if (OUT/'timing_metrics.csv').exists():
        for _,a in pd.read_csv(OUT/'timing_metrics.csv').iterrows():lines.append(f'- {a.method}, {a.scope}: 방향 {a.direction_accuracy:.1%}, MAE {a.mae:.2f}%p, {a.n}개')
    lines+=['','실제 공표 시각과 데이터 개정 이력이 없으므로 하루 이동만으로 시점 정합성이 완전히 검증됐다고 주장하지 않습니다. 보수적인 가정에 대한 결과 민감도입니다. 이 문제를 성능이 좋은 쪽으로 선택해서 덮지 않습니다.','',
    '## 판단','',
    '학습 자료가 오래된 설정과 WTI 변화율 문제를 분리해 수정했으나 방향 80%는 달성하지 못했습니다. 최근 자료만 쓰거나 방향을 직접 학습하는 방식도 80%를 만들지 못했습니다. 단일 설정 오류만 고치면 목표가 충족된다는 근거는 없습니다.','',
    '구간 폭 확대, 평가 표본 삭제, 평가 성적을 보고 종목 교체는 하지 않았습니다. paired_uncertainty.csv에는 날짜 10개 블록, 2,000회 재표본추출한 개선 구간을 기록했습니다. 많은 개발 실험 중 하나이므로 작은 평균 개선만으로 정식 승인하지 않습니다.','',
    '확정할 수 있는 수정은 중심값 학습과 구간 보정을 분리하고 학습 가능 시점 경계를 명시하는 것, 비정상 유가 분모를 검사하는 것입니다. 미국 자료는 원천의 공표 및 관측 시각이 확인되어야 합니다. 현재 데이터에는 당시 업종 이력과 기업별 공시 입력도 없습니다. 그것들이 개선에 도움이 되는지는 추가 실험 대상이며 해결된 것으로 기록하지 않습니다.','',
    '이번 산출물은 방향 예측 서비스로 전환한 것이 아닙니다. 조건부 스트레스 모델이 실제 과거 충격에서 종목 반응을 충분히 설명하는지 평가한 것입니다. 조건부 재구성은 충격의 인과효과를 검증하지 않습니다.','',
    '## 재실행','',
    'scripts/fresh_center_audit.py, scripts/audit_macro_timing.py, scripts/report_fresh_center.py 순서로 실행합니다. 기존 reselection_20261103의 학습 표와 원본 연구 입력 및 예측 결과가 필요합니다. 원천 데이터와 인증정보는 저장소에 포함하지 않습니다.']
    (OUT/'결과.md').write_text('\n'.join(lines)+'\n',encoding='utf8')
if __name__=='__main__':main()
