"""Conformal Prediction. 과거 잔차의 평균/표준편차로 구간을 만드는 방식과 다릅니다.

split conformal: 학습에 쓰지 않은 보정 데이터의 비적합 점수(잔차 크기)에서 유한 표본 보정 분위수
    k = ceil((n+1) * level), 보정값 = 정렬한 점수의 k번째 값(k > n 이면 무한대: 보장 불가)
를 구해 구간을 만듭니다. 교환 가능성 가정 아래 평균적으로 level 이상 포함을 보장합니다.
여기서는 인접 날짜의 5일/20일 구간이 겹쳐 가정이 정확히 성립하지 않으므로, 보장 대신 시험 구간의 실제 포함률을 측정합니다.

CQR(conformalized quantile regression): 분위수 모델의 [lo, hi]를 점수 max(lo-y, y-hi)의 보정 분위수만큼 넓히거나 줄입니다.
모든 점수는 종목 변동성 척도(asset_scale)로 나눈 정규화 단위입니다.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from common import MIN_ASSET_ROWS


def conformal_quantile(scores, level: float) -> float:
    s = np.sort(np.asarray(scores, dtype=float))
    n = len(s)
    k = int(np.ceil((n + 1) * level - 1e-12))
    return float('inf') if k > n or n == 0 else float(s[k - 1])


# ---------------------------------------------------------------- 점 예측 + 잔차 보정 (모델 D)
def sym_halfwidth(resid_cal, level) -> float:
    return conformal_quantile(np.abs(resid_cal), level)


def asym_halfwidths(resid_cal, level) -> tuple[float, float]:
    """아래쪽/위쪽 꼬리를 따로 보정(각 꼬리 1-(1-level)/2). resid = y - 예측."""
    t = 1 - (1 - level) / 2
    return conformal_quantile(-np.asarray(resid_cal), t), conformal_quantile(np.asarray(resid_cal), t)


def by_asset_halfwidths(resid_cal, assets_cal, level, assets_query, min_rows=MIN_ASSET_ROWS) -> np.ndarray:
    pooled = sym_halfwidth(resid_cal, level)
    qs = {a: (sym_halfwidth(g.to_numpy(), level) if len(g) >= min_rows else pooled)
          for a, g in pd.Series(resid_cal).groupby(np.asarray(assets_cal))}
    return np.array([qs.get(a, pooled) for a in assets_query])


# ---------------------------------------------------------------- CQR (모델 E)
def cqr_scores(y, lo, hi):
    return np.maximum(lo - y, y - hi)


def cqr_adjustment(y_cal, lo_cal, hi_cal, level) -> float:
    return conformal_quantile(cqr_scores(y_cal, lo_cal, hi_cal), level)


# ---------------------------------------------------------------- 롤링 보정
def rolling_quantiles(scores_pool, target_pos_pool, query_pos, level, window, fallback) -> np.ndarray:
    """각 질의 행(결정 위치 p)마다, 정답 종료 위치가 [p-window, p-1]인 풀 점수의 보정 분위수.

    p 시점에 이미 실현된 정답(target_pos < p)만 쓰므로 미래 정보가 들어가지 않습니다.
    풀이 너무 작으면(<200) 전체 보정 값(fallback)을 씁니다.
    """
    order = np.argsort(target_pos_pool, kind='stable')
    tp, sc = np.asarray(target_pos_pool)[order], np.asarray(scores_pool, dtype=float)[order]
    query_pos = np.asarray(query_pos)
    out = np.empty(len(query_pos))
    cache = {}
    for p in np.unique(query_pos):
        i0, i1 = np.searchsorted(tp, p - window, side='left'), np.searchsorted(tp, p, side='left')
        pool = sc[i0:i1]
        cache[p] = conformal_quantile(pool, level) if len(pool) >= 200 else fallback
    for j, p in enumerate(query_pos):
        out[j] = cache[p]
    return out
