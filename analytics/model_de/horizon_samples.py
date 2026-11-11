"""1일 / 5일 / 20일 예측용 표본(X, S, y)을 만듭니다. 기존 targets.py / build_samples.py는 수정하지 않습니다.

기존 코드는 5일 중심이고 1일은 막혀 있어(기간 2 이상만 허용) 같은 정의를 기간만 바꿔 다시 구현했습니다.
h=5 결과는 기존 build_samples와 같아야 하며 테스트가 그것을 확인합니다.

  y(h)      100 * ln(close[t+h] / close[t])           종목 열마다 독립, 거래일 달력 기준
  S(h)      환율/WTI %변화, 미국 10년 bp 변화, VIX 포인트 변화 (t -> t+h)
  X         t까지의 과거 정보만 사용(features.py 결과를 그대로 사용)
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ANALYTICS_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ANALYTICS_ROOT / 'src'))
from features import ASSET_FEATURES, MARKET_FEATURES, market_table  # noqa: E402
from targets import SHOCK_COLUMNS, SHOCK_FACTORS, join_reasons  # noqa: E402

KEY = ['trading_date', 'asset_id']
X_COLUMNS = MARKET_FEATURES + ASSET_FEATURES
S_COLUMNS = list(SHOCK_COLUMNS)


def y_column(h: int) -> str:
    return f'y_log_return_{h}d'


def market_shocks(df: pd.DataFrame, h: int) -> pd.DataFrame:
    """날짜당 한 행. targets.build_market_shocks와 같은 정의이며 h=1도 허용합니다."""
    assert h >= 1
    m = market_table(df)
    n = len(m)
    has_h = pd.Series(np.arange(n) + h < n, index=m.index)
    out = pd.DataFrame({'trading_date': m['trading_date']})
    out['target_date'] = m['trading_date'].shift(-h)
    fx0, fx1 = m['usdkrw'], m['usdkrw'].shift(-h)
    w0, w1 = m['wti'], m['wti'].shift(-h)
    r0, r1 = m['us_treasury_10y'], m['us_treasury_10y'].shift(-h)
    v0, v1 = m['vix'], m['vix'].shift(-h)
    out['shock_usdkrw_pct'] = ((fx1 / fx0 - 1) * 100).where((fx0 > 0) & (fx1 > 0))
    out['shock_wti_pct'] = ((w1 / w0 - 1) * 100).where((w0 > 0) & (w1 > 0))
    out['shock_us10y_bp'] = (r1 - r0) * 100
    out['shock_vix_pt'] = v1 - v0
    required = m[SHOCK_FACTORS]
    null_at = [required.shift(-k).isna().any(axis=1) for k in range(h + 1)]
    endpoint = null_at[0] | null_at[h]
    interior = pd.concat(null_at[1:h], axis=1).any(axis=1) if h >= 2 else pd.Series(False, index=m.index)
    out['flag_no_horizon'] = ~has_h
    out['flag_shock_endpoint_missing'] = has_h & endpoint
    out['flag_wti_nonpositive'] = has_h & ((w0 <= 0) | (w1 <= 0))
    out['flag_shock_interval_gap'] = has_h & ~endpoint & interior
    return out


def _wide(rows, values, calendar):
    f = pd.DataFrame({'trading_date': rows['trading_date'], 'asset_id': rows['asset_id'], 'v': values})
    return f.pivot(index='trading_date', columns='asset_id', values='v').reindex(calendar)


def _long(w, name):
    w = w.copy()
    w.index.name, w.columns.name = 'trading_date', 'asset_id'
    return w.reset_index().melt(id_vars='trading_date', var_name='asset_id', value_name=name)


def asset_targets(rows: pd.DataFrame, calendar, h: int) -> pd.DataFrame:
    """rows: trading_date, asset_id, close, row_usable. 종목 열마다 독립으로 달력 위치 기준 h행 앞을 봅니다."""
    calendar = pd.Index(calendar)
    n = len(calendar)
    ok = rows['row_usable'].astype(bool) & (rows['close'] > 0)
    px = _wide(rows, rows['close'].where(ok), calendar)
    wide_ok = _wide(rows, ok.astype('int8'), calendar).fillna(0).astype(bool)
    has_h = pd.Series(np.arange(n) + h < n, index=calendar)
    end_ok = wide_ok.shift(-h, fill_value=False)
    y = 100 * np.log(px.shift(-h) / px)
    end_gap = ~end_ok
    end_gap.loc[~has_h.to_numpy(), :] = False
    if h >= 2:
        interior_ok = wide_ok.shift(-1, fill_value=False)
        for k in range(2, h):
            interior_ok = interior_ok & wide_ok.shift(-k, fill_value=False)
        interval_gap = wide_ok & end_ok & ~interior_ok
    else:
        interval_gap = pd.DataFrame(False, index=wide_ok.index, columns=wide_ok.columns)
    out = rows[KEY].copy()
    for w, name in [(y, y_column(h)), (end_gap, 'flag_price_unusable_end'), (interval_gap, 'flag_price_interval_gap')]:
        out = out.merge(_long(w, name), on=KEY, how='left', validate='one_to_one')
    out['flag_price_unusable_t'] = (~ok).to_numpy()
    for c in ['flag_price_unusable_end', 'flag_price_interval_gap']:
        out[c] = out[c].astype(bool)
    return out


def build_horizon_samples(clean_gold: pd.DataFrame, fs, h: int) -> pd.DataFrame:
    """clean_gold: mock 제외 Gold. fs: features.build_features 결과. 반환: 표본 표(train_ready 포함)."""
    af = fs.asset_features
    rows = clean_gold[['dataset_version', 'trading_date', 'asset_id', 'close']].merge(
        af[KEY + ['row_usable', 'point_in_time_verified'] + X_COLUMNS], on=KEY, how='left', validate='one_to_one')
    assert len(rows) == len(af) and rows['row_usable'].notna().all(), 'features와 Gold의 행이 맞지 않습니다.'
    shocks = market_shocks(clean_gold, h)
    targets = asset_targets(rows, fs.market_state['trading_date'], h)
    s = (rows.drop(columns=['close']).merge(targets, on=KEY, how='left', validate='one_to_one')
         .merge(shocks, on='trading_date', how='left', validate='many_to_one'))
    flags = {'no_horizon': s['flag_no_horizon'], 'state_incomplete': s[X_COLUMNS].isna().any(axis=1),
             'price_unusable_t': s['flag_price_unusable_t'], 'price_unusable_end': s['flag_price_unusable_end'],
             'price_interval_gap': s['flag_price_interval_gap'], 'shock_endpoint_missing': s['flag_shock_endpoint_missing'],
             'wti_nonpositive': s['flag_wti_nonpositive'], 'shock_interval_gap': s['flag_shock_interval_gap']}
    s['exclude_reasons'] = join_reasons(flags, s.index)
    s['train_ready'] = s['exclude_reasons'].eq('')
    s['horizon'] = h
    cols = (['dataset_version', 'horizon', 'trading_date', 'target_date', 'asset_id'] + X_COLUMNS + S_COLUMNS + [y_column(h)]
            + ['point_in_time_verified', 'row_usable', 'exclude_reasons', 'train_ready'])
    out = s[cols].sort_values(KEY).reset_index(drop=True)
    ready = out[out['train_ready']]
    assert not ready[X_COLUMNS + S_COLUMNS + [y_column(h)]].isna().any().any(), 'train_ready 행에 결측이 있습니다.'
    return out
