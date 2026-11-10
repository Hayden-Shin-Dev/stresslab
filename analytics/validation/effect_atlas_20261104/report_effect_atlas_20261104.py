"""Readable stock-variable evidence, with unsupported identification explicitly retained."""
import json,hashlib
import numpy as np
import pandas as pd
from analyze_effect_atlas_20261104 import OUT,ROOT,RAW,SHOCKS,SRC
from variable_labels_20261104 import labels
from report_long_universe import metric

def main():
    assert json.loads((OUT/'progress.json').read_text())['status']=='complete'
    response=OUT/'coordinates';assert json.loads((response/'progress.json').read_text())['status']=='complete'
    e=pd.read_parquet(response/'effects.parquet');c=pd.read_parquet(response/'curves.parquet');m=pd.read_parquet(OUT/'matching.parquet');h=pd.read_parquet(response/'heterogeneity.parquet');a=pd.read_parquet(response/'time_audit.parquet')
    assert (pd.to_datetime(a.train_end)<pd.to_datetime(a.test_start)).all()
    assert pd.to_datetime(a.test_end).max()<pd.Timestamp('2022-01-01')
    for _,z in c.groupby(['asset','feature','fold','outcome']):assert abs(np.average(z.ale,weights=z.n))<1e-8
    assets=json.loads((SRC/'selected_assets.json').read_text());assert len(m)==len(assets)*len(RAW)
    names=pd.read_csv(SRC/'eligible_pairs.csv',dtype={'asset':str}).drop_duplicates('asset').set_index('asset')['name'];lab=labels()
    rows=[]
    for asset in assets:
        for feature in RAW:
            rec=dict(asset=asset,name=names.get(asset,asset),feature=feature,description=lab[feature])
            for outcome in ['return','up_score','crash_score']:
                z=e[(e.asset==asset)&(e.feature==feature)&(e.outcome==outcome)]
                rec[outcome+'_folds']=len(z);rec[outcome+'_effect']=z.net_effect.mean();rec[outcome+'_amplitude']=z.range_effect.mean()
                rec[outcome+'_stable_sign']=bool(len(z)==2 and ((z.net_effect>0).all() or (z.net_effect<0).all()))
                rec[outcome+'_shape']='insufficient' if len(z)<2 else ('mixed_local_directions' if ((z.positive_local_fraction>.2)&(z.negative_local_fraction>.2)).any() else 'mostly_one_direction')
            matched=m[(m.asset==asset)&(m.feature==feature)].iloc[0];rec['matched_status']=matched.status
            for key in ['n','unique_reference_n','max_control_smd','return_contrast_pp','feature_high','feature_low','up_frequency_contrast_pp','crash_frequency_contrast_pp']:rec['matched_'+key]=matched.get(key,np.nan)
            rec['interpretation']='Model-conditional pattern; not isolated causal effect. Matched contrast usable descriptively only if balanced.'
            rows.append(rec)
    result=pd.DataFrame(rows);result.to_csv(OUT/'종목별_변수영향.csv',index=False,encoding='utf-8-sig')
    turning=[]
    for (asset,feature,fold,outcome),z in c.groupby(['asset','feature','fold','outcome']):
        z=z.sort_values('bin')
        for i in range(1,len(z)):
            left=z.iloc[i-1];right=z.iloc[i]
            if left.local_change*right.local_change<0:
                turning.append(dict(asset=asset,name=names.get(asset,asset),feature=feature,description=lab[feature],fold=fold,outcome=outcome,
                    candidate_low=float(left.low),candidate_high=float(right.high),left_local_change=float(left.local_change),right_local_change=float(right.local_change),
                    interpretation='Model local-direction reversal candidate, not a certified economic threshold'))
    pd.DataFrame(turning).to_csv(OUT/'반응방향_변화후보.csv',index=False,encoding='utf-8-sig')
    c=c.copy();c.insert(1,'name',c.asset.map(names));c.to_parquet(OUT/'named_curves.parquet',index=False)
    shock=c[(c.feature.isin(SHOCKS))&(c.outcome=='return')].groupby(['asset','name','feature','fold']).apply(lambda z:pd.Series(dict(n=z.n.sum(),low_mid=(z.low.iloc[0]+z.high.iloc[0])/2,high_mid=(z.low.iloc[-1]+z.high.iloc[-1])/2,low_to_high_model_change_pp=z.ale.iloc[-1]-z.ale.iloc[0])),include_groups=False).reset_index()
    shock.to_csv(OUT/'종목별_충격반응곡선요약.csv',index=False,encoding='utf-8-sig')
    hs=h.groupby(['asset','shock','state','outcome']).agg(folds=('fold','nunique'),positive=('response_difference',lambda x:(x>0).sum()),negative=('response_difference',lambda x:(x<0).sum()),mean_difference=('response_difference','mean'),mean_abs_difference=('response_difference',lambda x:x.abs().mean()),reversal_folds=('sign_reversal','sum')).reset_index()
    hs['stable_difference_sign']=(hs.folds==2)&((hs.positive==2)|(hs.negative==2));hs['state_description']=hs.state.map(lab);hs['name']=hs.asset.map(names);hs.to_csv(OUT/'시장조건별_충격반응차이.csv',index=False,encoding='utf-8-sig')
    m.to_csv(OUT/'비슷한조건_실제관측비교.csv',index=False,encoding='utf-8-sig')
    q=pd.read_parquet(response/'explanation_model_quality.parquet');q['beats_constant']=q.mae_or_score_brier<q.constant_reference;q.groupby('outcome').agg(folds=('asset','size'),better_fraction=('beats_constant','mean')).to_csv(OUT/'explanation_model_quality_summary.csv')
    verification=dict(stocks=len(assets),raw_variables=len(RAW),stock_variable_analyses=len(m),curve_points=len(c),heterogeneity_rows=len(h),time_audit_passed=True,ale_centering_passed=True,
        balanced_contrasts=int(m.status.eq('balanced_descriptive').sum()),causal_identification=False,classifier_scores_calibrated=False,production=False)
    verification['return_curves_supported_in_both_periods']=int(result.return_folds.eq(2).sum())
    protocol=json.loads((OUT/'protocol.json').read_text());assert hashlib.sha256((ROOT/'exports/seongjin_gold_v1_1/gold_stress_daily.parquet').read_bytes()).hexdigest()==protocol['gold_sha256'];verification['gold_unchanged']=True
    lines=['# 종목별 변수 반응 분석','',
        '성능 순위보다 변수의 반응 방향, 비선형 구간, 시장 조건별 차이와 관측 근거를 먼저 정리했습니다. 101종목의 70개 원입력입니다. 기존 98개 중 나머지 28개는 원입력의 곱이므로 독립 변수로 중복 해석하지 않습니다.','',
        '## 무엇을 계산했는지','',
        '1. 2018년과 2020년 이전 자료로 각각 설명 모델을 학습하고, 이후 2년의 관측 상태에서 변수 반응을 계산했습니다. 분석에 2022년 이후 정답을 사용하지 않았습니다.',
        '2. 변수별 관측 범위를 6개 구간으로 나눠 그 구간 안에서만 값을 바꾸었습니다. 나머지 입력을 유지한 모델 반응을 누적한 ALE 곡선입니다. 단순 상관이나 중요도 점수와 달리 반응 방향과 값의 구간을 확인할 수 있습니다.',
        '3. 중심 수익률, 상승 점수, -5% 이하 급락 점수를 따로 분석했습니다. 분류 점수는 보정된 미래 확률이 아닙니다.',
        '4. 네 충격의 국소 반응이 66개 다른 시장 및 기업 입력의 높고 낮음에 따라 달라지는지 조사했습니다. 구간 구성과 다른 변수도 달라질 수 있으므로 독립된 두 변수 상호작용 효과라고 단정하지 않습니다.',
        '5. 실제 과거 자료에서 변수 값이 높은 표본과 낮은 표본을 다른 관측 조건으로 매칭했습니다. 표준화 차이, 비교 가능한 표본 수와 재사용된 대조 표본을 검사했습니다. 균형이 부족한 결과는 독립 영향 근거로 사용하지 않습니다.','',
        '## 읽는 순서','',
        '- 종목별_변수영향.csv: 종목과 변수별 방향, 반응 크기, 기간 안정성, 실제 관측 비교의 적합 여부입니다.',
        '- 종목별_충격반응곡선요약.csv: 충격이 표에 적힌 낮은 값에서 높은 값으로 바뀔 때 설명 모델의 중심 수익률이 얼마나 달라지는지입니다. 네 충격은 단위가 다르므로 계수 크기를 그대로 비교하지 않습니다.',
        '- 시장조건별_충격반응차이.csv: 어떤 시장 조건에서 충격 반응이 달라지는지입니다.',
        '- 비슷한조건_실제관측비교.csv: 실제 수익률 차이와 다른 조건이 얼마나 맞는지입니다. remaining_imbalance는 통제가 충분하지 않다는 뜻입니다.',
        '- coordinates/curves.parquet: 중복 관계를 제거한 모델의 모든 반응 곡선, 표본 수와 실제 관측값입니다. observed 항목은 단순 구간 통계이며 통제된 효과가 아닙니다. 최상위 curves.parquet는 중복 입력을 유지했던 최초 진단으로 보존했습니다.','',
        '## 해석 범위','',
        f'총 {len(m):,}개 종목-변수 비교 중 설정한 표본 수와 관측 조건 균형 기준을 통과한 비교는 {verification["balanced_contrasts"]:,}개입니다. 나머지 비교가 없거나 불균형한 사실을 숨기지 않았습니다.',
        f'중심 반응 곡선을 두 기간 모두 충분한 구간 표본으로 계산할 수 있었던 종목-변수 조합은 {verification["return_curves_supported_in_both_periods"]:,}개입니다. 나머지는 영향이 없다는 뜻이 아니라 비교 범위나 표본이 부족할 수 있습니다. folds와 insufficient 표시를 함께 확인해야 합니다.',
        'ALE는 모델이 학습한 반응을 설명합니다. 모델이 틀리면 반응 곡선도 틀릴 수 있습니다. 실제 영향을 입증한 값으로 표시하지 않습니다. 기존 변수 분석의 충격 잔차 관계, 관측 비교, 기간 안정성을 함께 봐야 합니다.',
        '국소 변화의 구간은 분기 단위 재표본추출이며 설명 모델을 고정합니다. 모델 재학습 불확실성까지 포함한 신뢰구간이 아닙니다. 매칭 구간도 대조 표본 재사용의 불확실성을 완전히 반영하지 못하므로 탐색용입니다.',
        '모든 기업 사건과 미래 수급을 관측하지 못했고, 일부 입력은 정의상 서로 연결돼 있습니다. 확보된 변수들을 분석한 것이 모든 시장 원인을 분리했다는 뜻은 아닙니다.','',
        '방법 근거: https://doi.org/10.1111/rssb.12377','']
    if (OUT/'application_predictions.parquet').exists():
        r=pd.read_parquet(OUT/'application_predictions.parquet');assert r.groupby(['asset','date']).actual.nunique().eq(1).all();assert r.groupby(['asset','date']).method.nunique().eq(2).all()
        metrics=pd.DataFrame([dict(method=k,**metric(z)) for k,z in r.groupby('method')]);metrics.to_csv(OUT/'application_metrics.csv',index=False)
        pd.DataFrame([dict(asset=a,method=k,**metric(z)) for (a,k),z in r.groupby(['asset','method'])]).to_csv(OUT/'application_asset_metrics.csv',index=False)
        audit=pd.read_csv(OUT/'application_time_audit.csv');assert (pd.to_datetime(audit.train_end)<pd.to_datetime(audit.test_start)).all();assert (pd.to_datetime(audit.feature_selection_label_end)<pd.Timestamp('2022-01-01')).all()
        verification['application_time_audit_passed']=True
        lines+=['## 분석 결과의 모델 반영','',
            '두 분석 기간에서 반응 방향이 같고 관측 비교의 균형 기준을 통과한 입력을 중심값과 급락 관점에서 각각 선정했습니다. 네 충격과 기존 기본 시장 입력은 비교를 위해 유지했습니다. 선정된 상태 변수 중 기간별 차이 방향이 유지된 충격 조합을 추가했습니다. 2022년 이후 결과로 입력을 고르거나 반응 부호를 강제하지 않았습니다.',
            '동일한 2023~2026년 종목과 날짜에 적용했습니다. 이 평가 기간은 재사용한 연구 구간이며 독립 블라인드가 아닙니다. 점수 개선이 없으면 운영 모델로 반영하지 않습니다.','',
            '| 방식 | 방향 일치율 | 중심 오차 | 고정 5%p 폭 진단 포함률 |','|---|---:|---:|---:|']
        for _,v in metrics.iterrows():lines.append(f'| {v.method} | {v.direction_accuracy:.2%} | {v.mae:.3f}%p | {v.fixed5_coverage:.2%} |')
        lines+=['','고정 폭 포함률은 진단용이며 학습하거나 보정한 위험 구간이 아닙니다.']
    lines+=['','실행 순서: analyze_effect_atlas_20261104.py, apply_effect_atlas_20261104.py, report_effect_atlas_20261104.py. 기존 연구 모듈과 비공개 학습 자료가 필요합니다. Azure와 Gold 계약은 변경하지 않았습니다.']
    lines+=['','## 중복된 변수 정의를 먼저 수정한 이유','',
        '상대수익률은 종목 수익률에서 시장 수익률을 뺀 값입니다. 이 세 값을 동시에 고정한 채 하나만 바꿀 수는 없습니다. 부채비율과 자기자본비율, 추세 차이와 변동성 비율에도 같은 문제가 있었습니다.',
        'coordinates 분석은 확인된 10개 중복 정의를 제거한 60개 입력으로 모델을 학습합니다. 파생 변수를 분석할 때는 해당 변수가 원래 기본 변수 하나를 대신하도록 좌표를 바꿉니다. 예를 들어 상대수익률을 바꾸면 시장 수익률을 유지하고 종목 수익률을 함께 바꿉니다. 나머지 값을 모두 유지한 독립 개입이라는 뜻이 아닙니다.',
        '변수끼리 정의상 묶인 관계와 실제 금융 상관을 구분했습니다. 모델 적용에서도 분석으로 선택한 중복 변수는 기본 입력으로 통합했습니다. 원래 분석은 삭제하지 않았습니다.',
        '전체 실행 순서: analyze_effect_atlas_20261104.py → analyze_coordinate_effects_20261104.py → balance_effect_atlas_20261104.py → apply_effect_atlas_20261104.py → report_effect_atlas_20261104.py → plot_effect_atlas_20261104.py.']
    if (OUT/'entropy_balanced_contrasts.csv').exists():
        b=pd.read_csv(OUT/'entropy_balanced_contrasts.csv',dtype={'asset':str});assert len(b)==len(assets)*len(RAW)
        assert not b.outcome_used_for_weights.fillna(False).astype(bool).any()
        verification['entropy_balanced_comparisons']=len(b);verification['entropy_supported']=int(b.status.eq('balanced_descriptive').sum())
        joined=result.merge(b,on=['asset','feature'],suffixes=('_atlas','_balanced'),validate='one_to_one');joined.to_csv(OUT/'통합_변수분석.csv',index=False,encoding='utf-8-sig')
        partial=pd.read_csv(ROOT/'reports/variable_analysis_20261104/partial_with_multiplicity.csv',dtype={'asset':str}).rename(columns={'shock':'feature'})
        joined[joined.feature.isin(SHOCKS)].merge(partial,on=['asset','feature'],validate='one_to_one').to_csv(OUT/'충격별_근거통합.csv',index=False,encoding='utf-8-sig')
        lines+=['','## 다른 조건을 가중치로 맞춘 실제 관측 비교','',
            '최근접 표본만으로 조건 차이가 남아, 추가로 엔트로피 균형 방식의 정규화 근사 가중치를 계산했습니다. 수익률을 보지 않고 높은 값과 낮은 값 집단의 다른 입력 평균 및 결측 비율을 맞췄습니다. 원 논문의 정확한 제약식과 달리 작은 정규화 벌점을 둔 근사 방식입니다.',
            f'{len(b):,}개 비교 중 {verification["entropy_supported"]:,}개가 평균 조건 차이, 유효 표본 수, 가중치 쏠림 및 수렴 기준을 통과했습니다. 기준 미달 결과는 별도로 남겼습니다.',
            '통합_변수분석.csv에서 ALE 반응, 기간 안정성과 가중치를 적용한 실제 수익률 차이를 같이 볼 수 있습니다. 평균을 맞춘 것이 분포 전체나 관측하지 못한 요인을 통제했다는 뜻은 아닙니다. 이 차이를 인과효과나 임의 충격의 가격 계수로 직접 적용하지 않습니다.',
            '가중 관측 비교에서는 해당 종목의 장기 표본에서 절반 이상 관측되고 변동이 있는 입력만 통제합니다. 그보다 결측이 많은 연간 재무 정보 등은 모든 비교에서 통제됐다고 주장할 수 없습니다. 실제 사용한 입력은 controls_list에 남겼습니다. 반응 모델은 결측을 지원하는 방식으로 전체 60개 입력을 사용합니다.',
            'entropy_balanced_contrasts.csv의 feature_high와 feature_low가 실제 비교한 값입니다. return_contrast_pp는 해당 가중 표본의 수익률 차이입니다. 모델 반응 곡선의 차이와 다릅니다.',
            '충격별_근거통합.csv에는 이전 연구의 다른 변수를 고려한 시간순 잔차 관계와 이번 반응 곡선 및 가중 관측 비교를 합쳤습니다. 반응방향_변화후보.csv의 구간은 모델에서 반응 방향이 바뀐 후보이며 검증된 금융 임계값이 아닙니다.',
            '추가 실행: balance_effect_atlas_20261104.py 다음 report_effect_atlas_20261104.py. 방법 근거: https://doi.org/10.1093/pan/mpr025']
        if (OUT/'사전지정5종목_충격반응안정성.csv').exists():
            cases=pd.read_csv(OUT/'사전지정5종목_충격반응안정성.csv',dtype={'asset':str});cases.insert(1,'name',cases.asset.map(names));cases.to_csv(OUT/'5종목_관측반응_설명용.csv',index=False,encoding='utf-8-sig')
            lines+=['','## 유가 반응을 실제 종목으로 읽는 예','',
                '사전에 정한 삼성전자, SK하이닉스, 대한항공, S-Oil, 현대차를 설명용 사례로 사용했습니다. 성능이 좋은 종목을 보고 고른 목록이 아닙니다. 아래는 유가가 낮았던 집단 대비 높았던 집단의 가중 실제 수익률 차이입니다. 정확한 유가 수준은 entropy_balanced_contrasts.csv의 feature_low와 feature_high에 있습니다.','',
                '| 종목 | 실제 수익률 차이 | 분기 재표본추출 구간 | 연도를 하나씩 제외했을 때 같은 방향 비율 |','|---|---:|---:|---:|']
            for _,v in cases[cases.shock.eq('shock_oil')].iterrows():lines.append(f'| {v["name"]} | {v.contrast_pp:+.2f}%p | {v.fixed_weight_quarter_ci_low:+.2f} ~ {v.fixed_weight_quarter_ci_high:+.2f}%p | {v.leave_one_year_sign_agreement:.0%} |')
            lines+=['','가중치를 고정한 분기 재표본추출입니다. 가중치 추정 오차와 관측되지 않은 요인까지 포함한 신뢰구간이 아닙니다. 연도 제외도 가중치를 재추정하지 않은 민감도 진단입니다. 향후 유가 충격의 인과적 손익 계수로 바로 적용하지 않습니다.']
    (OUT/'README.md').write_text('\n'.join(lines)+'\n',encoding='utf8');(OUT/'verification.json').write_text(json.dumps(verification,indent=2))
if __name__=='__main__':main()
