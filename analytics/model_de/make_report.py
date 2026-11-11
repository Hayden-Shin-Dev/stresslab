"""compare_models.py 결과(CSV/JSON)로 최종 보고서(model_report.md)를 만듭니다. 인자 없이 실행.

표의 숫자는 모두 outputs/model_de/ 의 측정값을 그대로 옮깁니다. 구조/방법 설명은 고정 문장이고,
'추천'은 아래 기준을 코드로 계산한 초안입니다. 대체 모델(scikit-learn)로 돌린 결과면 보고서 맨 위에 임시 결과임을 표시합니다.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402

H = {1: '1일', 5: '5일', 20: '20일'}


def md(df: pd.DataFrame, fmt=None) -> str:
    fmt = fmt or {}
    cols = list(df.columns)
    out = ['| ' + ' | '.join(cols) + ' |', '|' + '|'.join(['---'] * len(cols)) + '|']
    for _, r in df.iterrows():
        out.append('| ' + ' | '.join((fmt.get(c, '{}')).format(r[c]) if pd.notna(r[c]) else '' for c in cols) + ' |')
    return '\n'.join(out)


def verdict(comp, cov, paired) -> tuple[str, list]:
    """기준: 목표 근접(|coverage-목표| 평균), 같은 포함률에서 폭, MAE/RMSE, 충격 커질 때 안정성, 속도."""
    p = comp[comp.is_primary]
    rows, score = [], {'Model D': 0, 'Model E': 0}
    for h in C.HORIZONS:
        d, e = (p[(p.model == m) & (p.horizon == h)].iloc[0] for m in ('Model D', 'Model E'))
        gap = lambda r: sum(abs(r[f'coverage_gap_{C.lv(L)}']) for L in C.LEVELS) / 3
        isc = lambda r: sum(r[f'interval_score_{C.lv(L)}'] for L in C.LEVELS) / 3
        ext = cov[(cov.group_type == 'regime') & (cov.group == 'extreme_any_shock') & cov.is_primary & (cov.horizon == h) & (cov.target_coverage == 0.90)]
        eg = {m: abs(ext[ext.model == m]['coverage_gap'].iloc[0]) for m in ('Model D', 'Model E')}
        checks = [('목표 Coverage 근접(평균 절대차)', gap(d), gap(e)), ('Interval Score(평균)', isc(d), isc(e)),
                  ('MAE', d.mae, e.mae), ('RMSE', d.rmse, e.rmse), ('극단 충격 구간 90% 포함률 차이', eg['Model D'], eg['Model E']),
                  ('추론 시간(ms/행)', d.inference_ms_per_row, e.inference_ms_per_row)]
        for nm, a, b in checks:
            win = 'Model D' if a < b else 'Model E'
            score[win] += 1
            rows.append({'기간': H[h], '기준': nm, 'Model D': a, 'Model E': b, '우위': win})
    top = '무승부' if score['Model D'] == score['Model E'] else max(score, key=score.get)
    return top, rows, score


def main():
    comp = pd.read_csv(C.OUT / 'model_comparison.csv')
    cov = pd.read_csv(C.OUT / 'coverage_analysis.csv', dtype={'group': str})
    paired = pd.read_csv(C.OUT / 'paired_differences.csv')
    scn = pd.read_csv(C.OUT / 'scenario_comparison.csv', dtype={'asset_id': str})
    info = json.loads((C.OUT / 'run_info.json').read_text(encoding='utf-8'))
    backs = {v.get('backend_gbm', v.get('backend')) for v in info['models'].values()}
    temp = bool(backs & {'sklearn_hist_gradient_boosting', 'sklearn_hist_gradient_boosting_quantile'})
    p = comp[comp.is_primary].sort_values(['horizon', 'model'])
    top, vrows, score = verdict(comp, cov, paired)
    L = []
    L.append('# 모델 D vs 모델 E 비교 보고서 (종목별 로그수익률 1/5/20일)\n')
    if temp:
        L.append('> **임시 결과**: 이 실행은 LightGBM/CatBoost가 없어 scikit-learn 대체 모델(HistGradientBoosting)로 계산했습니다. '
                 '구조와 절차는 최종과 같지만 수치는 최종이 아닙니다. `.venv`에서 `pip install lightgbm catboost` 후 compare_models.py를 다시 실행하고 이 보고서를 다시 만드세요.\n')
    L.append(f'백엔드: {sorted(backs)} · 시드 {info["seed"]} · 시험 구간은 이전 실험에서 이미 본 적이 있어 완전한 blind가 아닙니다.\n')
    L.append('## 1. 구조적 차이\n')
    L.append('- **모델 D**: 중심값을 종목별 Ridge와 전 종목 GBM의 가중 평균으로 냅니다. 구간은 보정 구간 잔차 크기(종목 변동성으로 정규화)의 '
             '유한 표본 split-conformal 분위수 × 그날 종목 변동성 척도입니다. 구간 폭은 **입력 충격과 무관**하고 변동성 척도에만 비례합니다(대칭).\n'
             '- **모델 E**: 분위수 2.5/5/10/50/90/95/97.5%를 각각 학습해 Q50을 중심값, 분위수 쌍을 구간으로 씁니다. 그 위에 CQR로 구간을 늘리거나 줄입니다. '
             '구간 폭과 비대칭이 **입력(충격·상태)에 따라 달라질 수 있습니다**.\n'
             '- 두 방식 모두 평균/표준편차 방식이 아니라 보정 자료의 순위 기반 분위수를 씁니다. 겹치는 5/20일 정답 때문에 교환 가능성 보장은 정확히 성립하지 않아 실제 포함률을 시험 구간에서 측정했습니다.\n')
    L.append('## 2. 학습 및 검증 방법\n')
    s5 = info['splits']['5']
    L.append(f'- 분리(기존 프로젝트 설정 유지): 학습 {s5["train_period"][0]}~{s5["train_period"][1]}, 보정 {s5["cal_period"][0]}~{s5["cal_period"][1]}, 시험 {s5["test_period"][0]}~. '
             '정답 종료일이 다음 구간에 걸치는 행은 제외(purging): ' + ', '.join(f'{H[int(h)]} {v["purged_rows"]}행' for h, v in info['splits'].items()) + '.')
    L.append('- 예측 대상은 종목별 y(h)=100·ln(종가[t+h]/종가[t])이며 1/5/20일을 각각 따로 학습·보정합니다(kospi_d* 열은 만들지 않았습니다).')
    L.append('- 입력은 기존 10개(충격 4 + 상태 6)이며 기존 전처리/특성(features.py)을 그대로 사용합니다. 충격은 t→t+h 변화, 상태는 t까지 정보입니다.')
    L.append('- D의 Ridge 비중(0.3/0.5/0.7)은 학습 구간 안 연도별 롤링 검증에서만 고릅니다. 보정/시험 구간은 선택에 쓰지 않습니다. 선택 결과: ' +
             ', '.join(f'{H[int(h)]} {info["models"][f"D_h{h}"]["blend_selection"]["chosen_ridge_weight"]}' for h in info['splits']) + '.')
    L.append('- E의 하이퍼파라미터는 고정값이며(튜닝 없음) 보정 구간을 쓰지 않았습니다. 롤링 보정은 최근 250거래일 중 정답이 이미 실현된 행만 씁니다.\n')
    L.append('## 3. 중심 예측 정확도 (시험 구간, 로그수익률 %)\n')
    L.append(md(p[['model', 'horizon', 'mae', 'rmse', 'r2', 'directional_accuracy']].rename(columns={'horizon': '기간', 'directional_accuracy': '방향 적중률'}),
                {'mae': '{:.3f}', 'rmse': '{:.3f}', 'r2': '{:.3f}', '방향 적중률': '{:.1%}'}))
    L.append('\nD-E 쌍대 차이(블록 부트스트랩 95%, 90% 구간 기준)에서 MAE 차이가 0을 포함하는지는 `paired_differences.csv`에 있습니다. '
             'R²가 0에 가깝거나 음수인 것은 일별 수익률의 예측 가능성이 원래 낮다는 뜻이며 두 모델 모두 같습니다.\n')
    L.append('## 4. 예측구간 신뢰도\n')
    t = p[['model', 'horizon'] + [f'coverage_{C.lv(l)}' for l in C.LEVELS] + [f'mean_width_{C.lv(l)}' for l in C.LEVELS]].rename(columns={'horizon': '기간'})
    L.append(md(t, {c: '{:.1%}' for c in t.columns if c.startswith('coverage')} | {c: '{:.2f}' for c in t.columns if c.startswith('mean_width')}))
    ba = cov[(cov.group_type == 'conformal_before_after') & (cov.target_coverage == 0.90) & cov.variant.isin(['raw', 'cqr'])]
    L.append('\n**모델 E: Conformal 보정 전/후 (목표 90%)**\n')
    L.append(md(ba[['horizon', 'group', 'coverage', 'mean_width']].rename(columns={'horizon': '기간', 'group': '구분'}), {'coverage': '{:.1%}', 'mean_width': '{:.2f}'}))
    cr = [(h, info['models'][f'E_h{h}']['quantile_crossing']['test']['rows_with_any_crossing']) for h in info['splits']]
    L.append('\n분위수 역전(quantile crossing) 비율(시험): ' + ', '.join(f'{H[int(h)]} {v:.2%}' for h, v in cr) + ' → 정렬해서 사용.\n')
    asy = cov[(cov.group_type == 'asymmetry') & (cov.target_coverage == 0.90) & cov.variant.isin(['sym', 'cqr'])]
    L.append('**비대칭 분석 (90%: 목표 꼬리 각 5%)**\n')
    L.append(md(asy[['model', 'horizon', 'miss_below', 'miss_above', 'up_over_down_ratio']].rename(columns={'horizon': '기간', 'miss_below': '아래로 이탈', 'miss_above': '위로 이탈', 'up_over_down_ratio': '위폭/아래폭'}),
                {'아래로 이탈': '{:.1%}', '위로 이탈': '{:.1%}', '위폭/아래폭': '{:.3f}'}))
    L.append('\n모델 D 기본(sym)은 구조상 대칭입니다. 위/아래 이탈률이 다르면 수익률 분포가 비대칭(하락 꼬리/상승 꼬리)이라는 신호이며, D의 asym 변형과 E가 이를 어느 정도 반영하는지는 `coverage_analysis.csv`의 `asym`/`cqr` 행을 보세요.\n')
    rl = cov[(cov.group_type == 'regime') & (cov.group == 'all') & (cov.target_coverage == 0.90) & cov.variant.isin(['sym', 'cqr', 'roll', 'cqr_roll', 'asset', 'asym'])]
    L.append('**롤링 보정 및 변형 (90%, 전체 포함률)**\n')
    L.append(md(rl[['model', 'variant', 'horizon', 'coverage', 'mean_width']].rename(columns={'horizon': '기간'}), {'coverage': '{:.1%}', 'mean_width': '{:.2f}'}))
    L.append('\n## 5. 시장충격 유형별 (90% 구간 포함률)\n')
    rg = cov[(cov.group_type == 'regime') & cov.is_primary & (cov.target_coverage == 0.90)]
    pv = rg.pivot_table(index=['horizon', 'group'], columns='model', values=['coverage', 'independent_blocks']).reset_index()
    pv.columns = ['기간', '유형', '블록수D', '블록수E', 'D 포함률', 'E 포함률']
    pv['유형'] = pv['유형'].map(lambda g: {'all': '전체', 'normal': '평상시', 'rate_up': '금리 급등', 'rate_down': '금리 급락', 'fx_up': '환율 급등', 'fx_down': '환율 급락',
                                         'rate_and_fx_both_large': '금리·환율 동시', 'extreme_any_shock': '극단 충격'}.get(g, g))
    L.append(md(pv[['기간', '유형', 'D 포함률', 'E 포함률', '블록수D']].rename(columns={'블록수D': '독립 블록수'}), {'D 포함률': '{:.1%}', 'E 포함률': '{:.1%}', '독립 블록수': '{:.0f}'}))
    L.append('\n유형 기준: ' + C.REGIME_NOTE + '. 독립 블록 수가 작은 유형(특히 20일)은 숫자 차이를 단정할 수 없습니다.\n')
    L.append('## 6. 계산 비용 및 추론 속도\n')
    L.append(md(p[['model', 'horizon', 'train_seconds', 'inference_ms_per_row', 'calibration_seconds']].rename(columns={'horizon': '기간', 'train_seconds': '학습(초)', 'inference_ms_per_row': '추론(ms/행)', 'calibration_seconds': '보정(초)'}),
                {'학습(초)': '{:.2f}', '추론(ms/행)': '{:.4f}', '보정(초)': '{:.3f}'}))
    L.append('\n시간은 이 실행 환경의 측정값이며 대체 모델 기준이면 실제 LightGBM/CatBoost와 다릅니다. E는 분위수 7개를 각각 학습·예측하므로 D보다 학습/추론 비용이 큽니다(분위수 수에 비례).\n')
    L.append('## 7. 가상 시장충격 입력 테스트\n')
    a = scn[scn.asset_id.str.startswith('ALL') & (scn.target_coverage == 0.90) & (scn.horizon == 5)]
    L.append('5일, 90%, 전 종목 평균(종목별 값은 `scenario_comparison.csv`):\n')
    L.append(md(a[['scenario', 'model', 'center_pct', 'lower_pct', 'upper_pct', 'width_pct', 'range_status']].rename(columns={'scenario': '시나리오', 'model': '모델', 'center_pct': '중심', 'lower_pct': '하한', 'upper_pct': '상한', 'width_pct': '폭', 'range_status': '범위'}),
                {'중심': '{:.2f}', '하한': '{:.2f}', '상한': '{:.2f}', '폭': '{:.2f}'}))
    wd = a.groupby('모델' if False else 'model')['width_pct'].agg(['min', 'max'])
    L.append('\n- 모델별 폭 범위(시나리오 간): ' + ', '.join(f'{m} {r["min"]:.1f}~{r["max"]:.1f}' for m, r in wd.iterrows()) + '. 모델 D는 충격이 커져도 폭이 변하지 않는 구조이고, E는 충격에 따라 폭이 달라집니다.')
    L.append('- OUT_OF_RANGE/RARE 표시는 학습 구간 충격의 최소·최대 / 1%·99% 기준입니다. 외삽 구간에서는 어느 모델도 신뢰하기 어렵습니다.')
    L.append('- ' + info['scenario_note'] + '\n')
    L.append('## 8. 추천 초안 (기준별 비교)\n')
    L.append(md(pd.DataFrame(vrows), {'Model D': '{:.4f}', 'Model E': '{:.4f}'}))
    L.append(f'\n기준 승수: D {score["Model D"]}, E {score["Model E"]}. 점수 합산은 참고용이며 아래 사실을 우선해서 판단하세요.')
    L.append('- 포함률이 목표에 가까운 쪽, 같은 포함률에서 폭이 좁은 쪽, 극단 충격에서 포함률이 덜 무너지는 쪽, 충격 입력에 반응하는 폭을 주는 쪽을 우선합니다.')
    L.append('- 서비스 관점: 사용자가 가상 충격을 바꿔 보는 기능이므로 **충격에 따라 구간이 반응하는지**가 중요합니다. D의 구간은 충격에 반응하지 않습니다.')
    L.append((f'- 이 실행의 초안 결론: 기준 승수가 같아 **우열을 가리지 못했습니다**. 위 사실(충격 반응성 등)을 보고 판단하세요.' if top == '무승부' else f'- 이 실행의 초안 결론: **{top}** 쪽이 기준 {score[top]}개에서 우위입니다.') + (' (임시 결과이므로 실제 라이브러리 실행 후 다시 판단)' if temp else '') + '\n')
    L.append('## 9. 한계와 개선 방향\n')
    L.append('- 시험 구간(2023~)은 이전 실험에서 이미 확인했으므로 blind 시험이 아닙니다. 새로운 기간이 쌓이면 다시 평가해야 합니다.\n'
             '- 모델링 종목 18개(전체 KOSPI 아님). 결과를 KOSPI 전체로 일반화할 수 없습니다.\n'
             '- 5/20일 표본은 정답 구간이 겹쳐 독립 표본 수가 작습니다(20일 시험 약 47 블록). 포함률 차이의 통계적 의미는 부트스트랩 구간으로 판단하세요.\n'
             '- 포함률은 평균 보장이며 시장 상황별 조건부 보장이 아닙니다. 변동성 급변기에는 이동 포함률이 목표 아래로 내려갈 수 있습니다(그래프 6).\n'
             '- 개선: 변동성 수준별(Mondrian) 보정, 적응형 conformal(ACI), E의 하이퍼파라미터를 학습 구간 롤링 검증으로 튜닝, 종목 효과 반영.\n')
    path = C.OUT / 'model_report.md'
    path.write_text('\n'.join(L), encoding='utf-8')
    print('저장:', path)
    return 0


if __name__ == '__main__':
    sys.exit(main())
