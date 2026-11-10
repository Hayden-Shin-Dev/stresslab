"""Recompute paired checks and publish a center-only failure audit."""
import json
import hashlib
import numpy as np
import pandas as pd
from crash_cases_center_20261104 import OUT, ROOT, COLS, DOM, STATE, EXTRA, SHOCKS, inputs, metrics

def main():
    r=pd.read_parquet(OUT/'predictions.parquet')
    baseline=r[(r.model=='catboost') & (r.policy=='baseline')].sort_values(['asset','date'])
    assert len(baseline)==2928 and baseline.asset.nunique()==20
    prior=pd.read_parquet(ROOT/'reports/shared_improvement_20261104/predictions.parquet')
    for (model,policy),z in r.groupby(['model','policy']):
        z=z.sort_values(['asset','date'])
        assert z[['asset','date','actual']].reset_index(drop=True).equals(baseline[['asset','date','actual']].reset_index(drop=True))
        if policy=='baseline':
            p=prior[(prior.model==model)&(prior.policy=='refresh')].sort_values(['asset','date'])
            np.testing.assert_array_equal(z.center,p.center)
    for filename in ['fit_audit.csv','tail_fit_audit.csv']:
        a=pd.read_csv(OUT/filename)
        assert (pd.to_datetime(a.train_label_end)<pd.to_datetime(a.test_start)).all()
    assert not any(c in r for c in ['lo','hi','lower','upper'])
    assert 'diagnostic_only_future_market5' not in COLS
    recorded=pd.read_csv(OUT/'metrics.csv')
    for (model,policy),z in r.groupby(['model','policy']):
        expected=recorded[(recorded.model==model)&(recorded.policy==policy)].iloc[0]
        for key,value in metrics(z).items():
            np.testing.assert_allclose(value,expected[key],rtol=1e-10)
    d=inputs();cases=pd.read_csv(OUT/'worst_crash_by_stock.csv',dtype={'asset':str},parse_dates=['date'])
    neighbors=[]
    for _,c in cases.iterrows():
        tr=d[(d.asset==c.asset)&(d.end_date<pd.Timestamp(int(c.fold),1,1)-pd.Timedelta(days=20))&d.oil_valid].sort_values('date').iloc[::6]
        cols=STATE+EXTRA+DOM;med=tr[cols].median();scale=(tr[cols].quantile(.75)-tr[cols].quantile(.25)).replace(0,1)
        dist=((tr[cols].fillna(med)-c[cols].astype(float).fillna(med))/scale).pow(2).mean(axis=1)
        pool=tr.loc[dist.nsmallest(100).index].copy();ss=(tr[SHOCKS].quantile(.75)-tr[SHOCKS].quantile(.25)).replace(0,1)
        pool['distance']=((pool[SHOCKS]-c[SHOCKS].astype(float))/ss).pow(2).mean(axis=1)
        n=pool.nsmallest(20,'distance')
        neighbors.append(dict(asset=c.asset,date=c.date,crash_fraction=float((n.target<=-5).mean()),median=float(n.target.median()),mean=float(n.target.mean()),current_market5=c.market_return5,neighbor_market5=float(n.market_return5.median())))
    pd.DataFrame(neighbors).to_csv(OUT/'domestic_neighbor_diagnostic.csv',index=False)
    pivot=r[r.model=='catboost'].pivot(index=['asset','date'],columns='policy',values='center').reset_index()
    detail=cases[['asset','date','actual','start_close','end_close','market_return5','shock_fx','shock_rate','shock_oil','shock_vix','diagnostic_only_future_market5']].merge(pivot,on=['asset','date'],validate='one_to_one')
    assert len(detail)==20
    detail.to_csv(OUT/'case_center_comparison.csv',index=False)
    # Paired calendar-month block bootstrap, not independent stock observations.
    rng=np.random.default_rng(20261104);ci=[]
    for model in r.model.unique():
        z=r[r.model==model];b=z[z.policy=='baseline'][['asset','date','actual','center']]
        for policy in ['domestic','domestic_mean','tail_weighted']:
            q=z[z.policy==policy].merge(b,on=['asset','date','actual'],suffixes=('','_b'),validate='one_to_one')
            q['gain']=abs(q.center_b-q.actual)-abs(q.center-q.actual)
            q['month']=q.date.dt.to_period('M').astype(str)
            for subset,mask in [('all',q.actual.notna()),('crash',q.actual<=-5)]:
                groups=q[mask].groupby('month').gain.agg(['sum','count'])
                idx=rng.integers(0,len(groups),size=(2000,len(groups)))
                vals=groups['sum'].to_numpy()[idx].sum(1)/groups['count'].to_numpy()[idx].sum(1)
                ci.append(dict(model=model,policy=policy,subset=subset,gain_pp=q.loc[mask,'gain'].mean(),low95=np.quantile(vals,.025),high95=np.quantile(vals,.975),calendar_blocks=len(groups)))
    pd.DataFrame(ci).to_csv(OUT/'paired_mae_uncertainty.csv',index=False)
    gold=ROOT/'exports/seongjin_gold_v1_1/gold_stress_daily.parquet'
    verification=dict(passed=True,models=4,policies=4,stocks=20,paired_rows_per_model_policy=2928,dates=baseline.date.nunique(),start=str(baseline.date.min()),end=str(baseline.date.max()),crash_rows=int((baseline.actual<=-5).sum()),crash_start_dates=baseline.loc[baseline.actual<=-5,'date'].nunique(),baseline_matches_previous_refresh=True,label_end_before_evaluation=True,future_market_excluded=True,intervals_changed=False,gold_sha256=hashlib.sha256(gold.read_bytes()).hexdigest(),gold_contract_changed=False,azure_changed=False,independent_blind_test=False)
    (OUT/'verification.json').write_text(json.dumps(verification,indent=2),encoding='utf8')
    lines=['# 급락 중심값 실패 분석','', '20종목의 동일한 2,928개 종목별 평가값을 비교했습니다. 평가 기간은 2023-01-02~2026-10-19입니다. 5거래일 수익률이 -5% 이하인 390개 표본을 급락으로 정의했습니다. 시작 날짜는 105개이며 기간이 겹치므로 독립 사건 105개라는 뜻은 아닙니다.','',
    '## 결론','', '이번 세 가지 수정으로 중심값 개선을 입증하지 못했습니다. 국내 단기 상태 보완, 평균 학습, 급등락 표본 가중치를 네 모델에 동일하게 적용했지만 모두 급락 MAE가 기존보다 커졌습니다. 구간을 넓히거나 운영 모델을 변경하지 않았습니다.','',
    '## 실제 실패 사례','', '| 종목 코드 | 날짜 | 실제 수익률 | 기존 중심값 | 국내 상태 추가 | 급등락 가중 |','|---|---|---:|---:|---:|---:|']
    for _,c in detail.iterrows():lines.append(f'| {c.asset} | {c.date:%Y-%m-%d} | {c.actual:.2f}% | {c.baseline:.2f}% | {c.domestic:.2f}% | {c.tail_weighted:.2f}% |')
    lines += ['', '종목별 가장 큰 과소평가 사례입니다. CatBoost 결과이며 전체 네 모델의 종목별 결과는 per_stock.csv에 있습니다. 시작 가격, 종료 가격, 네 충격과 국내 시장 변화는 case_center_comparison.csv에 있습니다.','',
    '## 무엇을 놓쳤는지','',
    '1. 동시 급락: 2026-07-01 시작 구간은 삼성전기 실제 -32.93%, 기존 중심 +3.63%였습니다. 같은 5일 코스피는 -12.73%인데 환율은 -2.22%, VIX는 -0.32포인트였습니다. 해외 위험 지표의 방향만으로 국내 급락을 설명하기 어려운 사례입니다. 미래 코스피 수익률은 원인 진단에만 사용했고 입력에 넣지 않았습니다.',
    '2. 검색의 상태 차이: 해당 사례의 과거 후보 20개 중 급락은 4개였고 중앙값은 +0.26%였습니다. 당시 국내 시장의 직전 5일은 -1.98%였지만 후보의 직전 5일 중앙값은 +2.65%였습니다. 단기 흐름을 추가해 검색하면 후보 수익률 중앙값은 -0.61%로 바뀌지만 실제 -32.93%와는 여전히 멉니다. 가장 가까운 후보라는 이유만으로 충분한 근거라고 볼 수 없습니다.',
    '3. 중심값 학습: 극단 반응이 같은 입력 조건에서 드물면 중앙값은 그 반응을 따라가지 않습니다. 그렇지만 평균 학습으로 바꿔도 급락 오차는 더 커졌으므로 중앙값 목적함수 하나가 원인이라는 설명도 맞지 않습니다.',
    '4. 급락 강화의 대가: CatBoost에서 급락 중심값 포착은 9건에서 15건으로 늘었지만 오경보도 5건에서 11건으로 늘었습니다. 실제 급락 평균 -8.49%에 비해 중심값 평균은 -0.66%에서 -0.63%가 되어 개선되지 않았습니다.',
    '5. 개별 종목 요인: 시장이 상승한 구간에도 개별 종목 급락이 있습니다. 이 자료만으로 공시, 수급, 뉴스 중 무엇이 원인인지 확인하지 않았습니다. 독립적인 인과효과를 밝혔다는 뜻이 아닙니다.','',
    '## 동일 조건 결과','', '| 모델 | 방식 | 중심 MAE(%p) | 방향 일치율 | 급락 MAE(%p) | 급락 포착/390 | 오경보 |','|---|---|---:|---:|---:|---:|---:|']
    labels={'baseline':'기존','domestic':'국내 상태 추가','domestic_mean':'국내 상태 + 평균','tail_weighted':'국내 상태 + 급등락 가중'}
    for _,x in recorded.iterrows():lines.append(f'| {x.model} | {labels[x.policy]} | {x.mae:.3f} | {x.direction:.2%} | {x.crash_mae:.3f} | {int(x.crash_caught)} | {int(x.false_crash)} |')
    lines += ['', '방향 일치율은 실제 수익률이 0인 표본을 제외합니다. 급락 포착은 실제와 중심값이 모두 -5% 이하인 경우입니다. 이 값은 손실 구간 포함률과 다릅니다.','',
    '## 변경 및 검증 방법','',
    'Gold 34개 원본 컬럼은 유지했습니다. 기존 파생 입력 18개에 국내 1일/5일 흐름, 고점 대비 하락, 하방 변동성, 상대수익률 등을 계산해 36개 파생 입력으로 실험했습니다. 하락 비율은 관측한 보통주 19개 기준이며 코스피 전체 지표가 아닙니다.',
    '학습 정답 종료일은 평가 연도 시작 20일 전보다 이릅니다. 결측값 대체와 급등락 가중치 기준은 학습 데이터에서만 계산했습니다. 급등과 급락에 같은 가중치를 주며 손실 방향을 강제하지 않았습니다. 가중 학습 중심값을 일반적인 조건부 중앙값으로 해석하면 안 됩니다.',
    '2020~2021년 개발 구간에서 급락 MAE 5% 이상 개선, 전체 MAE와 방향 유지, 오경보 최대 2건 증가 조건을 적용했습니다. 네 모델 모두 기존 방식이 남았습니다. 실패 사례를 보고 설계했고 평가 구간도 이전 연구에서 사용했으므로 독립 블라인드 검증이 아닙니다.',
    '실제 발생한 미래 5거래일 충격을 사후 입력한 조건부 재구성 평가입니다. 임의의 가상 충격에 대한 정답 검증이나 인과효과 검증은 아닙니다. Gold의 공표 시각 누락과 현재 종목 기준 생존 편향도 남아 있습니다. 수정주가 원본의 재수집 검증은 이번 작업 범위에 포함하지 않았습니다.',
    '일부 종목의 개선만 골라 채택하지 않았습니다. 현재 데이터로 급락 중심값 문제가 해결됐다고 판단할 수 없습니다. 확정적 위험 추정치로 승격하지 않고 기존 비교 모델을 보존합니다.','',
    '## 재현','', '기존 연구 작업 폴더에서 scripts/crash_cases_center_20261104.py, scripts/crash_tail_weighted_20261104.py, scripts/report_crash_cases_center_20261104.py 순서로 실행합니다. Gold와 이전 shared_improvement_20261104, four_models_gold_20261104 결과가 필요합니다. 저장소 결과 폴더만으로 원천 데이터를 복원할 수는 없습니다.',
    '검증 결과는 verification.json, 전체 예측은 predictions.parquet, 월 단위 재표본추출 결과는 paired_mae_uncertainty.csv에 있습니다. 검증 통과는 계산 일치 확인이며 모델 성능 승인과 다릅니다.']
    (OUT/'README.md').write_text('\n'.join(lines)+'\n',encoding='utf8')
    print(json.dumps(verification))

if __name__=='__main__':main()
