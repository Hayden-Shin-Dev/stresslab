"""모델 E 하이퍼파라미터 탐색 결과 그래프. tune_model_e.py 실행 뒤 인자 없이 실행합니다.

    python analytics/model_de/plot_tuning.py  ->  analytics/outputs/model_de/tuning/plots/*.png
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib
import matplotlib.ticker

matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib import font_manager  # noqa: E402

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import common as C  # noqa: E402

SRC = C.OUT / 'tuning'
OUT = SRC / 'plots'
SURFACE, INK, INK2, GRID = '#fcfcfb', '#0b0b0b', '#52514e', '#e4e3df'
COL = {'default': '#8a8984', 'tuned': '#eb6834'}
DEPTH_COL = {3: '#1baf7a', 4: '#2a78d6', 6: '#9b59b6'}
H_LABEL = {1: '1일', 5: '5일', 20: '20일'}
DEFAULT = dict(depth=4, iterations=300, learning_rate=0.05, l2_leaf_reg=10.0)

_have = {f.name for f in font_manager.fontManager.ttflist}
_FONTS = [f for f in ['Malgun Gothic', 'AppleGothic', 'NanumGothic', 'Noto Sans CJK KR', 'Noto Sans CJK SC'] if f in _have] or ['DejaVu Sans']
plt.rcParams.update({'font.family': _FONTS, 'axes.unicode_minus': False, 'figure.facecolor': SURFACE, 'axes.facecolor': SURFACE,
                     'savefig.facecolor': SURFACE, 'axes.edgecolor': GRID, 'axes.labelcolor': INK2, 'xtick.color': INK2,
                     'ytick.color': INK2, 'text.color': INK, 'axes.spines.top': False, 'axes.spines.right': False,
                     'axes.grid': True, 'grid.color': GRID, 'grid.linewidth': 0.8, 'axes.axisbelow': True, 'font.size': 10})


def head(fig, main, sub):
    fig.text(0.01, 0.985, main, fontsize=14, fontweight='bold', va='top')
    fig.text(0.01, 0.943, sub, fontsize=9.5, color=INK2, va='top')


def save(fig, name):
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / name
    fig.savefig(p, dpi=150)
    plt.close(fig)
    return str(p)


def note(info) -> str:
    return '' if info.get('backend') == 'catboost' else '  ※ CatBoost 아닌 대체 모델 결과(최종 수치 아님)'


# 1. 단계 1: 복잡도(반복 횟수, 깊이)에 따른 검증 점수
def fig_stage1(grid, info):
    g = grid[grid.stage == 1]
    fig, axes = plt.subplots(1, 3, figsize=(13, 4.8))
    for ax, h in zip(axes, C.HORIZONS):
        t = g[g.horizon == h]
        for d, c in DEPTH_COL.items():
            r = t[t.depth == d].sort_values('iterations')
            ax.plot(r.iterations, r.cv_pinball, color=c, marker='o', lw=1.8, label=f'깊이 {d}')
            ax.fill_between(r.iterations, r.cv_pinball - r.cv_se, r.cv_pinball + r.cv_se, color=c, alpha=0.10, lw=0)
        d0 = t[(t.depth == DEFAULT['depth']) & (t.iterations == DEFAULT['iterations'])]
        if len(d0):
            ax.scatter(d0.iterations, d0.cv_pinball, s=150, facecolor='none', edgecolor=INK, lw=1.6, zorder=5, label='기본 설정' if h == 1 else None)
        best = t.loc[t.cv_pinball.idxmin()]
        ax.annotate(f'최저 {best.cv_pinball:.4f}', (best.iterations, best.cv_pinball), textcoords='offset points', xytext=(8, -16), fontsize=8.5, color=INK2)
        ax.set_xscale('log'); ax.xaxis.set_minor_locator(matplotlib.ticker.NullLocator()); ax.set_xticks([150, 300, 600]); ax.set_xticklabels(['150', '300', '600'])
        ax.set_title(f'{H_LABEL[h]} 예측', loc='left'); ax.set_xlabel('반복 횟수(나무 수)'); ax.set_ylabel('검증 pinball (낮을수록 좋음)' if h == 1 else '')
    axes[0].legend(fontsize=8.5, frameon=False, loc='upper left')
    head(fig, '1단계 탐색: 모델이 단순할수록 검증 점수가 좋아졌습니다',
         '음영 = ±1 표준오차(검증 3개 연도). 검은 원 = 기본 설정. 선택된 설정은 격자에서 가장 단순한 쪽(가장자리)입니다.' + note(info))
    fig.tight_layout(rect=(0, 0, 1, 0.9))
    return save(fig, '1_stage1_complexity.png')


# 2. 단계 2: 학습률 x l2
def fig_stage2(grid, info):
    g = grid[grid.stage == 2]
    fig, axes = plt.subplots(1, 3, figsize=(13, 5))
    for ax, h in zip(axes, C.HORIZONS):
        t = g[g.horizon == h].pivot(index='learning_rate', columns='l2_leaf_reg', values='cv_pinball').sort_index()
        vmin, vmax = t.values.min(), t.values.max()
        ax.imshow(t.values, cmap='YlGn_r', vmin=vmin, vmax=vmax + (vmax - vmin) * 0.6, aspect='auto')
        ax.set_xticks(range(t.shape[1])); ax.set_xticklabels([f'{c:g}' for c in t.columns])
        ax.set_yticks(range(t.shape[0])); ax.set_yticklabels([f'{c:g}' for c in t.index])
        for i in range(t.shape[0]):
            for j in range(t.shape[1]):
                ax.text(j, i, f'{t.values[i, j]:.4f}', ha='center', va='center', fontsize=9.5, color='white' if t.values[i, j] - vmin < (vmax - vmin) * 0.45 else INK)
        b = np.unravel_index(np.argmin(t.values), t.shape)
        ax.add_patch(plt.Rectangle((b[1] - .5, b[0] - .5), 1, 1, fill=False, edgecolor=INK, lw=2))
        ax.set_title(f'{H_LABEL[h]} 예측', loc='left'); ax.set_xlabel('l2 규제'); ax.set_ylabel('학습률' if h == 1 else '')
        ax.grid(False)
    head(fig, '2단계 탐색: 학습률 0.03이 가장 좋고 l2 규제는 영향이 거의 없습니다',
         '숫자 = 검증 pinball(낮을수록 좋음), 짙은 색 = 좋음, 검은 테두리 = 최저. 색 범위는 패널마다 따로이며 차이는 0.001 안팎으로 매우 작습니다.' + note(info))
    fig.tight_layout(rect=(0, 0, 1, 0.87))
    return save(fig, '2_stage2_lr_l2.png')


# 3. 기본 vs 튜닝 (시험 구간)
def fig_effect(eff, info):
    metrics = [('mae', 'MAE (낮을수록 좋음)', '{:.3f}'), ('cqr_mean_width_90', '90% 구간 평균 폭 (좁을수록 좋음)', '{:.2f}'),
               ('cqr_interval_score_90', '90% Interval Score (낮을수록 좋음)', '{:.2f}'), ('cqr_coverage_90', '90% 구간 실제 포함률 (목표 0.90)', '{:.3f}'),
               ('raw_coverage_90', '보정 전 90% 포함률 (목표 0.90)', '{:.3f}'), ('crossing_rate_test', '분위수 역전 비율 (낮을수록 좋음)', '{:.2%}')]
    fig, axes = plt.subplots(2, 3, figsize=(13, 8))
    xs = np.arange(3)
    for ax, (m, title, fmt) in zip(axes.ravel(), metrics):
        for k, s in enumerate(('default', 'tuned')):
            r = eff[eff.setting == s].sort_values('horizon')
            x = xs + (k - 0.5) * 0.36
            ax.bar(x, r[m], width=0.34, color=COL[s], label='기본 설정' if s == 'default' else '튜닝 설정')
            for xi, v in zip(x, r[m]):
                ax.text(xi, v, fmt.format(v), ha='center', va='bottom', fontsize=8, color=INK2)
        if 'coverage' in m:
            ax.axhline(0.90, color=INK, lw=1.2)
            lo = eff[m].min()
            ax.set_ylim(max(0, lo - 0.05), min(1.0, eff[m].max() + 0.03))
        else:
            ax.set_ylim(0, eff[m].max() * 1.18)
        ax.set_xticks(xs); ax.set_xticklabels([H_LABEL[h] for h in (1, 5, 20)]); ax.set_title(title, loc='left', fontsize=10); ax.grid(axis='x', visible=False)
    axes[0, 0].legend(fontsize=8.5, frameon=False, loc='upper left')
    head(fig, '기본 설정 vs 튜닝 설정 (시험 구간 2023~)',
         '튜닝 설정 = 깊이 3, 반복 150, 학습률 0.03, l2 30. 시험 구간은 이전에 본 적이 있어 blind가 아닙니다.' + note(info))
    fig.tight_layout(rect=(0, 0, 1, 0.92))
    return save(fig, '3_default_vs_tuned.png')


# 4. 개선폭과 불확실성
def fig_paired(pair, info):
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.8))
    for ax, metric, ttl in ((axes[0], 'MAE 개선(기본-튜닝)', 'MAE 개선폭 (양수 = 튜닝이 좋음)'), (axes[1], 'Interval Score 개선(기본-튜닝)', 'Interval Score 개선폭 (양수 = 튜닝이 좋음)')):
        t = pair[pair.metric == metric].sort_values(['horizon', 'target_coverage'])
        if metric.startswith('MAE'):
            t = t[t.target_coverage == 0.9]
        ys = np.arange(len(t))[::-1]
        lab = [f'{H_LABEL[h]}' + ('' if metric.startswith('MAE') else f' · {int(L * 100)}%') for h, L in zip(t.horizon, t.target_coverage)]
        ax.errorbar(t.mean_gain, ys, xerr=[t.mean_gain - t.ci_lo, t.ci_hi - t.mean_gain], fmt='o', color=COL['tuned'], ecolor=INK2, capsize=3, lw=1.2)
        ax.axvline(0, color=INK, lw=1.3)
        ax.set_yticks(ys); ax.set_yticklabels(lab); ax.set_title(ttl, loc='left', fontsize=10.5); ax.grid(axis='y', visible=False)
        ax.set_xlabel('개선폭 (점 = 평균, 선 = 95% 블록 부트스트랩 구간)')
    head(fig, '개선폭이 우연을 넘는가', '선이 0을 가로지르면 개선이라고 단정할 수 없습니다. 지금은 대부분 0을 포함합니다.' + note(info))
    fig.tight_layout(rect=(0, 0, 1, 0.9))
    return save(fig, '4_improvement_uncertainty.png')


def main():
    grid = pd.read_csv(SRC / 'tuning_grid.csv')
    eff = pd.read_csv(SRC / 'tuning_effect.csv')
    pair = pd.read_csv(SRC / 'tuning_effect_paired.csv')
    info = json.loads((SRC / 'best_params.json').read_text(encoding='utf-8'))
    paths = [fig_stage1(grid, info), fig_stage2(grid, info), fig_effect(eff, info), fig_paired(pair, info)]
    print(json.dumps(paths, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
