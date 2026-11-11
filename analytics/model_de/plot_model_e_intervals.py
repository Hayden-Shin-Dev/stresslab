"""모델 E: 실측값과 예측 구간 그래프. compare_models.py(또는 모델 E 스크립트) 실행 뒤 인자 없이 실행합니다.

    python analytics/model_de/plot_model_e_intervals.py  ->  analytics/outputs/model_de/plots_e/*.png

읽는 파일: outputs/model_de/model_e_predictions.parquet (pyarrow 없으면 .csv)
그리는 것(종목마다, 1/5/20일 세 줄)
  전체 시험 구간: 80/90/95% 보정 구간(겹친 띠) + Q50 중심선 + 실측값. 90% 구간 밖 실측은 빨간 점.
  최근 구간 확대: 같은 그림을 최근 표본으로 확대.
  전 종목 요약: 실측이 구간 안에 들어간 비율(80/90/95%)과 위/아래로 벗어난 비율.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use('Agg')
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib import font_manager  # noqa: E402

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import common as C  # noqa: E402

SRC = C.OUT
OUT = SRC / 'plots_e'
ASSETS = ('005930', '000660', '005380')              # 그릴 종목(삼성전자, SK하이닉스, 현대차). 데이터에 없으면 건너뜁니다.
ZOOM_ROWS = 150
SURFACE, INK, INK2, GRID = '#fcfcfb', '#0b0b0b', '#52514e', '#e4e3df'
BAND = {80: ('#eb6834', 0.45), 90: ('#eb6834', 0.28), 95: ('#eb6834', 0.14)}
MISS = '#d62728'
H_LABEL = {1: '1일', 5: '5일', 20: '20일'}

_have = {f.name for f in font_manager.fontManager.ttflist}
_FONTS = [f for f in ['Malgun Gothic', 'AppleGothic', 'NanumGothic', 'Noto Sans CJK KR', 'Noto Sans CJK SC'] if f in _have] or ['DejaVu Sans']
plt.rcParams.update({'font.family': _FONTS, 'axes.unicode_minus': False, 'figure.facecolor': SURFACE, 'axes.facecolor': SURFACE,
                     'savefig.facecolor': SURFACE, 'axes.edgecolor': GRID, 'axes.labelcolor': INK2, 'xtick.color': INK2,
                     'ytick.color': INK2, 'text.color': INK, 'axes.spines.top': False, 'axes.spines.right': False,
                     'axes.grid': True, 'grid.color': GRID, 'grid.linewidth': 0.8, 'axes.axisbelow': True, 'font.size': 10})


def load():
    e = C.read_table(SRC / 'model_e_predictions.parquet')
    e['trading_date'] = pd.to_datetime(e['trading_date'])
    e['asset_id'] = e['asset_id'].astype(str).str.zfill(6)
    note = ''
    p = SRC / 'model_e_summary.json'
    ri = SRC / 'run_info.json'
    for f in (ri, p):
        if f.exists():
            d = json.loads(f.read_text(encoding='utf-8'))
            items = d['models'].values() if isinstance(d, dict) and 'models' in d else d
            b = {x.get('backend') for x in items if isinstance(x, dict) and 'backend' in x}
            if b and b != {'catboost'}:
                note = '  ※ CatBoost 아닌 대체 모델 결과(최종 수치 아님)'
            break
    return e, note


def head(fig, main, sub):
    fig.text(0.01, 0.985, main, fontsize=14, fontweight='bold', va='top')
    fig.text(0.01, 0.945, sub, fontsize=9.5, color=INK2, va='top')


def save(fig, name):
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / name
    fig.savefig(p, dpi=150)
    plt.close(fig)
    return str(p)


def draw(ax, d, h, size):
    for L in (95, 90, 80):                                    # 넓은 띠부터 겹쳐 그림
        c, a = BAND[L]
        ax.fill_between(d['trading_date'], d[f'lo_cqr_{L}'], d[f'hi_cqr_{L}'], color=c, alpha=a, lw=0, label=f'{L}% 구간')
    ax.plot(d['trading_date'], d['center'], color=INK, lw=0.9, label='예측 중심(Q50)')
    inside = (d['y_actual'] >= d['lo_cqr_90']) & (d['y_actual'] <= d['hi_cqr_90'])
    ax.scatter(d.loc[inside, 'trading_date'], d.loc[inside, 'y_actual'], s=size, color='#2a78d6', zorder=3, label='실측(90% 안)')
    ax.scatter(d.loc[~inside, 'trading_date'], d.loc[~inside, 'y_actual'], s=size * 2.2, color=MISS, zorder=4, label='실측(90% 밖)')
    ax.axhline(0, color=GRID)
    ax.set_ylabel('로그수익률 (%)')
    return float(inside.mean()), int((~inside).sum())


def fig_asset(e, asset, zoom, note):
    fig, axes = plt.subplots(3, 1, figsize=(13, 10.5))
    for ax, h in zip(axes, C.HORIZONS):
        d = e[(e['asset_id'] == asset) & (e['horizon'] == h)].sort_values('trading_date')
        if zoom:
            d = d.tail(ZOOM_ROWS)
        cov, n_out = draw(ax, d, h, 7 if zoom else 4)
        ax.set_title(f'{H_LABEL[h]} 예측 · 종목 {asset} · 표본 {len(d):,}개 · 90% 구간 안 {cov:.1%} (밖 {n_out}개)', loc='left', fontsize=10.5)
        if not zoom:
            ax.xaxis.set_major_locator(mdates.YearLocator())
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
    axes[0].legend(ncol=6, loc='upper left', fontsize=8.5, frameon=False)
    sub = '주황 띠 = 보정 후 80/90/95% 구간, 검은 선 = Q50, 파란 점 = 실측, 빨간 점 = 90% 구간 밖 실측.'
    sub += (' 5일/20일은 인접 표본의 정답 기간이 겹쳐 점이 이어져 보입니다.' if zoom else '')
    head(fig, f'모델 E 실측값 vs 예측 구간 · {asset}' + (f' · 최근 {ZOOM_ROWS}개 표본' if zoom else ' · 시험 구간 전체'), sub + note)
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    return save(fig, f'e_intervals_{asset}_{"zoom" if zoom else "full"}.png')


def fig_summary(e, note):
    fig, axes = plt.subplots(1, 3, figsize=(13, 4.8), sharey=True)
    for ax, h in zip(axes, C.HORIZONS):
        d = e[e['horizon'] == h]
        xs = np.arange(3)
        ins, below, above = [], [], []
        for L in (80, 90, 95):
            ins.append(((d['y_actual'] >= d[f'lo_cqr_{L}']) & (d['y_actual'] <= d[f'hi_cqr_{L}'])).mean())
            below.append((d['y_actual'] < d[f'lo_cqr_{L}']).mean())
            above.append((d['y_actual'] > d[f'hi_cqr_{L}']).mean())
        ax.bar(xs, ins, color='#2a78d6', width=0.55, label='구간 안')
        ax.bar(xs, below, bottom=ins, color='#7a5195', width=0.55, label='아래로 벗어남')
        ax.bar(xs, above, bottom=np.array(ins) + np.array(below), color=MISS, width=0.55, label='위로 벗어남')
        for xi, L, v in zip(xs, (0.80, 0.90, 0.95), ins):
            ax.hlines(L, xi - 0.36, xi + 0.36, color=INK, lw=1.6)
            ax.text(xi, v - 0.035, f'{v:.1%}', ha='center', color='white', fontsize=9.5, fontweight='bold')
        ax.set_xticks(xs); ax.set_xticklabels(['80%', '90%', '95%']); ax.set_ylim(0.6, 1.0)
        ax.set_title(f'{H_LABEL[h]} 예측 · 전 종목 {len(d):,}행', loc='left'); ax.set_xlabel('목표 Coverage'); ax.grid(axis='x', visible=False)
    axes[0].set_ylabel('실측이 놓인 위치의 비율'); axes[0].legend(loc='lower left', fontsize=8.5, frameon=False)
    head(fig, '모델 E: 실측값이 구간 안에 들어간 비율', '검은 선 = 목표. 위로/아래로 벗어난 비율이 한쪽에 치우치면 구간이 비대칭으로 어긋났다는 뜻입니다.' + note)
    fig.tight_layout(rect=(0, 0, 1, 0.9))
    return save(fig, 'e_interval_hit_rate.png')


def main():
    e, note = load()
    paths = []
    for a in ASSETS:
        if a not in set(e['asset_id']):
            print(f'종목 {a} 은(는) 예측 파일에 없어 건너뜁니다.')
            continue
        paths += [fig_asset(e, a, False, note), fig_asset(e, a, True, note)]
    paths.append(fig_summary(e, note))
    print(json.dumps(paths, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
