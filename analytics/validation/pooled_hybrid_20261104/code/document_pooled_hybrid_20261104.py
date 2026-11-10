"""Generate the concise research handoff from computed results, not manual metrics."""
import hashlib,json,platform,importlib.metadata
from datetime import datetime,timezone
import pandas as pd
from pooled_stress_core_20261104 import OUT,ROOT

def main():
    c=pd.read_csv(OUT/'center_metrics.csv');risk=pd.read_csv(OUT/'interval_metrics.csv');ci=pd.read_csv(OUT/'center_date_block_ci.csv');old=json.loads((OUT/'legacy_reproduction.json').read_text());sel=json.loads((OUT/'development_selection.json').read_text())
    names={'ridge':'종목별 Ridge','lightgbm':'종목별 LightGBM','catboost':'종목별 CatBoost','partial_ridge':'부분 풀링 팩터','hybrid_catboost':'팩터 + CatBoost 잔차','hybrid_lightgbm':'팩터 + LightGBM 잔차'}
    lines=['# 부분 풀링 스트레스 모델 비교','',
    '기존 Gold와 운영 모델은 유지하고 로컬에서 비교했습니다. 평균 폭 5%p는 승인 기준에서 제외했습니다. 중심값은 0 수익률, 구간은 무조건부 역사적 분위수 및 변동성 기준선과 비교했습니다.','',
    '## 결과','',
    '부분 풀링은 중심값의 평균 오차를 조금 줄였고 충격 크기에 따른 선형 반응을 구현했습니다. 하지만 급락 중심값 오차는 악화됐습니다. 하이브리드를 정식 모델로 교체할 근거는 부족합니다. 일반 구간의 상대 성능 개선과 극단 손실 추정의 신뢰성은 구분해야 합니다.','',
    '| 모델 | 중심 MAE(%p) | 0 대비 개선 | 표준 R² | 방향 일치율 | 급락 MAE(%p) |','|---|---:|---:|---:|---:|---:|']
    for name in ['ridge','lightgbm','catboost','partial_ridge','hybrid_catboost','hybrid_lightgbm']:
        z=c[c.model==name].iloc[0];lines.append(f'| {names[name]} | {z.mae:.3f} | {z.mae_gain_zero:.2%} | {z.r2:.2%} | {z.direction:.2%} | {z.crash_mae:.3f} |')
    h=ci[ci.model=='hybrid_lightgbm'].iloc[0]
    lines += ['',f'LightGBM 하이브리드의 기존 CatBoost 대비 MAE 개선은 {h.gain:.3f}%p이며 월 블록 재표본추출 95% 구간은 [{h.gain_lo:.3f}, {h.gain_hi:.3f}]%p입니다. 0을 포함합니다. 급락 MAE 개선 구간은 [{h.crash_gain_lo:.3f}, {h.crash_gain_hi:.3f}]%p로 음수이며 급락에서는 악화됐습니다.',
    '급락은 실제 5거래일 수익률 -5% 이하입니다. 전체 2,928개 종목별 평가값, 20종목, 169개 날짜 중 급락 390개 표본을 사용했습니다. 같은 날짜의 종목은 독립 사건이 아닙니다. 재표본추출은 46개 달을 단위로 모든 종목을 함께 묶어 2,000회 수행했습니다. 반복 연구 및 다중 비교이므로 신뢰구간을 독립적인 최종 승인 근거로 해석하지 않습니다.','',
    '## 구간 비교','', '| 모델 / 보정 | 포함률 | 폭(%p) | 구간 점수 | 무조건부 대비 점수 개선 | 급락 하방 이탈률 |','|---|---:|---:|---:|---:|---:|']
    for model,method in [('unconditional','historical'),('volatility_history','normalized_history'),('catboost','asset'),('catboost','pooled'),('partial_ridge','pooled'),('hybrid_lightgbm','pooled'),('hybrid_lightgbm','har_proxy')]:
        z=risk[(risk.model==model)&(risk.interval==method)].iloc[0];lines.append(f'| {names.get(model,model)} / {method} | {z.coverage80:.2%} | {z.width80:.2f} | {z.interval_score80:.3f} | {z.interval_score_gain_unconditional:.2%} | {z.crash_lower_breach:.2%} |')
    lines += ['', '구간 점수는 폭과 구간 밖 오차를 함께 벌점으로 계산하며 작을수록 좋습니다. 이번 10/90 분위수 평균 Pinball Loss는 구간 점수의 1/20이므로 두 지표의 개선율이 같은 것은 독립적인 두 증거가 아닙니다.',
    '전체 잔차 풀링은 연도별 684~757행이지만 날짜는 37~46개입니다. 독립 사건이 700개가 됐다는 뜻이 아닙니다. 업종 및 시장 변동성 구간별 풀링도 비교했으며 전체 결과는 interval_metrics.csv에 있습니다.',
    'HAR는 일별 수익률 제곱의 1일/5일/22일 평균으로 다음 5일 변동을 설명하는 대용 모형입니다. 과거 분봉 실현변동성을 사용하는 정식 HAR-RV가 아닙니다. 폭과 평균 점수는 줄었으나 급락 하방 이탈이 늘어 정식 채택하지 않았습니다.',
    f'2020~2021 내부 개발 기준으로 선택된 중심값은 {sel["center_choice"]}, 구간 후보는 {sel["interval_choice"]}입니다. 이후 2023~2026 평가에서 하방 문제를 확인했으므로 자동 승격하지 않습니다. 평가 결과가 가장 좋은 조합을 사후 선택해 승인하지 않았습니다.','',
    '## 모델 구조','',
    '입력은 기존 Gold에서 계산한 확정 일별 시장 상태와 종목 상태, 사용자가 지정한 환율(%), 미국 10년 금리(bp), WTI(%), VIX 변화(포인트)입니다. 학습에서는 실제 이후 5거래일 충격과 같은 기간 종목 수익률을 연결합니다.',
    '부분 풀링 팩터는 공통 계수 + 종목별 절편 편차 + 종목별 네 충격 계수 편차를 학습합니다. 종목별 편차에 더 강한 Ridge 벌점을 적용합니다. 공통 충격과 시장 추세/변동성의 상호작용도 포함합니다. 정답은 기존처럼 사전에 계산한 변동성으로 정규화하며 결과는 종목 수익률로 환산합니다.',
    '잔차 보정은 2005년부터 매년 당시 이전 데이터만으로 팩터 모델을 학습하고, 다음 기간에서 틀린 값을 모아 학습했습니다. 선형 모델이 자기 학습 데이터에 맞춘 인샘플 잔차를 쓰지 않았습니다. CatBoost와 LightGBM은 잔차 보정에만 사용합니다.',
    '학습은 겹치는 5일 구간을 매일 사용합니다. 풀링 행에는 날짜별 가중치를 주어 종목이 많아진 날짜의 비중이 과도하게 커지지 않도록 했습니다. 원자료가 없는 시기의 신규 상장 종목은 행을 만들어 채우지 않았습니다.',
    '각 연도 학습의 마지막 연도를 내부 검증으로 분리해 공통 벌점과 종목 편차 벌점을 선택했습니다. 이전 1년은 외부 구간 보정용으로 남겼습니다. 학습/보정/평가 정답 종료일 사이에 20일 경계를 적용했습니다. 과거 내부 튜닝 이력은 inner_tuning.csv에 있습니다.',
    '과거 유사 시장 검색 A는 충격을 제외한 STATE만 사용합니다. B는 같은 상태와 사용자 충격을 사용합니다. A의 소수 사례를 정답처럼 다시 학습하지 않으며 검색 예시는 별도 관측 근거로 제공합니다.','',
    '## 극단 입력','',
    '12차원 시장 상태와 충격 조합을 과거 자료와 비교합니다. 가까운 사례의 거리 기준을 벗어날수록 트리 보정을 줄이고, 기준 거리의 두 배 이상에서는 보정을 0으로 둡니다. 이는 지원 범위를 점검하는 규칙이며 확률이나 정확도 보장이 아닙니다. 변수별 과거 범위 이탈도 따로 표시합니다.',
    '환율 +2.5%/금리 +50bp에서 +10%/+200bp로 바꿔도 완전히 같은 결과를 내는 현상은 새 세 모델에서 0/20종목입니다. 선형 외삽이 숫자를 바꾼다는 뜻이며, 그 값이 정확하다는 검증은 아닙니다. 트리 보정이 줄어들면서 전체 결과가 비례하지 않을 수 있습니다.',
    '사용자 VIX 입력을 자동으로 바꾸지 않습니다. 변화 0은 지수 수준 0이 아니라 기존 수준 유지입니다. 과거에 실제 관측된 공동 충격은 검색 사례로 제시하며 사용자 지정 시나리오를 덮어쓰지 않습니다.',
    '2026-10-19 상태에서 삼성전자와 현대차 각 5,000만원, 환율 +5%, 금리 +100bp, WTI/VIX 변화 0을 계산한 결과는 service_example.csv에 있습니다. 부분 풀링 팩터 손익은 약 +13.5만원이며 이 조합은 관측 지원 범위를 벗어나 검증된 예상 손익으로 승인하지 않았습니다.',
    '삼성전자 팩터 중심값 +0.382%는 무충격 모델값 +0.259%에 환율 기여 -3.773%p와 금리 기여 +3.896%p가 더해진 결과입니다. 이 양의 금리 계수는 과거 조건부 통계 관계이며 금리 상승의 인과적 이익이라는 뜻이 아닙니다. 하이브리드별 손익 차이도 함께 저장했습니다.',
    '고정 상태에서 계수 부호는 80개 종목/충격 조합 중 77개가 네 평가 연도에 걸쳐 유지됐습니다. 강한 부분 풀링 자체가 부호를 안정화할 수 있으므로 부호 안정성과 예측 유용성은 다릅니다. 실제 시장 상태가 달라진 효과는 factor_slopes_by_year.csv, 같은 상태에서 계수만 비교한 결과는 coefficient_stability_fixed_state.csv에 있습니다.','',
    '## 기존 진단 재현과 데이터 한계','',
    f'원래 CatBoost MAE {old["mae"]:.3f}%p, 0 기준 MAE {old["zero_mae"]:.3f}%p, 폭 {old["width80"]:.2f}%p, 보정 33~38개를 재현했습니다. 시장 평균 제거 후 방향은 {old["demeaned_direction"]:.2%}, 상관은 {old["demeaned_corr"]:.4f}입니다. 51.5%와 정확히 같지는 않으며 날짜별 실제/모델 평균을 각각 제거한 정의입니다.',
    f'기존 R² 약 1.5%는 0 수익률 기준 비중심 R² {old["uncentered_r2_vs_zero"]:.2%}로 재현됩니다. 실제 평균을 기준으로 한 표준 R²는 {old["r2"]:.2%}입니다. 서로 다른 지표를 같은 이름으로 섞지 않았습니다.',
    '이번 비교의 기존 모델도 동일 조건으로 재학습했습니다. 과거 유가의 시작/종료 수준이 0 이하인 36개 학습 행을 제외했으므로 원래 보관 결과와 수치가 조금 다릅니다. 평가 종목/날짜/실제 수익률은 원래 2,928행과 정확히 같습니다. 부분 풀링은 같은 Gold의 이용 가능한 공통 종목 이력을 공유합니다.',
    'Gold sector_id가 모두 비어 있어 업종 풀링은 연구용으로 지정한 넓은 경제 그룹입니다. 당시의 공식 업종 이력으로 검증한 결과가 아닙니다. 1종목 그룹은 전체 풀링으로 대체했습니다. 현재 20종목에 대한항공과 S-Oil은 없어 두 기업의 반대 반응을 이번 실험으로 입증하지 않았습니다.',
    '공표 시각 available_at은 모두 누락돼 있고 당시 수정 전 데이터 이력도 없습니다. 코드의 시간 경계 검증 통과를 원천 데이터의 완전한 시점 정합성 승인으로 해석하지 않습니다. 현재 종목 기준 생존 편향도 남습니다.',
    '2023~2026년은 반복 사용된 개발 평가입니다. 독립 블라인드라고 부르지 않습니다. 2026-11-05 이후 미사용 상태 관측부터 Lockbox 대상으로 예약했습니다. 아직 새 데이터 수집이나 Lockbox 평가를 완료한 것은 아닙니다. 5거래일 정답이 완성되고 도착/수정 시각이 기록된 자료만 별도 보관해야 합니다.','',
    '## 채택 판단','',
    '외삽에 대한 역할 분리와 종목별 계수 공유는 구현됐습니다. 0 기준선 대비 평균 오차 개선도 확인됐습니다. 그러나 기존 CatBoost 대비 중심값 개선의 불확실성과 급락 악화가 남아 새 하이브리드를 정식 손실 추정 모델로 교체하지 않습니다. 팩터 기여도와 지원 범위 표시는 연구용 설명 기능 후보입니다.',
    '실제 사용자가 입력한 충격에는 관측 정답이 없을 수 있습니다. 역사적 반응 재구성 성능, 시나리오 계산 일관성, 극단 외삽 신뢰성을 구분합니다. 포트폴리오 금액은 종목별 계산 수익률과 보유 평가금액을 곱해 더했습니다. 종목별 분위수를 합쳐 포트폴리오 확률 구간으로 표시하지 않았습니다.','',
    '## 파일과 재현','',
    '- center_metrics.csv: 여섯 모델 중심값 비교',
    '- interval_metrics.csv: 다섯 보정 방식과 두 기준선 비교',
    '- center_by_asset.csv / interval_by_asset.csv: 20종목 각각의 결과',
    '- center_by_sector.csv / center_by_fold.csv / center_by_regime.csv: 그룹, 연도, 변동성별 결과',
    '- center_date_block_ci.csv / risk_date_block_ci.csv: 날짜 블록 불확실성',
    '- factor_attribution_example.csv / service_example.csv / portfolio_example.csv: 사용자 시나리오 계산 근거',
    '- state_only_search_example.csv: 충격을 넣지 않은 과거 시장 검색',
    '- verification.json / scenario_verification.json: 계산 및 시간 경계 확인',
    '- legacy_reproduction.json: 외부 검토 수치 재현',
    '- lockbox.json: 미사용 데이터 평가 규칙과 파일 해시','',
    '기존 연구 루트의 exports/seongjin_gold_v1_1/gold_stress_daily.parquet와 reports/four_models_gold_20261104, reports/gold20_locked_20261104가 필요합니다. 원자료와 학습 모델 캐시는 공개 저장소에 포함하지 않았습니다. 코드 실행 시 STRESSLAB_AUDIT_ROOT를 해당 루트로 설정합니다. Python과 라이브러리 버전은 environment.json을 참고하세요.','',
    '실행 순서: run_pooled_hybrid_20261104.py → report_pooled_hybrid_20261104.py → verify_pooled_scenario_20261104.py → document_pooled_hybrid_20261104.py. 같은 폴더의 완료 체크포인트는 재사용하므로 다른 실험 설정은 새 버전 폴더에서 실행해야 합니다.','',
    '방법 참고: [Ridge](https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.Ridge.html), [Corsi HAR 논문](https://doi.org/10.1093/jjfinec/nbp001).']
    (OUT/'README.md').write_text('\n'.join(lines)+'\n',encoding='utf8')
    versions={k:importlib.metadata.version(k) for k in ['numpy','pandas','scikit-learn','catboost','lightgbm','xgboost','pyarrow','joblib','threadpoolctl']}
    (OUT/'environment.json').write_text(json.dumps(dict(python=platform.python_version(),libraries=versions),indent=2));(OUT/'requirements.txt').write_text('\n'.join(f'{k}=={v}' for k,v in versions.items())+'\n')
    files=['pooled_stress_core_20261104.py','run_pooled_hybrid_20261104.py','report_pooled_hybrid_20261104.py','verify_pooled_scenario_20261104.py','document_pooled_hybrid_20261104.py']
    lock=json.loads((OUT/'lockbox.json').read_text());lock.update(frozen_at=datetime.now(timezone.utc).isoformat(),source_hashes={f:hashlib.sha256((ROOT/'scripts'/f).read_bytes()).hexdigest() for f in files},protocol_hash=hashlib.sha256((OUT/'protocol.json').read_bytes()).hexdigest(),development_selection=sel)
    (OUT/'lockbox.json').write_text(json.dumps(lock,indent=2));(OUT/'progress.json').write_text(json.dumps(dict(stage='complete',production_promoted=False)))
    print('Report and reproducibility manifest saved.')

if __name__=='__main__':main()
