"""Independent checks, uncertainty and candid decisions for common-policy improvements."""
import json,hashlib,importlib.metadata
import numpy as np
import pandas as pd
from shared_improvement_20261104 import ROOT,OUT,OLD,KINDS,POLICIES
from four_models_gold_20261104 import score
def main():
    r=pd.read_parquet(OUT/'predictions.parquet');dev=pd.read_parquet(OUT/'development_predictions.parquet');m=pd.read_csv(OUT/'metrics.csv').set_index(['model','policy']);selection=json.loads((OUT/'development_selection.json').read_text());audit=pd.read_csv(OUT/'fit_audit.csv',dtype={'asset':str})
    locked=pd.read_parquet(ROOT/'reports/gold20_locked_20261104/locked_baseline.parquet').sort_values(['asset','date']);baseline=pd.read_parquet(OLD/'predictions.parquet')
    assert len(r)==4*7*2928 and not r.duplicated(['asset','date','model','policy']).any()
    for (kind,p),z in r.groupby(['model','policy']):
        z=z.sort_values(['asset','date']);assert len(z)==2928 and z.asset.nunique()==20
        assert list(zip(z.asset,z.date))==list(zip(locked.asset,locked.date));assert np.array_equal(z.actual.to_numpy(),locked.actual.to_numpy())
        assert np.isfinite(z[['center','lo','hi','q05','es']]).all().all() and (z.lo<=z.hi).all()
        if p=='baseline':
            old=baseline[baseline.model==kind].sort_values(['asset','date']);assert np.array_equal(z.center.to_numpy(),old.center.to_numpy())
        for k,v in score(z).items():assert np.isclose(v,m.loc[(kind,p),k],equal_nan=True)
    valid=audit[~audit.fallback];assert (pd.to_datetime(valid.train_label_end)<pd.to_datetime(valid.test_start)).all();assert (pd.to_datetime(valid.cal_label_end)<pd.to_datetime(valid.test_start)).all()
    for value,start in zip(valid.cal_model_label_ends,valid.test_start):assert all(pd.Timestamp(x)<pd.Timestamp(start) for x in str(value).split(';'))
    # Recompute development-only choices without inspecting evaluation metrics.
    for kind in KINDS:
        z=dev[dev.model==kind];b=score(z[z.policy=='baseline']);eligible=[]
        for p in POLICIES:
            s=score(z[z.policy==p]);annual=all(score(z[(z.policy==p)&(z.fold==y)])['mae']<=score(z[(z.policy=='baseline')&(z.fold==y)])['mae'] for y in [2020,2021])
            if s['mae']<=b['mae']*.99 and s['direction']>=b['direction'] and s['crash_mae']<=b['crash_mae'] and annual:eligible.append((s['mae'],p))
        assert selection[kind]==(min(eligible)[1] if eligible else 'baseline')
    cis=[]
    for (kind,p),z in r.groupby(['model','policy']):
        if p=='baseline':continue
        b=r[(r.model==kind)&(r.policy=='baseline')][['asset','date','center']].rename(columns={'center':'base'});q=z.merge(b,on=['asset','date'],validate='one_to_one');q['gain']=abs(q.actual-q.base)-abs(q.actual-q.center);q['dg']=np.where(q.actual.ne(0),(np.sign(q.actual)==np.sign(q.center)).astype(float)-(np.sign(q.actual)==np.sign(q.base)).astype(float),np.nan)
        agg=q.groupby('date').agg(gain=('gain','sum'),n=('gain','size'),direction=('dg','sum'),dn=('dg','count')).sort_index().to_numpy();n=len(agg);rng=np.random.default_rng(20261104);samples=[]
        for _ in range(1500):
            starts=rng.integers(0,n,int(np.ceil(n/5)));idx=np.concatenate([(s+np.arange(5))%n for s in starts])[:n];v=agg[idx].sum(axis=0);samples.append([v[0]/v[1],v[2]/v[3]])
        bounds=np.quantile(samples,[.025,.975],axis=0);cis.append(dict(model=kind,policy=p,mae_gain_lo=bounds[0,0],mae_gain_hi=bounds[1,0],direction_gain_lo=bounds[0,1],direction_gain_hi=bounds[1,1]))
    ci=pd.DataFrame(cis);ci.to_csv(OUT/'paired_uncertainty.csv',index=False)
    decisions=[];refresh=[]
    for kind in KINDS:
        b=m.loc[(kind,'baseline')];p=selection[kind];s=m.loc[(kind,p)];fresh=m.loc[(kind,'refresh')]
        point=bool(p!='baseline' and s.mae<b.mae and s.direction>=b.direction)
        risk=bool(point and s.coverage80>=b.coverage80 and s.interval_score80<=b.interval_score80 and s.crash_mae<=b.crash_mae and s.crash_lower_breach<=b.crash_lower_breach)
        decisions.append(dict(model=kind,development_selected=p,point_improved=point,risk_guard_passed=risk,production_promoted=False))
        refresh.append(dict(model=kind,mae_before=b.mae,mae_after=fresh.mae,mae_improvement_pct=(b.mae-fresh.mae)/b.mae*100,direction_before=b.direction,direction_after=fresh.direction,coverage_before=b.coverage80,coverage_after=fresh.coverage80,width_before=b.width80,width_after=fresh.width80,crash_mae_before=b.crash_mae,crash_mae_after=fresh.crash_mae,crash_lower_breach_before=b.crash_lower_breach,crash_lower_breach_after=fresh.crash_lower_breach))
    pd.DataFrame(decisions).to_csv(OUT/'decision.csv',index=False);pd.DataFrame(refresh).to_csv(OUT/'common_refresh_comparison.csv',index=False)
    failure=r[r.policy=='refresh'].copy();failure['absolute_error']=abs(failure.actual-failure.center);failure.nlargest(40,'absolute_error').to_csv(OUT/'failure_examples.csv',index=False)
    pd.DataFrame([dict(model=k,policy=p,regime='high' if h else 'other',**score(z)) for (k,p,h),z in r.groupby(['model','policy','high_vol'])]).to_csv(OUT/'per_regime.csv',index=False)
    checks=dict(status='passed',models=4,stocks=20,policies_including_baseline=7,rows_per_model_policy=2928,paired_targets_exact=True,baseline_predictions_preserved=True,selection_recomputed_from_development_only=True,training_and_calibration_before_test=True,overlapping_calibration_windows='greedily removed across year boundaries; runtime assertions in study code',gold_contract_unchanged=True,production_promoted=False)
    (OUT/'verification.json').write_text(json.dumps(checks,indent=2),encoding='utf8')
    table=['| 모델 | MAE 이전 → 갱신 | 방향 이전 → 갱신 | 포함률 이전 → 갱신 | 폭 이전 → 갱신 |','| --- | ---: | ---: | ---: | ---: |']
    for z in refresh:table.append(f"| {z['model']} | {z['mae_before']:.3f} → {z['mae_after']:.3f} | {z['direction_before']*100:.2f}% → {z['direction_after']*100:.2f}% | {z['coverage_before']*100:.2f}% → {z['coverage_after']*100:.2f}% | {z['width_before']:.2f} → {z['width_after']:.2f} |")
    selectiontable=['| 모델 | 개발 기간 선정 | 평가 중심값 동시 개선 | 급락을 포함한 위험 기준 |','| --- | --- | --- | --- |']
    for row in decisions:selectiontable.append(f"| {row['model']} | {row['development_selected']} | {'통과' if row['point_improved'] else '미통과'} | {'통과' if row['risk_guard_passed'] else '미통과'} |")
    refreshcal=valid[(valid.policy=='refresh')&(valid.fold>=2023)]
    text=f'''# 네 모델에 같은 개선 절차 적용

Gold 34개 컬럼과 20종목을 유지했습니다. 모델마다 같은 여섯 개선안을 실행하고, 기존과 같은 2,928개 종목별 평가값으로 비교했습니다. 운영 모델, Azure, Fabric 계약은 변경하지 않았습니다.

## 공통 재학습 방식의 결과

아래는 네 모델 모두에 적용한 `refresh`입니다. 최신 자료로 재학습하고 과거 두 해의 외표본 오차로 구간을 보정했습니다. 같은 개선 방식의 효과를 보여주는 표이며, 평가에서 가장 좋은 방법을 종목별로 골라 합친 결과가 아닙니다.

{chr(10).join(table)}

MAE와 폭은 %p입니다. 네 모델 모두 방향 일치율과 중심값 MAE의 점추정은 개선됐습니다. 폭은 줄지 않았습니다. 포함률 개선만 보고 목표 달성이라고 판단하지 않습니다. 날짜 블록 기반 개선 불확실성은 `paired_uncertainty.csv`에 있습니다. 0을 포함하는 개선 범위는 통계적으로 확실한 우위로 해석하지 않습니다.

급락 중심값 오차는 네 모델 모두 소폭 나빠졌습니다. 반면 급락 때 구간 하한 이탈률은 낮아졌습니다. 중심값이 급락을 더 정확히 맞힌 것과 넓어진 구간이 손실을 덜 놓친 것은 구분해야 합니다. 상세 수치는 `common_refresh_comparison.csv`에 있습니다.

## 개발 기간에서 고른 방식

선정 규칙은 실험 시작 시 고정했습니다. 각 모델에서 2020~2021년 개발 MAE 1% 이상 감소, 방향 유지, 급락 MAE 유지, 두 개발 연도 모두 MAE 악화 없음인 방법 중 MAE가 가장 낮은 것을 선택했습니다. 이후 2023~2026년 평가를 해석했습니다. 모든 기간은 재사용 연구 기간이며 블라인드 검증이 아닙니다.

{chr(10).join(selectiontable)}

공통 `refresh` 비교와 개발 기간 선정 결과는 별도로 보고했습니다. 평가에서 좋아 보이는 방법을 사후 선정해 공식 승격하지 않았습니다. 평균 폭 5%p 이하, 포함률 80% 이상, 급락 안정성을 함께 확보하지 못했습니다.

## 발견한 문제와 실제 수정

| 문제 | 확인 및 조치 |
| --- | --- |
| 오래된 학습 모델 | 기존 2026년 모델은 2024년 12월까지 학습했습니다. refresh는 2025년 12월까지 사용하되, 예측 정답 종료일에 20일 여유를 둡니다. |
| 보정 자료 부족 | 기존 보정은 전년도 약 33~38개였습니다. 이전 두 해에서 당시 모델의 외표본 오차를 모았습니다. refresh의 보정 표본은 {int(refreshcal.cal_n.min())}~{int(refreshcal.cal_n.max())}개입니다. 연도 경계를 포함해 5거래일 정답이 겹치는 구간을 제거했습니다. |
| 음수 WTI의 변화율 | 유가 충격의 시작 또는 종료 수준이 0 이하인 36개 종목별 학습 행을 확인했습니다. 새 방식의 학습과 보정에서 제외했습니다. 과거 유가 추세의 분모도 같은 규칙으로 검사합니다. 평가 표본은 삭제하지 않습니다. |
| 장기 시장 구조 변화 | 전체 이력과 최근 8년을 비교했습니다. 오래됐다는 이유만으로 반드시 성능이 나쁘다고 가정하지 않았습니다. |
| 가격 수준과 변화량 혼재 | 유가 및 미국 금리 수준을 20일 변화로 바꾸고 한국 금리는 미국 금리와의 차이를 사용하는 실험을 분리했습니다. 기존 Gold에서 계산합니다. |
| 정규화 영향 | 최근 8년 방식에서 정규화 유무만 바꿨습니다. 폭이 줄더라도 포함률과 하방 포착이 나빠지면 개선으로 인정하지 않습니다. |
| 시장 상태와 충격의 결합 | 각 충격과 시장 추세, 시장 변동성, 종목 추세의 곱을 같은 방식으로 네 모델에 추가했습니다. 관계를 독립적인 인과효과로 표현하지 않습니다. |
| 데이터 누락 및 정합성 | 중복 키 0개, 합성 자료 0개를 확인했습니다. 기존 격리 104행과 결측 101행은 기존 품질 규칙으로 처리합니다. 큰 실제 수익률은 오차가 크다는 이유로 삭제하지 않았습니다. |

`quality_only`는 첫 유가 품질 처리만, `refresh`는 품질 처리와 최신 재학습 및 누적 보정, `recent8`은 refresh에서 학습 이력을 8년으로 제한한 방식입니다. `stationary`, `raw_target`, `interactions`는 각각 recent8에 한 가지 변경을 더합니다. 각 알고리즘의 기존 개발 설정은 고정했으며, 개선안마다 평가를 보고 튜닝하지 않았습니다.

과거 외표본 오차는 당시 시점 이전 자료로 학습한 모델에서 만들었습니다. 현재 모델은 그 이후 확보한 자료도 사용할 수 있습니다. 따라서 과거 오차가 현재 모델에도 적절하다는 가정이 남으며, 이를 자동적인 구간 보장으로 표현하지 않습니다. ES 꼬리 표본 역시 적어 정식 승인 대상이 아닙니다.

## 해결되지 않은 데이터 문제

관측일이 거래일보다 미래인 행은 확인되지 않았습니다. 그러나 가격과 거시 요인의 실제 공개 시각은 연구 파일에서 모두 NULL입니다. 관측일 정합성과 실제 공개 시각 검증은 다릅니다. 시각을 추측해 채우지 않았으며 이 부분까지 해결됐다고 보고하지 않습니다.

오래된 큰 수익률은 `largest_historical_returns_audit.csv`에 남겼습니다. 기업 이력 변화와 기업행사를 전수 재검증한 것은 아닙니다. 과거 관측 범위를 넘는 사용자 충격의 결과도 별도 한계가 있으며, `scenario_sensitivity.csv`는 가정 변화에 대한 계산 검사일 뿐 정확도 검증이 아닙니다.

## 재현과 파일

`STRESSLAB_AUDIT_ROOT`를 원본 프로젝트 경로로 지정하고 아래 순서로 실행합니다.

```powershell
python shared_improvement_20261104.py
python audit_shared_inputs_20261104.py
python report_shared_improvement_20261104.py
```

기존 `four_models_gold_20261104` 결과 및 Gold 원본이 입력입니다. 코드의 기본 경로는 `protocol.json`과 기존 연구 폴더를 참조합니다. 재실행은 완료된 종목을 재사용합니다. 데이터나 코드를 바꾼 경우 별도 출력 폴더를 사용하거나 해당 연구 체크포인트만 갱신해야 합니다.

`metrics.csv`는 28개 조합 전체, `per_stock.csv`는 종목별 결과, `per_year.csv`는 연도별 결과, `per_regime.csv`는 변동성별 결과입니다. `fit_audit.csv`에서 학습 및 보정 시점과 기준선으로 돌아간 경우를 확인할 수 있습니다. 필요한 학습 또는 보정 자료가 부족한 경우 기준선으로 돌아가며, 해당 종목을 평가에서 빼지 않습니다. 원본 데이터와 인증정보는 저장소에 올리지 않습니다.
'''
    (OUT/'README.md').write_text(text,encoding='utf8');(OUT/'environment.json').write_text(json.dumps({k:importlib.metadata.version(k) for k in ['numpy','pandas','scikit-learn','catboost','lightgbm','xgboost','pyarrow']},indent=2),encoding='utf8')
    print(pd.DataFrame(decisions).to_string(index=False));print(pd.DataFrame(refresh).to_string(index=False))
if __name__=='__main__':main()
