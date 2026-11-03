"""학습용 시장 충격(S)과 종목 정답(y)을 만듭니다. (analytics/README.md 6절)

기준일 t와 한국 거래일 달력상 5거래일 뒤 t+5를 연결합니다.
달력상 5일이나 "종목의 다음 5개 유효 행"이 아닙니다. 달력은 Gold에 들어 있는 한국 거래일이며
결측 행을 지우지 않으므로, 5행 뒤가 곧 5거래일 뒤입니다.

  종목 정답  y = 100 * ln(종가[t+5] / 종가[t])                 (로그수익률, %)
  환율 충격     (usdkrw[t+5] / usdkrw[t] - 1) * 100             (%)
  WTI 충격      (wti[t+5] / wti[t] - 1) * 100                   (%, 두 값이 모두 양수일 때만)
  미국 10년 금리 충격  (금리[t+5] - 금리[t]) * 100               (bp)
  VIX 충격      vix[t+5] - vix[t]                               (지수 차이)

이 모듈은 미래 값(t+5)을 쓰는 유일한 곳입니다. 여기서 만든 충격과 정답은 현재 상태 피처나
시장 검색(A)의 입력에 들어가면 안 됩니다. 열 그룹은 build_samples.py에서 X, S, y로 분리됩니다.

충격의 시작값(t)은 Gold가 그 거래일에 연결한 관측값입니다. 상태 계산에 별도의 공표 지연 값을 썼다면
그 값으로 시작값을 바꾸지 않습니다. 각 요인의 공급자 관측 시작일/종료일과 그 간격(일)을 함께 남깁니다.
미국 관측 구간이 한국 종가 구간과 같다고 간주하지 않습니다.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

try:
    from features import market_table
except ImportError:  # 패키지로 가져올 때
    from .features import market_table

TARGET_VERSION = 'targets-v1.0'
HORIZON = 5
SHOCK_FACTORS = ['usdkrw', 'us_treasury_10y', 'wti', 'vix']
SHOCK_COLUMNS = ['shock_usdkrw_pct', 'shock_wti_pct', 'shock_us10y_bp', 'shock_vix_pt']
Y_COLUMN = 'y_log_return_5d'
OBS_COLUMNS = [f'{f}_{s}' for f in SHOCK_FACTORS for s in ('obs_start', 'obs_end', 'obs_span_days')]

TARGET_SPEC = {
    Y_COLUMN: '100 * ln(close[t+5] / close[t]). 로그수익률 %. 화면 변환은 to_simple_return_pct',
    'shock_usdkrw_pct': '(usdkrw[t+5] / usdkrw[t] - 1) * 100. %',
    'shock_wti_pct': '(wti[t+5] / wti[t] - 1) * 100. %. 두 값 중 하나라도 0 이하이면 결측',
    'shock_us10y_bp': '(us_treasury_10y[t+5] - us_treasury_10y[t]) * 100. bp',
    'shock_vix_pt': 'vix[t+5] - vix[t]. 지수 차이',
}


def to_simple_return_pct(log_return_pct):
    """학습 로그수익률(%)을 화면용 일반 수익률(%)로 바꿉니다. 70000 -> 66500은 약 -5.1293 -> -5."""
    return 100 * (np.exp(log_return_pct / 100) - 1)


def join_reasons(flags: dict, index) -> pd.Series:
    """True인 사유 이름을 ';'로 이어 붙입니다. 사유가 없으면 빈 문자열입니다."""
    out = pd.Series('', index=index, dtype=object)
    for name, mask in flags.items():
        out = out + np.where(np.asarray(mask, dtype=bool), name + ';', '')
    return out.str.rstrip(';') if len(out) else out


# ---------------------------------------------------------------- 시장 충격 (날짜당 한 행)
def build_market_shocks(df: pd.DataFrame, horizon: int = HORIZON) -> pd.DataFrame:
    assert horizon >= 2
    m = market_table(df)                                   # 날짜별 한 행, 거래일 오름차순
    n = len(m)
    has_h = pd.Series(np.arange(n) + horizon < n, index=m.index)

    out = pd.DataFrame({'trading_date': m['trading_date']})
    out['target_date'] = m['trading_date'].shift(-horizon)
    fx0, fx1 = m['usdkrw'], m['usdkrw'].shift(-horizon)
    w0, w1 = m['wti'], m['wti'].shift(-horizon)
    r0, r1 = m['us_treasury_10y'], m['us_treasury_10y'].shift(-horizon)
    v0, v1 = m['vix'], m['vix'].shift(-horizon)
    out['shock_usdkrw_pct'] = ((fx1 / fx0 - 1) * 100).where((fx0 > 0) & (fx1 > 0))
    out['shock_wti_pct'] = ((w1 / w0 - 1) * 100).where((w0 > 0) & (w1 > 0))
    out['shock_us10y_bp'] = (r1 - r0) * 100
    out['shock_vix_pt'] = v1 - v0

    for f in SHOCK_FACTORS:                                # 공급자 관측 시작일/종료일 보존
        start = m[f'{f}_observation_date']
        end = start.shift(-horizon)
        out[f'{f}_obs_start'], out[f'{f}_obs_end'] = start, end
        out[f'{f}_obs_span_days'] = (end - start).dt.days.astype('Int64')

    required = m[SHOCK_FACTORS]
    null_at = [required.shift(-k).isna().any(axis=1) for k in range(horizon + 1)]
    endpoint = null_at[0] | null_at[horizon]
    interior = pd.concat(null_at[1:horizon], axis=1).any(axis=1)
    out['flag_no_horizon'] = ~has_h                                          # 마지막 5거래일
    out['flag_shock_endpoint_missing'] = has_h & endpoint                    # t 또는 t+5의 요인 값이 없음
    out['flag_wti_nonpositive'] = has_h & ((w0 <= 0) | (w1 <= 0))            # 비율 변화 학습 제외
    out['flag_shock_interval_gap'] = has_h & ~endpoint & interior            # t+1~t+4 사이 요인 값이 없음
    return out


# ---------------------------------------------------------------- 종목 정답 (날짜 x 종목)
def _wide(rows: pd.DataFrame, values: pd.Series, calendar, dtype=None) -> pd.DataFrame:
    frame = pd.DataFrame({'trading_date': rows['trading_date'], 'asset_id': rows['asset_id'], 'v': values})
    w = frame.pivot(index='trading_date', columns='asset_id', values='v').reindex(calendar)
    return w


def _long(w: pd.DataFrame, name: str) -> pd.DataFrame:
    w = w.copy()
    w.index.name, w.columns.name = 'trading_date', 'asset_id'
    return w.reset_index().melt(id_vars='trading_date', var_name='asset_id', value_name=name)


def build_asset_targets(rows: pd.DataFrame, calendar, horizon: int = HORIZON) -> pd.DataFrame:
    """rows: trading_date, asset_id, close, row_usable(제외 사유 없음) 컬럼을 가진 (날짜, 종목) 표.

    종목 열마다 독립적으로 거래일 달력에 맞춘 뒤 horizon행 앞을 봅니다. 종목 사이를 섞지 않습니다.
    """
    calendar = pd.Index(calendar)
    n = len(calendar)
    ok = rows['row_usable'].astype(bool) & (rows['close'] > 0)
    wide_px = _wide(rows, rows['close'].where(ok), calendar)
    wide_ok = _wide(rows, ok.astype('int8'), calendar).fillna(0).astype(bool)
    has_h = pd.Series(np.arange(n) + horizon < n, index=calendar)

    end_ok = wide_ok.shift(-horizon, fill_value=False)
    interior_ok = wide_ok.shift(-1, fill_value=False)
    for k in range(2, horizon):
        interior_ok = interior_ok & wide_ok.shift(-k, fill_value=False)

    y = 100 * np.log(wide_px.shift(-horizon) / wide_px)
    end_gap = ~end_ok
    end_gap.loc[~has_h.to_numpy(), :] = False                 # 정답 자체가 없는 마지막 구간은 시장 단위 사유로 처리
    interval_gap = wide_ok & end_ok & ~interior_ok

    out = rows[['trading_date', 'asset_id']].copy()
    for w, name in [(y, Y_COLUMN), (end_gap, 'flag_price_unusable_t5'), (interval_gap, 'flag_price_interval_gap')]:
        out = out.merge(_long(w, name), on=['trading_date', 'asset_id'], how='left', validate='one_to_one')
    out['flag_price_unusable_t'] = (~ok).to_numpy()
    for c in ['flag_price_unusable_t5', 'flag_price_interval_gap']:
        out[c] = out[c].astype(bool)
    return out
