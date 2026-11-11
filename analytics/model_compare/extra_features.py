"""비교 실험용 추가 특징(F21 후보). 모두 t 시점까지의 과거 값으로만 계산합니다.

시장(날짜당 한 값)
  kospi_ret5          최근 5거래일 코스피 등락률(%)           -> 직전 급락/급등(단기 모멘텀, 반등/연쇄 하락)
  kospi_drawdown60    60거래일 최고점 대비 낙폭(%)             -> 이미 얼마나 빠진 상태인지
  vix_change5         VIX[t] - VIX[t-5]                       -> 불안이 막 커지는 중인지
  us10y_change20_bp   미국 10년 금리 20거래일 변화(bp)         -> 금리 방향성
  wti_trend20         WTI 20거래일 변화율(%)                   -> 유가 방향성
종목(날짜 x 종목, 종목 열마다 독립 계산)
  asset_ret20         종목 20거래일 등락률(%)
  asset_rel20         asset_ret20 - kospi_trend20             -> 시장 대비 강약
  asset_beta60        종목 일수익률의 코스피 일수익률 대비 60일 베타 -> 시장 충격에 대한 민감도
  asset_vol_ratio     asset_vol20 / asset_vol60               -> 최근 변동성이 평소보다 큰지
충격과의 곱(모델 입력을 만들 때 계산): ix_usdkrw_beta60, ix_vix_beta60 = 정규화한 충격 x 종목 베타
"""
from __future__ import annotations

import numpy as np
import pandas as pd

WINDOW, LONG_WINDOW = 20, 60
EXTRA_MARKET = ['kospi_ret5', 'kospi_drawdown60', 'vix_change5', 'us10y_change20_bp', 'wti_trend20']
EXTRA_ASSET = ['asset_ret20', 'asset_rel20', 'asset_beta60', 'asset_vol_ratio']
EXTRA_IX = ['ix_usdkrw_beta60', 'ix_vix_beta60']
IX_SOURCES = {'ix_usdkrw_beta60': ('shock_usdkrw_pct', 'asset_beta60'), 'ix_vix_beta60': ('shock_vix_pt', 'asset_beta60')}
EXTRA_COLUMNS = EXTRA_MARKET + EXTRA_ASSET


def build_extra_features(clean_gold: pd.DataFrame, fs) -> pd.DataFrame:
    """clean_gold: mock 제외한 Gold. fs: features.build_features 결과. 반환: (trading_date, asset_id) 단위 EXTRA_COLUMNS."""
    from features import market_table
    m = market_table(clean_gold).set_index('trading_date')
    kospi = m['kospi_close'].where(m['kospi_close'] > 0)
    wti = m['wti'].where(m['wti'] > 0)
    mk = pd.DataFrame(index=m.index)
    mk['kospi_ret5'] = (kospi / kospi.shift(5) - 1) * 100
    mk['kospi_drawdown60'] = (kospi / kospi.rolling(LONG_WINDOW, min_periods=LONG_WINDOW).max() - 1) * 100
    mk['vix_change5'] = m['vix'] - m['vix'].shift(5)
    mk['us10y_change20_bp'] = (m['us_treasury_10y'] - m['us_treasury_10y'].shift(WINDOW)) * 100
    mk['wti_trend20'] = (wti / wti.shift(WINDOW) - 1) * 100
    mk = mk.reset_index()

    af = fs.asset_features
    cal = pd.Index(fs.market_state['trading_date'])
    usable = af.set_index(['trading_date', 'asset_id'])['row_usable']
    close = clean_gold.set_index(['trading_date', 'asset_id'])['close']
    px = close.where(usable.reindex(close.index).fillna(False).astype(bool) & (close > 0))
    wide = px.unstack('asset_id').reindex(cal)
    k_ret = 100 * np.log(kospi.reindex(cal) / kospi.reindex(cal).shift(1))
    a_ret = 100 * np.log(wide / wide.shift(1))                     # 종목 열마다 독립
    beta = a_ret.rolling(LONG_WINDOW, min_periods=LONG_WINDOW).cov(k_ret).div(
        k_ret.rolling(LONG_WINDOW, min_periods=LONG_WINDOW).var(), axis=0)
    ret20 = (wide / wide.shift(WINDOW) - 1) * 100

    def long(w, name):
        w = w.copy()
        w.index.name, w.columns.name = 'trading_date', 'asset_id'
        return w.reset_index().melt(id_vars='trading_date', var_name='asset_id', value_name=name)

    out = af[['trading_date', 'asset_id', 'asset_vol20', 'asset_vol60']].copy()
    out = out.merge(long(ret20, 'asset_ret20'), on=['trading_date', 'asset_id'], how='left', validate='one_to_one')
    out = out.merge(long(beta, 'asset_beta60'), on=['trading_date', 'asset_id'], how='left', validate='one_to_one')
    out = out.merge(mk, on='trading_date', how='left', validate='many_to_one')
    kt = fs.market_state[['trading_date', 'kospi_trend20']]
    out = out.merge(kt, on='trading_date', how='left', validate='many_to_one')
    out['asset_rel20'] = out['asset_ret20'] - out['kospi_trend20']
    out['asset_vol_ratio'] = out['asset_vol20'] / out['asset_vol60'].where(out['asset_vol60'] > 0)
    return out[['trading_date', 'asset_id'] + EXTRA_COLUMNS]
