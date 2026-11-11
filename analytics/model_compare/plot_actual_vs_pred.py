"""실제 y와 예측 y를 비교하는 그래프. (2023~ 평가 구간, 학습 <2020, 보정 2020~2022)

    python analytics/model_compare/plot_actual_vs_pred.py        # VS Code ▶ 실행, 인자 없음
    -> analytics/outputs/model_compare/actual_vs_pred/{holdout_predictions.csv, 01~03 .png}

y = 5거래일 로그수익률(%), 즉 100*ln(종가[t+5]/종가[t]). 예측 y는 모델의 중심값(분포의 가운데)이며
실제 충격 S를 입력으로 넣은 '조건부 반응 재구성'입니다. 비교 모델: 10개 Ridge(현재), 10개 GBM, 결합(Ridge 30%).
2023~ 구간은 이전 실험에서 이미 사용했으므로 참고용입니다. 인접 날짜의 5일 구간은 겹칩니다.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import compare_models as cm  # noqa: E402
import matplotlib  # noqa: E402

matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402
import plot_compare as pc  # noqa: E402  (같은 글꼴/색 설정을 재사용)

OUT = cm.OUT / 'actual_vs_pred'
FS = 'F10'
MODELS = [('ridge', '10개 Ridge (현재)', pc.FAMILY_COLOR['ridge']), ('gbm', '10개 GBM', pc.FAMILY_COLOR['gbm']),
          ('blend_w30', '10개 결합(Ridge30%)', pc.FAMILY_COLOR['blend'])]
ACTUAL_COLOR = '#8a8984'
SHOW_ASSETS = ['005930', '005380']
LIM = 25


def predictions(d: pd.DataFrame) -> pd.DataFrame:
    """고정 분할(학습 <2020, 보정 2020~2022, 평가 2023~)에서 예측 y(로그수익률 %)와 90% 구간을 만듭니다."""
    train = d[d['target_date'] < cm.CAL_START]
    cal = d[(d['trading_date'] >= cm.CAL_START) & (d['target_date'] < cm.EVAL_START)]
    test = d[d['trading_date'] >= cm.EVAL_START]
    n = train.groupby('asset_id').size()
    assets = set(n[n >= cm.MIN_ASSET_TRAIN_ROWS].index) & set(cal['asset_id']) & set(test['asset_id'])
    train, cal, test = (x[x['asset_id'].isin(assets)].reset_index(drop=True) for x in (train, cal, test))
    m = cm.CenterModels(cm.FEATURE_SETS[FS]).fit(train, assets)
    cc, ct = m.centers(cal), m.centers(test)
    sc = cm._floor(test['asset_scale'].to_numpy())
    y_cal = cal['y_log_return_5d'].to_numpy(float) / cm._floor(cal['asset_scale'].to_numpy())
    out = test[['trading_date', 'asset_id']].copy()
    out['actual'] = test['y_log_return_5d'].to_numpy(float)
    for kind, _, _ in MODELS:
        out[f'pred_{kind}'] = ct[kind] * sc
        per, pooled = cm.residual_quantiles(pd.Series(y_cal - cc[kind]), cal['asset_id'])
        q = np.array([per.get(a, pooled) for a in test['asset_id']])
        out[f'lo_{kind}'] = (ct[kind] + q[:, 0]) * sc
        out[f'hi_{kind}'] = (ct[kind] + q[:, 1]) * sc
    return out


def stats(p: pd.DataFrame, kind: str) -> dict:
    a, f = p['actual'].to_numpy(), p[f'pred_{kind}'].to_numpy()
    slope = np.polyfit(f, a, 1)[0]
    return {'corr': float(np.corrcoef(a, f)[0, 1]), 'slope': float(slope), 'mae': float(np.abs(a - f).mean()),
            'pred_std': float(f.std()), 'actual_std': float(a.std())}


def fig_scatter(p: pd.DataFrame):
    fig, axes = plt.subplots(2, 2, figsize=(12.5, 11))
    for ax, (kind, name, c) in zip(axes.flat[:3], MODELS):
        ax.scatter(p[f'pred_{kind}'], p['actual'], s=5, color=c, alpha=0.18, linewidths=0, rasterized=True)
        ax.plot([-LIM, LIM], [-LIM, LIM], color=pc.INK, lw=1.2, ls=(0, (4, 3)))
        ax.axhline(0, color=pc.GRID, lw=1)
        ax.axvline(0, color=pc.GRID, lw=1)
        s = stats(p, kind)
        ax.text(0.03, 0.97, f"상관 {s['corr']:.2f}\n예측 표준편차 {s['pred_std']:.2f} / 실제 {s['actual_std']:.2f}",
                transform=ax.transAxes, va='top', fontsize=9.5, color=pc.INK2)
        ax.set_xlim(-LIM, LIM)
        ax.set_ylim(-LIM, LIM)
        ax.set_aspect('equal')
        ax.set_xlabel('예측 y (5일 로그수익률 %)')
        ax.set_ylabel('실제 y (%)')
        ax.set_title(name, loc='left', fontsize=10.5)
    ax = axes.flat[3]
    ax.plot([-3, 3], [-3, 3], color=pc.INK, lw=1.2, ls=(0, (4, 3)))
    for kind, name, c in MODELS:
        b = pd.qcut(p[f'pred_{kind}'], 10, duplicates='drop')
        g = p.groupby(b, observed=True).agg(pred=(f'pred_{kind}', 'mean'), act=('actual', 'mean'), n=('actual', 'size'))
        se = p.groupby(b, observed=True)['actual'].std() / np.sqrt(g['n'])
        ax.errorbar(g['pred'], g['act'], yerr=1.96 * se, color=c, marker='o', ms=6, lw=2, capsize=3, label=name,
                    markeredgecolor=pc.SURFACE)
    ax.set_xlabel('예측 y 10분위 평균')
    ax.set_ylabel('그 구간의 실제 y 평균 (±95%)')
    ax.set_title('예측을 10구간으로 나눴을 때 실제 평균', loc='left', fontsize=10.5)
    ax.legend(frameon=False, fontsize=9, loc='upper left')
    pc.title(fig, '실제 y와 예측 y (2023~, 참고용)', '점선 = 완벽한 예측(y=x). 예측은 0 근처에 몰려 있습니다. 5일 수익률 대부분이 시장 충격으로 설명되지 않는 종목 고유 움직임이기 때문입니다.')
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    return pc.save_to(fig, OUT, '01_actual_vs_pred_scatter.png')


def fig_timeseries(p: pd.DataFrame):
    fig, axes = plt.subplots(len(SHOW_ASSETS), 1, figsize=(14, 4.8 * len(SHOW_ASSETS)), sharex=True)
    cal = pd.Index(sorted(p['trading_date'].unique()))
    for ax, a in zip(np.atleast_1d(axes), SHOW_ASSETS):
        g = p[p['asset_id'] == a].set_index('trading_date').reindex(cal)       # 빈 날짜는 NaN으로 두어 선이 끊기게
        ax.fill_between(g.index, g['lo_gbm'], g['hi_gbm'], color=pc.FAMILY_COLOR['gbm'], alpha=0.12, linewidth=0,
                        label='GBM 90% 구간')
        ax.plot(g.index, g['actual'], color=ACTUAL_COLOR, lw=0.9, label='실제 y')
        for kind, name, c in MODELS[:2]:
            ax.plot(g.index, g[f'pred_{kind}'], color=c, lw=1.4, label=f'{name} 예측')
        ax.axhline(0, color=pc.GRID, lw=1)
        ax.set_ylabel('5일 로그수익률 (%)')
        ax.set_title(f'종목 {a}', loc='left', fontsize=10.5)
        ax.legend(frameon=False, ncol=4, fontsize=9, loc='upper left')
        ax.grid(axis='x', visible=False)
    pc.title(fig, '시간에 따른 실제 y와 예측 y', '회색 = 실제, 파랑 = Ridge 예측, 주황 = GBM 예측. 음영 = GBM 90% 구간. 인접 날짜의 5일 구간은 겹치므로 실제 선이 부드럽게 이어집니다.')
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    return pc.save_to(fig, OUT, '02_actual_vs_pred_timeseries.png')


def fig_grid(p: pd.DataFrame):
    assets = sorted(p['asset_id'].unique())
    cols = 3
    rows = int(np.ceil(len(assets) / cols))
    cal = pd.Index(sorted(p['trading_date'].unique()))
    fig, axes = plt.subplots(rows, cols, figsize=(16, 2.6 * rows), sharex=True)
    for ax, a in zip(axes.flat, assets):
        g = p[p['asset_id'] == a].set_index('trading_date').reindex(cal)
        ax.plot(g.index, g['actual'], color=ACTUAL_COLOR, lw=0.7)
        ax.plot(g.index, g['pred_ridge'], color=MODELS[0][2], lw=1.1)
        ax.plot(g.index, g['pred_gbm'], color=MODELS[1][2], lw=1.1)
        ax.axhline(0, color=pc.GRID, lw=0.8)
        ax.set_title(a, loc='left', fontsize=10)
        ax.tick_params(labelsize=8)
        ax.grid(axis='x', visible=False)
    for ax in list(axes.flat)[len(assets):]:
        ax.axis('off')
    from matplotlib.lines import Line2D
    fig.legend(handles=[Line2D([0], [0], color=ACTUAL_COLOR, lw=2, label='실제 y'), Line2D([0], [0], color=MODELS[0][2], lw=2, label='Ridge 예측'),
                        Line2D([0], [0], color=MODELS[1][2], lw=2, label='GBM 예측')], loc='lower center', ncol=3, frameon=False,
               bbox_to_anchor=(0.5, 0.0))
    pc.title(fig, '종목별 실제 y와 예측 y (2023~)', '종목 데이터가 없는 구간은 선이 끊깁니다. 예측선은 0 근처에서 완만하게 움직입니다.')
    fig.tight_layout(rect=(0, 0.03, 1, 0.925))
    return pc.save_to(fig, OUT, '03_actual_vs_pred_by_asset.png')


def main(argv=None):
    from build_samples import DEFAULT_OUT as SAMPLES_DIR
    from features import build_features
    from load_gold import DEFAULT_SOURCE, load_gold
    from train import market_scale_from_gold
    from extra_features import build_extra_features
    gold = load_gold(DEFAULT_SOURCE)
    clean = gold[~gold['is_mock']].reset_index(drop=True)
    d, _ = cm.prepare(pd.read_parquet(Path(SAMPLES_DIR) / 'training_samples.parquet'), market_scale_from_gold(gold),
                      build_extra_features(clean, build_features(gold)))
    return run(d)


def run(d: pd.DataFrame):
    p = predictions(d)
    OUT.mkdir(parents=True, exist_ok=True)
    p.to_csv(OUT / 'holdout_predictions.csv', index=False, encoding='utf-8-sig', float_format='%.5f')
    paths = [fig_scatter(p), fig_timeseries(p), fig_grid(p)]
    for kind, name, _ in MODELS:
        s = stats(p, kind)
        print(f"{name}: 상관 {s['corr']:.3f}, MAE {s['mae']:.3f}, 예측 표준편차 {s['pred_std']:.3f} (실제 {s['actual_std']:.3f})")
    print('\n'.join(paths))
    return p


if __name__ == '__main__':
    sys.exit(0 if main() is not None else 1)
