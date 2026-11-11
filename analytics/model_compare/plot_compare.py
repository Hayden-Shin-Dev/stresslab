"""compare_models.py 결과를 그래프로 비교합니다.

    python analytics/model_compare/plot_compare.py        # VS Code ▶ 실행, 인자 없음 (먼저 compare_models.py 실행)
    -> analytics/outputs/model_compare/plots/*.png

01_mae_overview.png      모델별 MAE (롤링 / 2023~ 평가)
02_diff_vs_ridge10.png   현재 모델(10개 Ridge) 대비 MAE 차이와 95% 신뢰구간
03_features_vs_model.png 특징 개수(10/14/21) x 모델 종류, 아래는 Ridge에 특징 묶음을 하나씩 더한 진단
04_by_year.png           연도별 MAE
05_interval_quality.png  90% 구간의 포함률과 폭, 구간 점수
06_by_asset.png          종목별 MAE 변화(2023~)
색: 회색=변동성 기준선, 파랑=Ridge, 주황=GBM, 초록=결합. 선택/강조는 색이 아니라 위치와 라벨로도 구분합니다.
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

HERE = Path(__file__).resolve().parent
ANALYTICS_ROOT = HERE.parent
SRC = ANALYTICS_ROOT / 'outputs/model_compare'
OUT = SRC / 'plots'

SURFACE, INK, INK2, GRID = '#fcfcfb', '#0b0b0b', '#52514e', '#e4e3df'
FAMILY_COLOR = {'baseline': '#8a8984', 'ridge': '#2a78d6', 'gbm': '#eb6834', 'blend': '#1baf7a'}
REF = 'F10:ridge'
from matplotlib import font_manager  # noqa: E402

_have = {f.name for f in font_manager.fontManager.ttflist}
_FONTS = [f for f in ['Malgun Gothic', 'AppleGothic', 'NanumGothic', 'Noto Sans CJK KR', 'Noto Sans CJK SC'] if f in _have] or ['DejaVu Sans']
plt.rcParams.update({
    'font.family': _FONTS,
    'axes.unicode_minus': False, 'figure.facecolor': SURFACE, 'axes.facecolor': SURFACE, 'savefig.facecolor': SURFACE,
    'axes.edgecolor': GRID, 'axes.labelcolor': INK2, 'xtick.color': INK2, 'ytick.color': INK2, 'text.color': INK,
    'axes.spines.top': False, 'axes.spines.right': False, 'axes.grid': True, 'grid.color': GRID, 'grid.linewidth': 0.8,
    'axes.axisbelow': True, 'font.size': 10,
})


def family(m: str) -> str:
    if m.startswith('baseline'):
        return 'baseline'
    kind = m.split(':')[1]
    return 'blend' if kind.startswith('blend') else kind


def label(m: str) -> str:
    if m.startswith('baseline'):
        return '변동성 기준선'
    fs, kind = m.split(':')
    fs_name = {'F10': '10개', 'F14': '14개', 'F21': '21개', 'F10+M': '10개+시장모멘텀', 'F10+A': '10개+종목상태', 'F10+I': '10개+충격×베타'}[fs]
    k = {'ridge': 'Ridge', 'gbm': 'GBM', 'blend_w30': '결합(Ridge30%)', 'blend_w50': '결합(Ridge50%)'}[kind]
    return f'{fs_name} {k}' + (' (현재)' if m == REF else '')


def read(name):
    p = SRC / f'{name}.csv'
    if not p.exists():
        raise SystemExit(f'{p} 가 없습니다. 먼저 compare_models.py 를 실행하세요.')
    return pd.read_csv(p, encoding='utf-8-sig', dtype={'asset_id': str})


def legend_handles():
    from matplotlib.lines import Line2D
    names = {'baseline': '변동성 기준선', 'ridge': 'Ridge(종목별)', 'gbm': 'GBM(전 종목 합침)', 'blend': '결합'}
    return [Line2D([0], [0], marker='o', color='none', markerfacecolor=c, markeredgecolor=SURFACE, markersize=9, label=names[k])
            for k, c in FAMILY_COLOR.items()]


def title(fig, main, sub):
    fig.text(0.01, 0.985, main, fontsize=14, fontweight='bold', va='top')
    fig.text(0.01, 0.945, sub, fontsize=10, color=INK2, va='top')


def save_to(fig, out_dir, name):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / name
    fig.savefig(p, dpi=150)
    plt.close(fig)
    return str(p)


def save(fig, name):
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / name
    fig.savefig(p, dpi=150)
    plt.close(fig)
    return str(p)


# ---------------------------------------------------------------- 1. 개요
def dot_panel(ax, t, col, sub_title, fmt='{:.3f}', main=None):
    t = t.sort_values(col, ascending=False).reset_index(drop=True)          # 위가 가장 좋음
    for i, r in t.iterrows():
        f = family(r['model'])
        ax.plot([t[col].min() - 0.0, r[col]], [i, i], color=FAMILY_COLOR[f], lw=1.5, alpha=0.35, solid_capstyle='round')
        ax.scatter(r[col], i, s=70, color=FAMILY_COLOR[f], edgecolor=SURFACE, linewidth=1.5, zorder=3)
        ax.text(r[col], i + 0.0, '  ' + fmt.format(r[col]), va='center', ha='left', fontsize=8.5, color=INK2)
    ax.set_yticks(range(len(t)))
    ax.set_yticklabels([label(m) for m in t['model']], fontsize=9)
    for tl, m in zip(ax.get_yticklabels(), t['model']):
        if m == REF:
            tl.set_fontweight('bold')
    if REF in set(t['model']):
        ax.axvline(float(t.loc[t.model == REF, col].iloc[0]), color=INK2, lw=1, ls=(0, (4, 3)))
    ax.set_title(sub_title, loc='left', fontsize=10.5, color=INK)
    ax.grid(axis='y', visible=False)
    lo, hi = t[col].min(), t[col].max()
    ax.set_xlim(lo - (hi - lo) * 0.15, hi + (hi - lo) * 0.25)


def plot_overview():
    r, h = read('rolling_summary'), read('holdout_summary')
    fig, axes = plt.subplots(1, 2, figsize=(14, 7.2), sharey=False)
    dot_panel(axes[0], r, 'mae_pct', '롤링 검증 2012~2022 (모델 선택 기준)')
    dot_panel(axes[1], h, 'mae_pct', '고정 분할 2023~ (참고용, 이미 한 번 사용한 구간)')
    for a in axes:
        a.set_xlabel('MAE (5일 로그수익률 %, 낮을수록 좋음)')
    fig.legend(handles=legend_handles(), loc='lower center', ncol=4, frameon=False, bbox_to_anchor=(0.5, 0.0))
    title(fig, '모델별 평균 절대 오차(MAE)', '점선 = 현재 모델(10개 Ridge). 위쪽이 더 좋은 모델입니다. 축은 0에서 시작하지 않으므로 차이는 작습니다(몇 %).')
    fig.tight_layout(rect=(0, 0.04, 1, 0.91))
    return save(fig, '01_mae_overview.png')


# ---------------------------------------------------------------- 2. 차이와 신뢰구간
def plot_diff():
    fig, axes = plt.subplots(1, 2, figsize=(14, 6.6))
    for ax, name, ttl in [(axes[0], 'rolling_paired', '롤링 2012~2022'), (axes[1], 'holdout_paired', '2023~ (참고용)')]:
        p = read(name)
        p = p[p.metric == 'mae_diff_pct'].sort_values('mean_diff', ascending=False).reset_index(drop=True)
        for i, r in p.iterrows():
            c = FAMILY_COLOR[family(r['model'])]
            ax.plot([r['ci95_low'], r['ci95_high']], [i, i], color=c, lw=2.2, solid_capstyle='round', alpha=0.8)
            ax.scatter(r['mean_diff'], i, s=60, color=c, edgecolor=SURFACE, linewidth=1.5, zorder=3)
            ax.text(max(r['ci95_high'], 0) + 0.004, i, f"{r['mean_diff']:+.3f}" + ('' if r['significant'] else '  (유의하지 않음)'), va='center', fontsize=8.5, color=INK2)
        ax.axvline(0, color=INK, lw=1.2)
        ax.set_yticks(range(len(p)))
        ax.set_yticklabels([label(m) for m in p['model']], fontsize=9)
        ax.set_xlabel('MAE 차이 (%p)  ← 현재 모델보다 좋음 | 나쁨 →')
        ax.set_title(ttl, loc='left', fontsize=10.5)
        ax.grid(axis='y', visible=False)
        lo, hi = p['ci95_low'].min(), p['ci95_high'].max()
        ax.set_xlim(lo - (hi - lo) * 0.05, hi + (hi - lo) * 0.45)
    fig.legend(handles=legend_handles(), loc='lower center', ncol=4, frameon=False, bbox_to_anchor=(0.5, 0.0))
    title(fig, '현재 모델(10개 Ridge) 대비 MAE 차이', '점 = 평균 차이, 선 = 5일 구간 묶음 부트스트랩 95% 구간. 0을 지나지 않으면 우연이 아닐 가능성이 큽니다.')
    fig.tight_layout(rect=(0, 0.04, 1, 0.91))
    return save(fig, '02_diff_vs_ridge10.png')


# ---------------------------------------------------------------- 3. 특징 개수 x 모델
def plot_features():
    fig, axes = plt.subplots(2, 2, figsize=(13, 8.6))
    kinds = [('ridge', 'Ridge', FAMILY_COLOR['ridge']), ('gbm', 'GBM', FAMILY_COLOR['gbm']), ('blend_w30', '결합(Ridge30%)', FAMILY_COLOR['blend'])]
    for j, (name, ttl) in enumerate([('rolling_summary', '롤링 2012~2022'), ('holdout_summary', '2023~ (참고용)')]):
        t = read(name).set_index('model')['mae_pct']
        ax = axes[0, j]
        xs = np.arange(3)
        for k, lab, c in kinds:
            ys = [t[f'{fs}:{k}'] for fs in ['F10', 'F14', 'F21']]
            ax.plot(xs, ys, color=c, lw=2, marker='o', markersize=8, markeredgecolor=SURFACE, markeredgewidth=1.5)
            yy = ys[-1] + {'gbm': -1, 'blend_w30': 1}.get(k, 0) * 0.012 * (t.max() - t.min()) * 3
            ax.text(2.06, yy, lab, color=INK2, va='center', fontsize=9)
        ax.axhline(t['baseline:volatility'], color=FAMILY_COLOR['baseline'], lw=1, ls=(0, (4, 3)))
        ax.text(-0.05, t['baseline:volatility'], '변동성 기준선 ', color=INK2, ha='right', va='bottom', fontsize=8.5)
        ax.set_xticks(xs)
        ax.set_xticklabels(['10개\n(현재)', '14개\n(기존 계획)', '21개\n(추가 특징)'])
        ax.set_xlim(-0.35, 2.9)
        ax.set_ylabel('MAE (낮을수록 좋음)')
        ax.set_title(f'특징 개수 x 모델 — {ttl}', loc='left', fontsize=10.5)
        ax.grid(axis='x', visible=False)
        ax = axes[1, j]
        order = ['F10', 'F10+M', 'F10+I', 'F10+A', 'F14', 'F21']
        vals = [t[f'{fs}:ridge'] for fs in order]
        base = t['F10:ridge']
        ax.axhline(base, color=INK2, lw=1, ls=(0, (4, 3)))
        for i, (fs, v) in enumerate(zip(order, vals)):
            ax.scatter(i, v, s=90, color=FAMILY_COLOR['ridge'], edgecolor=SURFACE, linewidth=1.5, zorder=3)
            ax.plot([i, i], [base, v], color=FAMILY_COLOR['ridge'], lw=1.5, alpha=0.4)
            ax.text(i, v + (0.004 if v >= base else -0.004), f'{v:.3f}', ha='center', va='bottom' if v >= base else 'top', fontsize=8.5, color=INK2)
        ax.set_xticks(range(len(order)))
        ax.set_xticklabels(['10개\n(현재)', '+시장\n모멘텀', '+충격×\n베타', '+종목\n상태', '14개', '21개'], fontsize=9)
        ax.set_xlim(-0.5, len(order) - 0.5)
        ax.set_ylabel('Ridge MAE')
        ax.set_title(f'Ridge에 특징을 더하면 — {ttl}', loc='left', fontsize=10.5)
        ax.grid(axis='x', visible=False)
        lo, hi = min(vals), max(vals)
        ax.set_ylim(lo - (hi - lo) * 0.25, hi + (hi - lo) * 0.3)
    title(fig, '특징을 늘리면 좋아지는가?', '위: 특징 개수별 세 모델. 아래: Ridge에 특징 묶음을 하나씩 더한 진단(점선 = 현재 10개). Ridge는 늘릴수록 나빠지고 GBM은 그대로입니다.')
    fig.tight_layout(rect=(0, 0, 1, 0.92))
    return save(fig, '03_features_vs_model.png')


# ---------------------------------------------------------------- 4. 연도별
def plot_by_year():
    f = read('rolling_by_fold')
    f['year'] = f['fold'].str[4:].astype(int)
    show = ['baseline:volatility', 'F10:ridge', 'F10:gbm', 'F10:blend_w30', 'F21:gbm']
    styles = {'F21:gbm': (0, (3, 2))}
    fig, ax = plt.subplots(figsize=(12, 6.2))
    ends = {}
    for m in show:
        g = f[f.model == m].sort_values('year')
        c = FAMILY_COLOR[family(m)]
        ax.plot(g['year'], g['mae_pct'], color=c, lw=2.2, ls=styles.get(m, '-'), marker='o', markersize=5.5,
                markeredgecolor=SURFACE, markeredgewidth=1.2)
        ends[m] = float(g['mae_pct'].iloc[-1])
    order = sorted(ends, key=ends.get)                      # 끝점 라벨이 겹치지 않게 최소 간격을 둡니다
    gap, ypos, prev = 0.075, {}, None
    for m in order:
        ypos[m] = ends[m] if prev is None else max(ends[m], prev + gap)
        prev = ypos[m]
    for m in show:
        ax.plot([f['year'].max() + 0.05, f['year'].max() + 0.25], [ends[m], ypos[m]], color=GRID, lw=1)
        ax.text(f['year'].max() + 0.3, ypos[m], label(m), color=INK2, va='center', fontsize=9)
    ax.set_xticks(sorted(f['year'].unique()))
    ax.set_xlim(f['year'].min() - 0.4, f['year'].max() + 2.6)
    ax.set_ylabel('MAE (낮을수록 좋음)')
    ax.grid(axis='x', visible=False)
    ax.legend(handles=legend_handles(), loc='upper left', frameon=False, ncol=2, fontsize=9)
    title(fig, '연도별 MAE (롤링 검증)', '해마다 오차 수준이 크게 다르지만(2015·2020은 큰 변동), 모델 순서는 대체로 같습니다.')
    fig.tight_layout(rect=(0, 0, 1, 0.92))
    return save(fig, '04_by_year.png')


# ---------------------------------------------------------------- 5. 구간 품질
def plot_interval():
    fig, axes = plt.subplots(1, 2, figsize=(14, 6.2))
    for ax, name, ttl in [(axes[0], 'rolling_summary', '롤링 2012~2022'), (axes[1], 'holdout_summary', '2023~ (참고용)')]:
        t = read(name)
        ax.axhline(0.90, color=INK, lw=1.2)
        ax.text(0.99, 0.90, '목표 포함률 90%', transform=ax.get_yaxis_transform(), ha='right', va='top', fontsize=8.5, color=INK2)
        for _, r in t.iterrows():
            c = FAMILY_COLOR[family(r['model'])]
            ax.scatter(r['mean_width_pct'], r['coverage90'], s=80, color=c, edgecolor=SURFACE, linewidth=1.5, zorder=3)
        t['fam'] = t['model'].map(family)
        groups = [('gbm', 'GBM (10·14·21개)', (14, 16), 'left'), ('blend', '결합 (Ridge 30·50%)', (16, -26), 'left'),
                  ('baseline', '변동성 기준선', (-8, 10), 'right')]
        for fam, txt, off, ha in groups:
            g = t[t.fam == fam]
            ax.annotate(txt, (g['mean_width_pct'].mean(), g['coverage90'].mean()), xytext=off, textcoords='offset points',
                        fontsize=9, color=INK2, ha=ha)
        for m, off in [('F10:ridge', (8, 8)), ('F21:ridge', (8, -12))]:
            r = t[t.model == m].iloc[0]
            ax.annotate(label(m).replace(' Ridge', ' Ridge'), (r['mean_width_pct'], r['coverage90']), xytext=off,
                        textcoords='offset points', fontsize=9, color=INK2)
        ax.set_xlabel('평균 구간 폭 (%p, 좁을수록 좋음)')
        ax.set_ylabel('90% 구간 포함률')
        ax.set_title(f'{ttl}: 오른쪽 아래일수록 넓고 덜 맞음 / 왼쪽 위가 좋음', loc='left', fontsize=10)
        ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0, decimals=1))
    fig.legend(handles=legend_handles(), loc='lower center', ncol=4, frameon=False, bbox_to_anchor=(0.5, 0.0))
    title(fig, '예측 구간의 품질', '모든 모델의 구간은 같은 방식(보정 잔차 5%/95%)으로 만들었습니다. 포함률이 90%에 가깝고 폭이 좁을수록 좋습니다.')
    fig.tight_layout(rect=(0, 0.04, 1, 0.91))
    return save(fig, '05_interval_quality.png')


# ---------------------------------------------------------------- 6. 종목별
def plot_by_asset():
    a = read('holdout_by_asset').set_index('asset_id')
    fig, ax = plt.subplots(figsize=(11, 7.2))
    d = pd.DataFrame({'GBM': 100 * (a['F10:gbm'] / a[REF] - 1), '결합(Ridge30%)': 100 * (a['F10:blend_w30'] / a[REF] - 1),
                      '변동성 기준선': 100 * (a['baseline:volatility'] / a[REF] - 1)}).sort_values('GBM', ascending=False)
    y = np.arange(len(d))
    h = 0.27
    for k, (col, c) in enumerate([('GBM', FAMILY_COLOR['gbm']), ('결합(Ridge30%)', FAMILY_COLOR['blend']), ('변동성 기준선', FAMILY_COLOR['baseline'])]):
        ax.barh(y + (k - 1) * h, d[col], height=h - 0.03, color=c, label=col, edgecolor=SURFACE)
    for yi, v in zip(y, d['GBM']):
        ax.text(v + (0.3 if v >= 0 else -0.3), yi - h, f'{v:+.1f}%', va='center', ha='left' if v >= 0 else 'right', fontsize=8, color=INK2)
    ax.axvline(0, color=INK, lw=1.2)
    ax.set_yticks(y)
    ax.set_yticklabels(d.index)
    ax.invert_yaxis()
    ax.set_xlabel('10개 Ridge 대비 MAE 변화 (%)   ← 좋음 | 나쁨 →')
    ax.grid(axis='y', visible=False)
    ax.legend(loc='lower right', frameon=False)
    title(fig, '종목별 MAE 변화 (2023~, 10개 Ridge 대비)', '이력이 짧은 종목(207940, 028260 등)에서 Ridge가 기준선보다도 나빠 GBM의 이득이 큽니다. 그 외 종목에서도 대부분 개선입니다.')
    fig.tight_layout(rect=(0, 0, 1, 0.92))
    return save(fig, '06_by_asset.png')


def main(argv=None):
    paths = [plot_overview(), plot_diff(), plot_features(), plot_by_year(), plot_interval(), plot_by_asset()]
    print('\n'.join(paths))
    return 0


if __name__ == '__main__':
    sys.exit(main())
