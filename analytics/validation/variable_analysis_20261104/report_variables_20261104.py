"""Report variable evidence and held-out incremental shock information separately."""
import json,hashlib
import numpy as np
import pandas as pd
from scipy.stats import norm
from analyze_variables_20261104 import OUT,ROOT,RAW,ALL,SRC
from report_long_universe import metric
from diagnose_rich_context import derive
from variable_labels_20261104 import labels

def main():
    assert json.loads((OUT/'progress.json').read_text())['status']=='complete'
    r=pd.read_parquet(OUT/'predictions.parquet')
    if (OUT/'response_predictions.parquet').exists():
        assert json.loads((OUT/'response_progress.json').read_text())['status']=='complete'
        r=pd.concat([r,pd.read_parquet(OUT/'response_predictions.parquet')],ignore_index=True)
    if (OUT/'guard_predictions.parquet').exists():
        r=pd.concat([r,pd.read_parquet(OUT/'guard_predictions.parquet')],ignore_index=True)
    expected_methods=r.method.nunique();assert r.groupby(['asset','date']).actual.nunique().eq(1).all()
    pairs=pd.read_csv(SRC/'eligible_pairs.csv',dtype={'asset':str})
    event=pd.Series(False,index=r.index)
    for _,pair in pairs.iterrows():event|=r.asset.eq(pair.asset)&r[pair.shock+'_event']
    rows=[]
    for scope,mask in [('all',pd.Series(True,index=r.index)),('selected_shock_events',event),('crash',r.actual<=-5),('rally',r.actual>=5)]:
        for name,z in r[mask].groupby('method'):rows.append(dict(scope=scope,method=name,**metric(z)))
    metrics=pd.DataFrame(rows);metrics.to_csv(OUT/'metrics.csv',index=False)
    asset_metrics=pd.DataFrame([dict(asset=a,method=m,**metric(z)) for (a,m),z in r.groupby(['asset','method'])]);asset_metrics.to_csv(OUT/'asset_metrics.csv',index=False)
    months=pd.period_range(r.date.min(),r.date.max(),freq='M');n=len(months);rng=np.random.default_rng(20261104)
    draws=np.array([np.concatenate([(s+np.arange(3))%n for s in rng.integers(0,n,size=(n+2)//3)])[:n] for _ in range(2000)])
    comparisons=[('baseline','complex_all'),('baseline','analysis_selected'),('no_shocks','complex_all')]+[(m,'complex_all') for m in sorted(r.method.unique()) if m.startswith('without_')]
    comparisons += [('baseline',m) for m in sorted(r.method.unique()) if m.startswith('orthogonal_')]
    stats=[]
    for reference,method in comparisons:
        z=r[r.method.eq(method)].merge(r[r.method.eq(reference)],on=['asset','date'],suffixes=('_new','_old'),validate='one_to_one')
        scopes=[('ALL',z)]+[(a,q) for a,q in z.groupby('asset')]
        for asset,q in scopes:
            for measure in ['mae_change','direction_gain']:
                h=q if measure=='mae_change' else q[q.actual_new.ne(0)]
                delta=(h.center_new-h.actual_new).abs()-(h.center_old-h.actual_old).abs() if measure=='mae_change' else (np.sign(h.center_new)==np.sign(h.actual_new)).astype(int)-(np.sign(h.center_old)==np.sign(h.actual_old)).astype(int)
                key=h.date.dt.to_period('M');num=delta.groupby(key).sum().reindex(months,fill_value=0).to_numpy();den=h.groupby(key).size().reindex(months,fill_value=0).to_numpy();ds=den[draws].sum(axis=1);values=num[draws].sum(axis=1)/np.maximum(ds,1)
                lo,hi=np.quantile(values[ds>0],[.025,.975]);stats.append(dict(asset=asset,reference=reference,method=method,metric=measure,n=len(h),change=delta.mean(),ci_low=lo,ci_high=hi))
    uncertainty=pd.DataFrame(stats);uncertainty.to_csv(OUT/'paired_uncertainty.csv',index=False)
    partial=pd.read_csv(OUT/'partial.csv',dtype={'asset':str});pvals=2*norm.sf(np.abs(partial.slope/partial.hac_se.replace(0,np.nan)))
    valid=np.isfinite(pvals);pv=np.asarray(pvals)[valid];order=np.argsort(pv);q=np.minimum.accumulate((pv[order]*len(pv)/np.arange(1,len(pv)+1))[::-1])[::-1]
    adjusted=np.empty(len(pv));adjusted[order]=np.minimum(q,1);partial['exploratory_bh_q']=np.nan;partial.loc[valid,'exploratory_bh_q']=adjusted
    partial['exploratory_by_q']=np.minimum(partial.exploratory_bh_q*np.sum(1/np.arange(1,len(pv)+1)),1)
    partial.to_csv(OUT/'partial_with_multiplicity.csv',index=False)
    selection_check=pairs[['asset','name','shock','direction','accuracy','sign_consistency']].merge(partial,on=['asset','shock'],validate='one_to_one')
    selection_check['same_sign_after_controls']=np.where(selection_check.direction.eq('positive'),selection_check.slope>0,selection_check.slope<0)
    selection_check['residual_ci_excludes_zero']=(selection_check.ci_low>0)|(selection_check.ci_high<0)
    selection_check['residual_sign_stability']=np.maximum(selection_check.positive_year_fraction,1-selection_check.positive_year_fraction)
    loco=uncertainty[(uncertainty.asset!='ALL')&uncertainty.reference.str.startswith('without_')&uncertainty.metric.eq('mae_change')].copy()
    loco['shock']=loco.reference.str.replace('without_','',regex=False)
    loco=loco[['asset','shock','change','ci_low','ci_high']].rename(columns={'change':'loco_mae_change','ci_low':'loco_ci_low','ci_high':'loco_ci_high'})
    selection_check=selection_check.merge(loco,on=['asset','shock'],validate='one_to_one');selection_check.to_csv(OUT/'original_selection_diagnosis.csv',index=False)
    importance=pd.read_csv(OUT/'importance.csv');variables=pd.read_csv(OUT/'variables.csv');shap=pd.read_csv(OUT/'shap.csv');selection=pd.read_csv(OUT/'selected.csv')
    feature=variables.groupby('feature').agg(stocks=('asset','nunique'),mean_abs_pearson=('pearson',lambda x:x.abs().mean()),mean_abs_partial=('regularized_partial_corr',lambda x:x.abs().mean()),mean_missing_fraction=('missing_fraction','mean'))
    im=importance[importance['mode'].eq('within_market_state')].groupby('feature').agg(validation_mae_increase_pp=('mae_increase_pp','mean'),positive_importance_stock_fraction=('mae_increase_pp',lambda x:x.gt(0).mean()))
    feature=feature.join(im).join(shap.groupby('feature').mean_abs_contribution_pp.mean()).join(selection.groupby('feature').asset.nunique().rename('selected_stock_count'));feature.to_csv(OUT/'feature_summary.csv')
    # Full pairwise matrix plus a readable table of every shock's relation to every raw state variable.
    d=pd.read_parquet(ROOT/'reports/rich_context_20261103/learning_table.parquet');d=d[d.end_date<pd.Timestamp('2022-01-01')-pd.Timedelta(days=20)]
    d=derive(d)
    risk=[]
    for asset,f in d.groupby('asset'):
        targets={'absolute_move':f.target.abs(),'downside_loss':(-f.target).clip(lower=0),'crash_indicator':f.target.le(-5).astype(float),'rally_indicator':f.target.ge(5).astype(float)}
        for label,y in targets.items():
            values=f[ALL].corrwith(y)
            for c in ALL:risk.append(dict(asset=asset,feature=c,target_kind=label,correlation=values[c],n=int(f[c].notna().sum()),period='pre2022_training',causal_effect=False))
    risk=pd.DataFrame(risk);risk.to_csv(OUT/'risk_variable_associations.csv',index=False)
    risk_summary=risk.groupby(['feature','target_kind']).correlation.mean().unstack('target_kind').add_prefix('risk_corr_')
    feature=feature.join(risk_summary);feature.to_csv(OUT/'feature_summary.csv')
    readable=feature.reset_index();readable.insert(1,'변수설명',readable.feature.map(labels()));readable.to_csv(OUT/'변수별_분석요약.csv',index=False,encoding='utf-8-sig')
    full=[]
    for asset,f in d.groupby('asset'):
        corr=f[RAW].corr(min_periods=100)
        for i,a in enumerate(RAW):
            for b in RAW[i+1:]:full.append(dict(asset=asset,feature_a=a,feature_b=b,correlation=corr.loc[a,b]))
    full=pd.DataFrame(full);full.to_parquet(OUT/'all_feature_correlations.parquet',index=False)
    full[full.feature_a.str.startswith('shock_')|full.feature_b.str.startswith('shock_')].to_csv(OUT/'shock_feature_correlations.csv',index=False)
    # Verify cohort, labels, temporal boundaries and controls for every shock.
    audit=pd.read_csv(OUT/'time_audit.csv');assert (pd.to_datetime(audit.train_label_end)<pd.to_datetime(audit.test_start)).all()
    residuals=pd.read_csv(OUT/'partial_residuals.csv');assert (pd.to_datetime(residuals.train_end)<pd.to_datetime(residuals.date)).all()
    residuals['asset']=residuals.asset.astype(str).str.zfill(6);residuals['date']=pd.to_datetime(residuals.date)
    augmented=residuals.merge(d[['asset','date','target','shock_fx','shock_rate','shock_oil','shock_vix']],on=['asset','date'],validate='many_to_one')
    histories={a:f for a,f in d.groupby('asset')};quality=[]
    for (asset,year,shock),z in augmented.groupby(['asset','year','shock']):
        train=histories[asset];train=train[train.end_date<=pd.Timestamp(z.train_end.iloc[0])]
        dy=float(((z.target-train.target.mean())**2).sum());ds=float(((z[shock]-train[shock].mean())**2).sum())
        quality.append(dict(asset=asset,year=year,shock=shock,n=len(z),return_nuisance_oos_r2=1-float((z.return_residual**2).sum())/dy if dy>0 else np.nan,
            shock_nuisance_oos_r2=1-float((z.shock_residual**2).sum())/ds if ds>0 else np.nan,shock_residual_sd=float(z.shock_residual.std())))
    pd.DataFrame(quality).to_csv(OUT/'nuisance_quality.csv',index=False)
    for _,z in residuals.groupby(['asset','shock']):
        z=z.sort_values('date');assert (pd.to_datetime(z.end_date).to_numpy()[:-1]<pd.to_datetime(z.date).to_numpy()[1:]).all()
    assert r.groupby(['asset','date']).method.nunique().eq(expected_methods).all()
    if (OUT/'response_time_audit.csv').exists():
        ra=pd.read_csv(OUT/'response_time_audit.csv')
        assert (pd.to_datetime(ra.train_label_end)<pd.to_datetime(ra.test_start)).all()
        assert (pd.to_datetime(ra.calibration_label_end)<pd.to_datetime(ra.test_start)).all()
    if (OUT/'state_support_audit.csv').exists():
        ga=pd.read_csv(OUT/'state_support_audit.csv')
        assert (pd.to_datetime(ga.pool_label_end)<pd.to_datetime(ga.date)).all()
        assert not ga.decision_uses_actual_return.any()
    reference=pd.read_parquet(ROOT/'reports/rich_context_20261103/predictions.parquet');reference=reference[reference.method.eq('all')]
    observed=r[r.method.eq('baseline')].merge(reference,on=['asset','date'],suffixes=('_new','_old'),validate='one_to_one');assert len(observed)==len(reference) and np.allclose(observed.actual_new,observed.actual_old)
    digest=hashlib.sha256((ROOT/'exports/seongjin_gold_v1_1/gold_stress_daily.parquet').read_bytes()).hexdigest();assert digest==json.loads((OUT/'protocol.json').read_text())['gold_sha256']
    verification=dict(status='passed',stocks=int(r.asset.nunique()),features=len(ALL),raw_features=len(RAW),observations=len(reference),methods=int(expected_methods),partial_associations=len(partial),
        all_features_analyzed=bool(set(variables.feature)==set(ALL)),same_keys_targets_as_previous=True,selection_uses2022_only=True,gold_unchanged=True,causal_identification=False,blind_test=False,production=False)
    (OUT/'verification.json').write_text(json.dumps(verification,indent=2),encoding='utf8')
    names=pairs.drop_duplicates('asset').set_index('asset')['name'];a=asset_metrics[asset_metrics.method.eq('baseline')].merge(asset_metrics[asset_metrics.method.eq('analysis_selected')],on='asset',suffixes=('_base','_guided'));a['name']=a.asset.map(names)
    a[['asset','name','n_base','direction_accuracy_base','direction_accuracy_guided','mae_base','mae_guided','crash_caught_base','crash_caught_guided']].to_csv(OUT/'종목별_분석반영결과.csv',index=False,encoding='utf-8-sig')
    lines=['# 변수별 관계 분석과 조건부 스트레스 모델 비교','',
        '확보된 101종목의 98개 입력을 각각 분석했습니다. 모든 금융 정보를 관측했다는 뜻은 아닙니다. 기존 Gold, Azure와 종목 목록은 변경하지 않았습니다.',
        '2000년부터 확보된 자료 중 2021년까지를 관계 분석에 사용하고, 2022년으로 피처를 선택했습니다. 2023~2026년의 동일한 종목과 날짜에서 평가했습니다. 평가 기간을 재사용했으므로 독립 블라인드가 아닙니다.','',
        '## 실제 수행한 분석','',
        '1. 각 변수의 결측, 관측 수, 단순 상관, 순위 상관, 다른 입력을 고려한 정규화 부분상관, 연도별 방향을 계산했습니다.',
        '2. 모든 원입력 쌍의 상관관계를 계산하고, 높은 중복 관계를 별도로 정리했습니다. 파생항은 새로운 독립 정보가 아닙니다.',
        '3. 각 원입력을 섞었을 때 오차가 얼마나 커지는지 2022년에 측정했습니다. 무작위 섞기와 비슷한 시장 구간 안의 섞기를 구분하고 파생항을 다시 계산했습니다.',
        '4. 네 충격은 각각 다른 세 충격과 관측된 시장 및 기업 정보로 설명되는 부분을 제거했습니다. 설명 모델은 과거로만 학습하고 이후 자료에 적용했습니다. 남은 충격과 남은 수익률의 관계, 연도별 방향, 불확실성을 확인했습니다.',
        '5. 추세, 변동성, 외국인 수급, 기관 수급, 부채 상태에 따라 충격 반응이 달라지는지 관측값과 모델 반응을 나눠 확인했습니다.',
        '6. 비선형 상호작용을 학습하는 더 큰 LightGBM과 분석으로 입력을 선택한 모델을 비교했습니다. 네 충격을 하나씩 뺀 모델을 각각 재학습해 실제 외표본 추가 설명력을 측정했습니다.','',
        '## 같은 조건의 외표본 결과','', '| 방법 | 관측 수 | 방향 일치율 | 중심 MAE | 고정 폭 5%p 진단 포함률 |','|---|---:|---:|---:|---:|']
    for _,v in metrics[metrics.scope.eq('all')].iterrows():lines.append(f'| {v.method} | {v.n} | {v.direction_accuracy:.2%} | {v.mae:.3f}%p | {v.fixed5_coverage:.2%} |')
    lines+=['','baseline은 같은 연간 학습 시점으로 다시 학습한 기존 규모 모델입니다. 이전 분기 재학습 수치와 그대로 비교하면 안 됩니다. complex_all은 깊이 6, 최대 잎 31개, 500개 트리이며 기존은 깊이 4, 최대 잎 15개, 250개 트리입니다. analysis_selected는 2022년 중요도로 고른 상태 변수와 네 충격을 사용합니다.','',
        'orthogonal_constant와 orthogonal_state_response는 시장 상태로 설명되는 수익률과 충격을 과거 외표본에서 먼저 제거하고, 남은 네 충격과 남은 수익률의 관계를 공동으로 학습합니다. 후자는 시장 상태에 따라 반응 계수가 달라집니다. 최종값은 시장 상태 평균에 충격의 추가 반응을 합한 조건부 평균입니다. 다른 모델의 중앙값과 의미가 다르므로 중심값 오차로 비교합니다. 인과효과 식별 모델로 승인한 것은 아닙니다.','',
        '## 충격별 추가 설명력','', '| 제외한 충격 | 충격을 다시 넣었을 때 MAE 변화 | 95% 블록 구간 | 방향 일치율 변화 |','|---|---:|---:|---:|']
    for shock in ['shock_fx','shock_rate','shock_oil','shock_vix']:
        q=uncertainty[(uncertainty.asset=='ALL')&(uncertainty.reference=='without_'+shock)];e=q[q.metric=='mae_change'].iloc[0];v=q[q.metric=='direction_gain'].iloc[0]
        lines.append(f'| {shock} | {e.change:+.3f}%p | {e.ci_low:+.3f} ~ {e.ci_high:+.3f} | {v.change*100:+.2f}%p |')
    lines+=['','MAE 변화가 음수이면 해당 충격을 추가했을 때 오차가 줄었다는 뜻입니다. 같은 날짜의 종목을 함께 묶은 3개월 블록 재표본추출입니다. 여러 비교의 구간은 탐색용이며 정식 승인 기준으로 자동 사용하지 않습니다.','',
        '## 해석과 파일','',
        '- variables.csv: 98개 변수 각각의 관계와 연도별 안정성입니다.',
        '- 변수별_분석요약.csv: 각 입력의 쉬운 설명과 분석 요약입니다. 파생항의 곱셈은 새로운 독립 정보가 아닙니다.',
        '- feature_summary.csv: 변수별 상관, 모델 기여, 조건부 섞기 중요도를 함께 봅니다. 상관이 크다는 이유만으로 유용한 입력이라고 판단하지 않습니다.',
        '- risk_variable_associations.csv: 방향뿐 아니라 절대 변동, 하방 손실, 급등 및 급락 발생과 각 변수의 관계입니다. 변동성을 설명하는 변수와 중심 수익률을 설명하는 변수를 구분합니다.',
        '- all_feature_correlations.parquet, shock_feature_correlations.csv: 전체 입력 관계와 네 충격의 모든 원입력 관계입니다.',
        '- partial_with_multiplicity.csv, stability.csv: 다른 관측 변수를 고려한 충격별 관계와 기간 안정성입니다. 탐색용 다중비교 보정도 포함했습니다.',
        '- nuisance_quality.csv: 다른 변수로 설명하는 보조 모델 자체의 외표본 성능입니다. 이 설명이 부정확하면 남은 관계를 충분히 분리한 영향이라고 단정할 수 없습니다.',
        '- original_selection_diagnosis.csv: 기존 선정 방향과 다른 변수 고려 후의 방향, 기간 안정성, 충격 제외 외표본 결과를 대조했습니다. 이 표로 평가 성적이 좋은 종목만 다시 고르지 않았습니다.',
        '- maps.csv: 시장 조건별 실제 반응과 모델의 국소 반응입니다. 학습 구간 설명이며 외표본 성능으로 해석하면 안 됩니다.',
        '- paired_uncertainty.csv: 전체 및 종목별 충격 제외 실험과 모델 변경 효과입니다.',
        '- metrics.csv, asset_metrics.csv: 급락과 급등 포착, 잘못된 포착까지 포함한 평가 결과입니다.',
        '- sensitivity.csv: 연도별 충격 변화에 대한 모델 반응입니다. 개별 변수의 관측 범위 확인은 공동 충격의 충분한 근거를 보장하지 않습니다.','',
        '부분상관, 잔차 관계, SHAP은 독립적인 인과효과의 증거가 아닙니다. 비슷한 시장 구간 내 섞기도 모든 변수의 결합 분포를 완벽히 보존하지는 않습니다. 공표 시각 및 수정 이력, 생존 편향, 관측되지 않은 기업 뉴스와 미래 수급 문제는 남습니다.',
        '고정 폭 5%p는 진단입니다. 모델의 위험 구간이 보정됐다는 의미가 아닙니다. 성능이 개선되지 않은 방법은 운영에 자동 반영하지 않습니다.','',
        '실행: 기존 로컬 연구 환경에서 analyze_variables_20261104.py, report_variables_20261104.py 순서입니다. 원본 학습 표는 직전 rich_context 연구 결과를 사용합니다. 공개 저장소에는 원천 데이터와 인증정보를 포함하지 않았습니다.']
    lines += ['', '## 상태별 반응 계수의 실패와 수정', '',
        '삼성증권 2026년 7월 20일에 상태별 반응 모델이 +260.43%를 계산했습니다. 실제 5거래일 수익률은 -0.295%였습니다. 과거 잔차 표본에서 거의 일정했던 부채비율이 최근 달라지면서 표준화 값이 141.65가 됐고, 상태와 충격의 곱이 과도하게 커졌습니다.',
        'orthogonal_support_guard는 과거 상태 범위나 과거 최근접 거리 기준을 벗어나면 이미 학습된 고정 계수 충격 반응으로 전환합니다. 수익률을 잘라내거나 하락을 강제하지 않습니다. 기준은 과거 상태만으로 계산합니다. 다만 평가 구간의 실패를 보고 개발한 수정이므로 독립 검증 결과가 아닙니다.',
        'state_support_audit.csv에 매 시점의 전환 사유와 수정 전후 값을 보존했습니다. 원래 실패 모델도 성능표에서 제외하지 않았습니다. 예외 처리가 정상 작동하는 것과 손익 추정이 정확한 것은 별개입니다.', '',
        '## 재실행', '',
        'run_variable_study.py에 --data-root로 기존 연구 데이터 폴더를 지정하고 --stage analysis, response, guard, report 순서로 실행합니다. 같은 validation 폴더의 이전 연구 코드가 필요합니다. 원본 자료와 학습 모델 파일은 공개 저장소에 올리지 않았습니다.']
    findings=['## 이번 결과의 판단','',
        '확보된 변수 분석은 완료했지만, 성능 목표는 달성하지 못했습니다. 복잡한 모델과 관계 분리 모델을 운영 후보로 교체하지 않습니다. 기존 모델도 목표 성능을 확보한 최종 모델이라는 뜻은 아닙니다.',
        '환율과 VIX는 나머지 입력을 유지한 제외 실험에서 외표본 MAE를 줄였습니다. WTI와 미국 금리는 전체 평균의 추가 개선 구간이 0을 포함합니다. 개별 종목에서의 관계와 전체 평균 성능을 구분해야 합니다.',
        f'기존 선정 {len(selection_check)}개 종목-충격 조합 중 다른 요인을 고려해도 방향이 같은 것은 {int(selection_check.same_sign_after_controls.sum())}개입니다. 그러나 충격 추가의 종목별 MAE 개선 구간이 0 아래인 조합은 {int(selection_check.loco_ci_high.lt(0).sum())}개입니다. 이 비교 구간은 탐색용이며, 이를 보고 종목을 다시 선택하지 않았습니다.',
        '과거 수급 변수의 조건부 섞기 중요도는 대부분 작습니다. 종목 20일 변동성은 학습 자료에서 다음 5일 절대 변동과 평균 상관 약 0.28을 보이지만, 중심값 오차에 대한 추가 설명력은 작습니다. 움직임의 크기를 설명하는 것과 방향을 설명하는 것은 다릅니다.',
        '연간 재무 입력은 2021년 이전 분석 표본에서 평균 약 77.6%가 결측입니다. 오래된 가격 이력이 길어도 같은 기간의 기업 설명 자료까지 충분한 것은 아닙니다. 결측을 실제 재무 값 0으로 해석하지 않았습니다.',
        '잔차 분리에 쓰는 보조 모델의 수익률 외표본 R² 중앙값은 충격별 약 0.01~0.05입니다. 관측된 다른 요인을 충분히 설명했다고 볼 수 없으므로 남은 계수를 완전히 독립된 영향이라고 단정하지 않습니다.',
        '급락 정답 2,217건에서 기존 모델과 복잡한 모델 모두 중심값이 -5% 이하였던 것은 88건입니다. 고정 계수 잔차 모델은 145건으로 늘었지만, 전체 급락 오경보도 135건에서 209건으로 늘고 급락 구간 MAE도 악화됐습니다. 급락 포착 개선으로 채택하지 않습니다.',
        '따라서 이번 자료는 종목별 충격 관련성과 실패 조건을 설명하는 연구 근거로 사용할 수 있습니다. 좁은 손익 범위나 높은 방향 정확도를 보장하는 서비스 모델로 사용할 근거는 아직 없습니다. 다음 연구를 한다면 이번 평가 기간을 다시 독립 검증이라고 부르지 않고, 발표 시각이 확인된 자료와 별도 평가 구간을 먼저 고정해야 합니다.','']
    lines=lines[:5]+findings+lines[5:]
    (OUT/'README.md').write_text('\n'.join(lines)+'\n',encoding='utf8')

if __name__=='__main__':main()
