"""포트폴리오 손익과 손실 위험을 계산합니다. (analytics/README.md 10절) 순수 계산이며 파일을 읽거나 쓰지 않습니다.

입력  draws    종목별 5거래일 로그수익률(%) 표본. 행 = draw_id, 열 = 종목. 같은 행은 같은 날짜의 잔차입니다.
      holdings 종목 -> 현재 평가금액(원, 양수)
처리  1) 로그수익률 -> 일반 수익률 (100*(exp(r/100)-1)/100)
      2) 표본마다 종목 평가금액을 곱해 종목 손익(원)을 만들고, **같은 표본 안에서** 합산해 포트폴리오 손익을 만듦
      3) 포트폴리오 손익의 분포에서 위험을 계산 (종목별 최악 손실을 따로 골라 더하지 않음)

손실을 양수로 표시하는 규칙
  VaR95 = -(포트폴리오 손익의 5% 분위수)       분위수: numpy.quantile(..., method='linear')
  ES95  = -(하위 꼬리 표본의 포트폴리오 손익 평균)  꼬리: 포트폴리오 손익이 가장 낮은 ceil(0.05*n)개 표본
                                                  (같은 값은 표본 번호 순서로 정함)
  종목 기여도_i = -(그 꼬리 표본들의 종목 i 손익 평균).  종목 기여도의 합 = ES95 (같은 표본이라 항상 성립)
표본 수 n이 작으면 꼬리 표본이 몇 개 안 됩니다. tail_count와 warnings를 함께 보세요.

결과는 확정적인 예상 손실이 아닙니다. 과거 보정 구간의 잔차로 만든 시나리오 분포를 평가금액에 적용한 값입니다.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

try:
    from targets import to_simple_return_pct
except ImportError:  # 패키지로 가져올 때
    from .targets import to_simple_return_pct

PORTFOLIO_VERSION = 'portfolio-v1.0'
TAIL_PROB = 0.05
QUANTILE_METHOD = "numpy.quantile(method='linear')"
BAND_LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]
MIN_SAMPLES_WARN = 200          # 이보다 적으면 하위 5% 꼬리가 10개 미만이라 경고


def validate_holdings(holdings: dict) -> pd.Series:
    if not holdings:
        raise ValueError('보유 종목이 없습니다.')
    h = pd.Series(holdings, dtype=float)
    if not np.isfinite(h).all() or (h <= 0).any():
        raise ValueError('평가금액은 0보다 큰 유한한 값이어야 합니다(공매도/음수는 받지 않음).')
    return h


def pnl_by_asset(draws: pd.DataFrame, holdings: dict) -> pd.DataFrame:
    """표본 x 종목 손익(원). 열은 보유 종목, 행 번호(draw_id)는 draws와 같습니다."""
    h = validate_holdings(holdings)
    missing = [a for a in h.index if a not in draws.columns]
    if missing:
        raise KeyError(f'수익률 표본이 없는 종목: {missing}')
    if draws[h.index].isna().any().any():
        raise ValueError('수익률 표본에 결측이 있습니다. 같은 날짜에 모든 종목이 있는 표본만 쓰세요.')
    simple = to_simple_return_pct(draws[h.index].to_numpy(dtype=float)) / 100
    return pd.DataFrame(simple * h.to_numpy()[None, :], index=draws.index, columns=h.index)


def risk_summary(pnl: pd.DataFrame, tail_prob: float = TAIL_PROB) -> dict:
    """pnl: pnl_by_asset 결과. 반환: 손익 구간, VaR95, ES95, 종목별 기여도."""
    n = len(pnl)
    if n < 2:
        raise ValueError('표본이 너무 적습니다.')
    total = pnl.sum(axis=1).to_numpy()
    tail_count = int(math.ceil(tail_prob * n - 1e-12))
    order = np.argsort(total, kind='stable')
    tail = order[:tail_count]

    q05 = float(np.quantile(total, tail_prob, method='linear'))
    var = -q05
    es = -float(total[tail].mean())
    contrib = -pnl.iloc[tail].mean(axis=0)
    assert abs(contrib.sum() - es) <= 1e-6 * max(1.0, abs(es)), '기여도 합이 ES와 다릅니다.'
    assert es >= var - 1e-9, 'ES가 VaR보다 작습니다.'

    band = {f'p{int(round(l * 100)):02d}': float(np.quantile(total, l, method='linear')) for l in BAND_LEVELS}
    per_asset = pd.DataFrame({
        'asset_id': pnl.columns,
        'median_pnl_krw': pnl.median(axis=0).to_numpy(),
        'p05_pnl_krw': pnl.quantile(0.05, interpolation='linear').to_numpy(),
        'p95_pnl_krw': pnl.quantile(0.95, interpolation='linear').to_numpy(),
        'es_contribution_krw': contrib.to_numpy(),
        'es_contribution_share': (contrib / es).to_numpy() if es > 0 else np.nan})
    warnings = []
    if n < MIN_SAMPLES_WARN:
        warnings.append(f'표본이 {n}개라 하위 {tail_prob:.0%} 꼬리는 {tail_count}개 표본에 의존합니다. 값이 불안정할 수 있습니다.')
    if es <= 0:
        warnings.append('하위 꼬리 평균 손익이 0 이상입니다(손실로 표시되지 않음).')
    return {
        'portfolio_version': PORTFOLIO_VERSION, 'n_samples': int(n), 'tail_prob': tail_prob, 'tail_count': tail_count,
        'quantile_method': QUANTILE_METHOD,
        'tail_definition': f'포트폴리오 손익이 가장 낮은 ceil({tail_prob}*n)={tail_count}개 표본',
        'loss_sign': '손실을 양수로 표시',
        'pnl_band_krw': band, 'median_pnl_krw': band['p50'], 'share_of_samples_with_loss': float((total < 0).mean()),
        'var95_krw': var, 'es95_krw': es,
        'tail_draw_ids': [int(pnl.index[i]) for i in tail],
        'contributions': per_asset, 'total_pnl_krw': pd.Series(total, index=pnl.index, name='portfolio_pnl_krw'),
        'warnings': warnings}
