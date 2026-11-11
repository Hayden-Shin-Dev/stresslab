"""모델 D / E 비교 그래프 6종. compare_models.py 실행 뒤에 인자 없이 실행합니다.

    python analytics/model_de/plot_de.py   ->  analytics/outputs/model_de/plots/*.png
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib import font_manager  # noqa: E402

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import common as C  # noqa: E402

SRC = C.OUT
OUT = SRC / 'plots'
SURFACE, INK, INK2, GRID = '#fcfcfb', '#0b0b0b', '#52514e', '#e4e3df'
COL = {'Model D': '#2a78d6', 'Model E': '#eb6834'}
LABEL = {'Model D': 'D  Ridge+LightGBM+Conformal', 'Model E': 'E  CatBoost 분위수+CQR'}
H_LABEL = {1: '1일', 5: '5일', 20: '20일'}
REGIME_ORDER = ['all', 'normal', 'rate_up', 'rate_down', 'fx_up', 'fx_down', 'rate_and_fx_both_large', 'extreme_any_shock']
REGIME_KO = {'all': '전체', 'normal': '평상시', 'rate_up': '금리 급등', 'rate_down': '금리 급락', 'fx_up': '환율 급등', 'fx_down': '환율 급락',
             'rate_and_fx_both_large': '금리·환율 동시', 'extreme_any_shock': '극단 충격'}

_have = {f.name for f in font_manager.fontManager.ttflist}
_FONTS = [f for f in ['Malgun Gothic', 'AppleGothic', 'NanumGothic', 'Noto Sans CJK KR', 'Noto Sans CJK SC'] if f in _have] or ['DejaVu Sans']
plt.rcParams.update({'font.family': _FONTS, 'axes.unicode_minus': False, 'figure.facecolor': SURFACE, 'axes.facecolor': SURFACE,
                     'savefig.facecolor': SURFACE, 'axes.edgecolor': GRID, 'axes.labelcolor': INK2, 'xtick.color': INK2,
                     'ytick.color': INK2, 'text.color': INK, 'axes.spines.top': False, 'axes.spines.right': False,
                     'axes.grid': True, 'grid.color': GRID, 'grid.linewidth': 0.8, 'axes.axisbelow': True, 'font.size': 10})


def load():
    d = C.read_table(SRC / 'model_d_predictions.parquet')
    e = C.read_table(SRC / 'model_e_predictions.parquet')
    for df in (d, e):
        df['trading_date'] = pd.to_datetime(df['trading_date'])
    cov = pd.read_csv(SRC / 'coverage_analysis.csv', dtype={'group': str})
    comp = pd.read_csv(SRC / 'model_comparison.csv')
    info = json.loads((SRC / 'run_info.json').read_text(encoding='utf-8'))
    return d, e, cov, comp, info


def stand_in_note(info) -> str:
    b = {v.get('backend_gbm', v.get('backend')) for v in info['models'].values()}
    if b & {'sklearn_hist_gradient_boosting', 'sklearn_hist_gradient_boosting_quantile'}:
        return '  ※ LightGBM/CatBoost 대신 scikit-learn 대체 모델로 계산한 임시 결과(최종 수치 아님)'
    return ''


def head(fig, main, sub):
    fig.text(0.01, 0.985, main, fontsize=14, fontweight='bold', va='top')
    fig.text(0.01, 0.945, sub, fontsize=9.5, color=INK2, va='top')


def save(fig, name):
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / name
    fig.savefig(p, dpi=150)
    plt.close(fig)
    return str(p)


def one_asset(d, e, h, asset=None):
    dd, ee = d[d['horizon'] == h], e[e['horizon'] == h]
    if asset is None:
        asset = '005930' if '005930' in set(dd['asset_id']) else dd['asset_id'].value_counts().index[0]
    return asset, dd[dd['asset_id'] == asset].sort_values('trading_date'), ee[ee['asset_id'] == asset].sort_values('trading_date')


# 1. 실제 수익률 vs 중심 예측
def fig_actual_vs_center(d, e, comp, info):
    fig, axes = plt.subplots(2, 3, figsize=(13, 8.2))
    for j, h in enumerate(C.HORIZONS):
        for i, (nm, df) in enumerate((('Model D', d), ('Model E', e))):
            ax, p = axes[i, j], df[df['horizon'] == h]
            lim = float(np.percentile(np.abs(p['y_actual']), 99))
            ax.scatter(p['center'].clip(-lim, lim), p['y_actual'].clip(-lim, lim), s=3, alpha=0.18, color=COL[nm], linewidths=0)
            ax.plot([-lim, lim], [-lim, lim], color=INK2, lw=1, ls=(0, (4, 3)))
            ax.axhline(0, color=GRID, lw=1); ax.axvline(0, color=GRID, lw=1)
            r = comp[(comp.model == nm) & (comp.horizon == h) & comp.is_primary].iloc[0]
            ax.set_title(f'{LABEL[nm]} · {H_LABEL[h]}', loc='left', fontsize=10)
            ax.text(0.02, 0.97, f'MAE {r.mae:.3f}  R² {r.r2:.3f}\n방향 {r.directional_accuracy:.1%}', transform=ax.transAxes, va='top', fontsize=9, color=INK2)
            ax.set_xlim(-lim, lim); ax.set_ylim(-lim, lim)
            ax.set_xlabel('중심 예측 (로그수익률 %)' if i == 1 else ''); ax.set_ylabel('실제 (%)' if j == 0 else '')
    head(fig, '실제 수익률과 중심 예측값', '점선 = 완전 일치. 각 점 = 한 날짜·한 종목(시험 구간 2023~). 표시 범위는 |실제| 99% 분위로 제한.' + stand_in_note(info))
    fig.tight_layout(rect=(0, 0, 1, 0.92))
    return save(fig, '1_actual_vs_center.png')


# 2. 예측구간 시각화 (한 종목, 최근 구간, 90%)
def fig_interval_zoom(d, e, info, n_last=150):
    fig, axes = plt.subplots(3, 1, figsize=(12, 10), sharex=False)
    for ax, h in zip(axes, C.HORIZONS):
        asset, dd, ee = one_asset(d, e, h)
        dd, ee = dd.tail(n_last), ee.tail(n_last)
        ax.fill_between(dd['trading_date'], dd['lo_sym_90'], dd['hi_sym_90'], color=COL['Model D'], alpha=0.18, lw=0, label='D 90% 구간')
        ax.fill_between(ee['trading_date'], ee['lo_cqr_90'], ee['hi_cqr_90'], color=COL['Model E'], alpha=0.18, lw=0, label='E 90% 구간(CQR)')
        ax.plot(dd['trading_date'], dd['center'], color=COL['Model D'], lw=1.2, label='D 중심')
        ax.plot(ee['trading_date'], ee['center'], color=COL['Model E'], lw=1.2, label='E 중심(Q50)')
        ax.scatter(dd['trading_date'], dd['y_actual'], s=9, color=INK, zorder=3, label='실제')
        ax.axhline(0, color=GRID)
        ax.set_title(f'{H_LABEL[h]} 예측 · 종목 {asset} · 최근 {len(dd)}개 표본일', loc='left', fontsize=10.5)
        ax.set_ylabel('로그수익률 (%)')
        if h == 1:
            ax.legend(ncol=5, loc='upper left', fontsize=8.5, frameon=False)
    head(fig, '예측구간과 실제 수익률 (90%)', '한 종목의 최근 시험 구간. 5일/20일은 인접 표본의 정답이 겹쳐 점이 이어져 보입니다.' + stand_in_note(info))
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    return save(fig, '2_intervals_zoom.png')


# 3. 포함률 비교
def fig_coverage(cov, info):
    t = cov[(cov.group_type == 'regime') & (cov.group == 'all') & cov.is_primary]
    fig, axes = plt.subplots(1, 3, figsize=(13, 4.8), sharey=True)
    xs = np.arange(3)
    for ax, h in zip(axes, C.HORIZONS):
        for k, nm in enumerate(('Model D', 'Model E')):
            r = t[(t.model == nm) & (t.horizon == h)].sort_values('target_coverage')
            x = xs + (k - 0.5) * 0.34
            ax.bar(x, r['coverage'], width=0.32, color=COL[nm], label=LABEL[nm])
            ax.errorbar(x, r['coverage'], yerr=[r['coverage'] - r['coverage_ci_lo'], r['coverage_ci_hi'] - r['coverage']], fmt='none', ecolor=INK2, capsize=3, lw=1)
            for xi, v in zip(x, r['coverage']):
                ax.text(xi, 0.705, f'{v:.1%}', ha='center', fontsize=8, color='white', rotation=90, va='bottom')
        for xi, L in zip(xs, (0.80, 0.90, 0.95)):
            ax.hlines(L, xi - 0.42, xi + 0.42, color=INK, lw=1.6)
        ax.set_xticks(xs); ax.set_xticklabels(['80%', '90%', '95%']); ax.set_ylim(0.70, 1.0)
        ax.set_title(f'{H_LABEL[h]} 예측', loc='left'); ax.set_xlabel('목표 Coverage'); ax.grid(axis='x', visible=False)
    axes[0].set_ylabel('시험 구간 실제 포함률')
    axes[0].legend(loc='upper left', fontsize=8.5, frameon=False)
    head(fig, '목표 Coverage 대비 실제 포함률', '검은 선 = 목표, 막대 끝 선 = 95% 블록 부트스트랩 구간(겹치는 정답 구간 고려).' + stand_in_note(info))
    fig.tight_layout(rect=(0, 0, 1, 0.9))
    return save(fig, '3_coverage_comparison.png')


# 4. 평균 구간 너비
def fig_width(comp, info):
    t = comp[comp.is_primary]
    fig, axes = plt.subplots(1, 3, figsize=(13, 4.6))
    xs = np.arange(3)
    for ax, h in zip(axes, C.HORIZONS):
        for k, nm in enumerate(('Model D', 'Model E')):
            r = t[(t.model == nm) & (t.horizon == h)].iloc[0]
            v = [r.mean_width_80, r.mean_width_90, r.mean_width_95]
            x = xs + (k - 0.5) * 0.34
            ax.bar(x, v, width=0.32, color=COL[nm], label=LABEL[nm])
            for xi, vv in zip(x, v):
                ax.text(xi, vv, f'{vv:.1f}', ha='center', va='bottom', fontsize=8.5, color=INK2)
        ax.set_xticks(xs); ax.set_xticklabels(['80%', '90%', '95%']); ax.set_title(f'{H_LABEL[h]} 예측', loc='left')
        ax.set_xlabel('목표 Coverage'); ax.set_ylabel('평균 구간 너비 (%p)' if h == 1 else ''); ax.grid(axis='x', visible=False)
    axes[0].legend(loc='upper left', fontsize=8.5, frameon=False)
    head(fig, '평균 예측구간 너비', '같은 목표 Coverage에서 좁을수록 유리하지만, 실제 포함률이 목표에 못 미치면 비교할 수 없습니다(그래프 3 참고).' + stand_in_note(info))
    fig.tight_layout(rect=(0, 0, 1, 0.9))
    return save(fig, '4_mean_width_comparison.png')


# 5. 시장충격 유형별 포함률 (90%)
def fig_regime(cov, info):
    t = cov[(cov.group_type == 'regime') & cov.is_primary & (cov.target_coverage == 0.90)]
    fig, axes = plt.subplots(1, 3, figsize=(13.5, 5), sharey=True)
    ys = np.arange(len(REGIME_ORDER))[::-1]
    for ax, h in zip(axes, C.HORIZONS):
        ax.axvline(0.90, color=INK, lw=1.4)
        for nm, off in (('Model D', 0.14), ('Model E', -0.14)):
            r = t[(t.model == nm) & (t.horizon == h)].set_index('group').reindex(REGIME_ORDER)
            ax.scatter(r['coverage'], ys + off, s=44, color=COL[nm], label=LABEL[nm], zorder=3)
        n = t[(t.model == 'Model D') & (t.horizon == h)].set_index('group').reindex(REGIME_ORDER)
        for y_, g in zip(ys, REGIME_ORDER):
            ax.text(1.0, y_, f'n={int(n.loc[g, "n"]):,} / 블록 {int(n.loc[g, "independent_blocks"])}', fontsize=7.5, color=INK2, va='center', ha='left')
        ax.set_xlim(0.78, 1.0); ax.set_yticks(ys); ax.set_yticklabels([REGIME_KO[g] for g in REGIME_ORDER])
        ax.set_title(f'{H_LABEL[h]} 예측', loc='left'); ax.set_xlabel('90% 구간 실제 포함률'); ax.grid(axis='y', visible=False)
    h_, l_ = axes[0].get_legend_handles_labels()
    fig.legend(h_, l_, loc='lower center', ncol=2, fontsize=8.5, frameon=False, bbox_to_anchor=(0.45, 0.0))
    head(fig, '시장충격 유형별 포함률 (목표 90%)', '유형 기준은 학습 구간 충격 분포. 블록 수가 적은 유형은 우연히 흔들리므로 숫자를 단정하지 마세요.' + stand_in_note(info))
    fig.tight_layout(rect=(0, 0.05, 0.9, 0.92))
    fig.subplots_adjust(right=0.86)
    return save(fig, '5_coverage_by_shock_type.png')


# 6. 시간에 따른 구간과 실제 (전체 시험 구간)
def fig_time(d, e, info, roll=120):
    fig, axes = plt.subplots(3, 2, figsize=(14, 10), gridspec_kw={'width_ratios': [2.2, 1.6]})
    for i, h in enumerate(C.HORIZONS):
        asset, dd, ee = one_asset(d, e, h)
        ax = axes[i, 0]
        ax.fill_between(dd['trading_date'], dd['lo_sym_90'], dd['hi_sym_90'], color=COL['Model D'], alpha=0.16, lw=0)
        ax.fill_between(ee['trading_date'], ee['lo_cqr_90'], ee['hi_cqr_90'], color=COL['Model E'], alpha=0.16, lw=0)
        ax.plot(dd['trading_date'], dd['y_actual'], color=INK, lw=0.6)
        ax.set_title(f'{H_LABEL[h]} · 종목 {asset}: 90% 구간(D 파랑, E 주황)과 실제(검정)', loc='left', fontsize=10)
        ax.set_ylabel('로그수익률 (%)')
        ax = axes[i, 1]
        for nm, df, lo, hi in (('Model D', d, 'lo_sym_90', 'hi_sym_90'), ('Model E', e, 'lo_cqr_90', 'hi_cqr_90')):
            p = df[df['horizon'] == h].copy()
            p['in'] = ((p['y_actual'] >= p[lo]) & (p['y_actual'] <= p[hi])).astype(float)
            s = p.groupby('trading_date')['in'].mean().rolling(roll, min_periods=roll // 2).mean()
            ax.plot(s.index, s.values, color=COL[nm], lw=1.4, label=LABEL[nm] if i == 0 else None)
        ax.axhline(0.90, color=INK, lw=1.2)
        ax.set_ylim(0.6, 1.0)
        ax.set_title(f'{H_LABEL[h]} · 최근 {roll}개 표본일 이동 포함률(전 종목 평균)', loc='left', fontsize=10)
    axes[0, 1].legend(loc='lower left', fontsize=8, frameon=False)
    head(fig, '시간에 따른 예측구간과 실제 수익률', '왼쪽: 한 종목, 오른쪽: 전 종목 이동 포함률(검은 선 = 목표 90%).' + stand_in_note(info))
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    return save(fig, '6_intervals_over_time.png')


def main():
    d, e, cov, comp, info = load()
    paths = [fig_actual_vs_center(d, e, comp, info), fig_interval_zoom(d, e, info), fig_coverage(cov, info), fig_width(comp, info),
             fig_regime(cov, info), fig_time(d, e, info)]
    print(json.dumps(paths, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
