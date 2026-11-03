"""날짜별 시장 상태(market_state)와 종목별 피처를 계산합니다. (analytics/README.md 5절)

    python analytics/src/features.py            # VS Code ▶ 실행도 같습니다
    -> analytics/outputs/features/market_state.parquet
       analytics/outputs/features/asset_features.parquet
       analytics/outputs/features/features_metadata.json

계산 원칙
  - 시장 공통 값은 날짜별 한 행으로 줄여 정렬한 뒤 계산하고 종목에 연결합니다.
    종목이 반복된 전체 표에 shift를 적용하지 않습니다.
  - 20거래일은 Gold에 들어 있는 한국 거래일 달력의 20행 전입니다. 결측 행을 지우지 않으므로
    "유효 관측 20개"로 바뀌지 않습니다. 기간이 부족하거나 창 안에 결측이 있으면 결측으로 남깁니다.
  - 종목별 변동성도 같은 달력에 맞춘 종목×날짜 표에서 계산합니다. 종목 사이를 섞어 shift하지 않습니다.
  - 제외 사유가 있는 종목 행(격리, 거래정지 후보, 결측 등)의 종가는 수익률 계산에서 빼고
    행 자체는 남깁니다. 다른 종목의 결측은 이 종목에 영향을 주지 않습니다.
  - A(시장 검색)와 B(조건부 모델)는 이 모듈이 만든 market_state를 그대로 받습니다.
    각자 다시 계산하지 않고, features_metadata.json의 market_state_sha256으로 같은 상태인지 확인합니다.

연구 모드의 Gold는 이전 관측일 값을 최대 7일 이내에서 연결한 것이며 당시 공개되어 있었다는 뜻이 아닙니다.
공표 일정 추정에 따른 추가 지연 처리(기존 로컬 연구 방식)는 적용하지 않았습니다.
공개 시각이 모두 확인된 날짜만 point_in_time_verified=True입니다.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

try:
    from load_gold import ANALYTICS_ROOT, DEFAULT_SOURCE, FACTORS, exclusion_table, load_gold, usable_mask
except ImportError:  # 패키지로 가져올 때
    from .load_gold import ANALYTICS_ROOT, DEFAULT_SOURCE, FACTORS, exclusion_table, load_gold, usable_mask

FEATURE_VERSION = 'features-v1.0'
WINDOW, LONG_WINDOW, ANNUAL_DAYS = 20, 60, 252
DEFAULT_OUT = ANALYTICS_ROOT / 'outputs/features'

MARKET_FEATURES = ['kospi_trend20', 'kospi_vol20', 'usdkrw_trend20', 'us10y_level',
                   'wti_level', 'vix_level', 'kr3y_level', 'kr3y_change20_bp']
ASSET_FEATURES = ['asset_vol20', 'asset_vol60']
OBS_DATES = [f'{f}_observation_date' for f in FACTORS]
AVAIL = [f'{f}_available_at' for f in FACTORS]

FEATURE_SPEC = {
    'kospi_trend20': '(kospi_close[t] / kospi_close[t-20] - 1) * 100. 단위 %',
    'kospi_vol20': '일 일반수익률(소수)의 최근 20개 표본 표준편차 * sqrt(252) * 100. 연율화 %',
    'usdkrw_trend20': '(usdkrw[t] / usdkrw[t-20] - 1) * 100. Gold에 연결된 관측값 기준. 단위 %',
    'us10y_level': 'us_treasury_10y 수준. 연 %',
    'wti_level': 'wti 수준. 달러/배럴. 0 이하도 원본대로 보존',
    'vix_level': 'vix 수준. 지수',
    'kr3y_level': 'korea_3y 수준. 3.0은 연 3%',
    'kr3y_change20_bp': '(korea_3y[t] - korea_3y[t-20]) * 100. 단위 bp',
    'asset_vol20': '100 * ln(종가[t]/종가[t-1])의 최근 20개 표본 표준편차. 연율화하지 않은 일 단위 %',
    'asset_vol60': '위와 같고 최근 60개',
}


@dataclass
class FeatureSet:
    market_state: pd.DataFrame     # 날짜당 한 행
    asset_features: pd.DataFrame   # Gold의 (날짜, 종목) 행마다 한 행. 시장 피처를 연결해 둠
    meta: dict


# ---------------------------------------------------------------- 시장 상태
def market_table(df: pd.DataFrame) -> pd.DataFrame:
    """종목이 반복된 표를 날짜별 한 행으로 줄입니다. 날짜 안에서 값이 다르면 멈춥니다."""
    cols = ['kospi_close'] + FACTORS + OBS_DATES + AVAIL
    nun = df.groupby('trading_date')[cols].nunique(dropna=False)
    bad = [c for c in cols if (nun[c] > 1).any()]
    if bad:
        raise ValueError(f'같은 날짜인데 종목마다 값이 다른 시장 공통 컬럼: {bad}. load_gold 검사를 먼저 통과해야 합니다.')
    m = df.drop_duplicates('trading_date').sort_values('trading_date')[['trading_date'] + cols]
    m = m.reset_index(drop=True)
    assert m['trading_date'].is_unique and m['trading_date'].is_monotonic_increasing
    return m


def build_market_state(df: pd.DataFrame) -> pd.DataFrame:
    m = market_table(df)
    kospi = m['kospi_close'].where(m['kospi_close'] > 0)
    fx = m['usdkrw'].where(m['usdkrw'] > 0)
    kospi_ret = kospi / kospi.shift(1) - 1                      # 일반 수익률, 소수

    out = pd.DataFrame({
        'dataset_version': df['dataset_version'].iloc[0],
        'feature_version': FEATURE_VERSION,
        'trading_date': m['trading_date'],
    })
    out['kospi_trend20'] = (kospi / kospi.shift(WINDOW) - 1) * 100
    out['kospi_vol20'] = kospi_ret.rolling(WINDOW, min_periods=WINDOW).std() * np.sqrt(ANNUAL_DAYS) * 100
    out['usdkrw_trend20'] = (fx / fx.shift(WINDOW) - 1) * 100
    out['us10y_level'] = m['us_treasury_10y']
    out['wti_level'] = m['wti']
    out['vix_level'] = m['vix']
    out['kr3y_level'] = m['korea_3y']
    out['kr3y_change20_bp'] = (m['korea_3y'] - m['korea_3y'].shift(WINDOW)) * 100

    # 사용한 관측일. 20거래일 전 값을 쓴 피처는 그 관측일도 남깁니다.
    for col in OBS_DATES:
        out[col] = m[col]
    out['usdkrw_observation_date_t20'] = m['usdkrw_observation_date'].shift(WINDOW)
    out['korea_3y_observation_date_t20'] = m['korea_3y_observation_date'].shift(WINDOW)

    # 기준 시각: 사용한 요인의 공개 시각이 모두 확인된 경우에만 채웁니다. 추정해서 채우지 않습니다.
    known = m[AVAIL].notna().all(axis=1)
    out['as_of_available_at'] = m[AVAIL].max(axis=1).where(known)
    out['point_in_time_verified'] = known
    return out


# ---------------------------------------------------------------- 종목 피처
def build_asset_features(df: pd.DataFrame, market_state: pd.DataFrame, usable: pd.Series) -> pd.DataFrame:
    calendar = pd.Index(market_state['trading_date'])
    px = df['close'].where(usable & (df['close'] > 0))          # 제외 사유가 있는 행의 종가는 수익률에서 뺍니다
    wide = (pd.DataFrame({'trading_date': df['trading_date'], 'asset_id': df['asset_id'], 'px': px})
            .pivot(index='trading_date', columns='asset_id', values='px')
            .reindex(calendar))                                  # 거래일 달력 × 종목. 결측은 NaN으로 남김
    log_ret = 100 * np.log(wide / wide.shift(1))                 # 종목 열마다 독립. 종목 사이 혼합 없음
    vols = {'asset_vol20': log_ret.rolling(WINDOW, min_periods=WINDOW).std(),
            'asset_vol60': log_ret.rolling(LONG_WINDOW, min_periods=LONG_WINDOW).std()}

    base = df[['dataset_version', 'trading_date', 'asset_id', 'instrument_kind', 'quality_status']].copy()
    base['row_usable'] = usable.to_numpy()
    for name, w in vols.items():
        w = w.copy()
        w.index.name, w.columns.name = 'trading_date', 'asset_id'
        long = w.reset_index().melt(id_vars='trading_date', var_name='asset_id', value_name=name)
        base = base.merge(long, on=['trading_date', 'asset_id'], how='left', validate='one_to_one')
    base = base.merge(market_state[['trading_date'] + MARKET_FEATURES + ['feature_version', 'point_in_time_verified']],
                      on='trading_date', how='left', validate='many_to_one')
    return base.sort_values(['trading_date', 'asset_id']).reset_index(drop=True)


# ---------------------------------------------------------------- 진입점
def _state_hash(ms: pd.DataFrame) -> str:
    text = ms[['trading_date'] + MARKET_FEATURES].to_csv(index=False, float_format='%.10g', date_format='%Y-%m-%d')
    return hashlib.sha256(text.encode('utf8')).hexdigest()


def build_features(df: pd.DataFrame, *, exclude_scopes=('asset_row',), source: str | None = None) -> FeatureSet:
    """load_gold가 반환한 표에서 피처를 계산합니다. 입력은 dataset_version 하나여야 합니다."""
    if df['dataset_version'].nunique() != 1:
        raise ValueError('dataset_version이 하나가 아닙니다. load_gold(dataset_version=...)로 선택하세요.')
    mock_rows = int(df['is_mock'].sum())
    df = df[~df['is_mock']].reset_index(drop=True)               # mock은 학습에서 제외
    if df.duplicated(['trading_date', 'asset_id']).any():
        raise ValueError('(trading_date, asset_id) 중복이 있습니다.')

    exclusions = exclusion_table(df)
    usable = usable_mask(df, exclusions, scopes=exclude_scopes)
    market_state = build_market_state(df)
    asset_features = build_asset_features(df, market_state, usable)

    verified = int(market_state['point_in_time_verified'].sum())
    meta = {
        'feature_version': FEATURE_VERSION,
        'created_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'dataset_version': str(df['dataset_version'].iloc[0]),
        'adjustment_versions': sorted(df['adjustment_version'].dropna().unique().tolist()),
        'source': source,
        'rows': int(len(asset_features)), 'dates': int(len(market_state)), 'assets': int(df['asset_id'].nunique()),
        'start': str(market_state['trading_date'].min())[:10], 'end': str(market_state['trading_date'].max())[:10],
        'calendar': 'Gold에 있는 한국 거래일(종목 합집합). 채우거나 다시 만들지 않음',
        'max_calendar_gap_days': int(market_state['trading_date'].diff().dt.days.max()),
        'windows': {'short': WINDOW, 'long': LONG_WINDOW, 'annualization_days': ANNUAL_DAYS},
        'features': FEATURE_SPEC,
        'alignment': ('Gold가 연결한 이전 관측일 값(연구 파일은 최대 7일, 거래일 이전). '
                      '공표 일정 추정에 따른 추가 지연 연구 옵션은 적용하지 않음'),
        'point_in_time': {'verified_dates': verified, 'total_dates': int(len(market_state)),
                          'status': 'verified' if verified == len(market_state) else 'unverified_research'},
        'mock_rows_dropped': mock_rows,
        'asset_rows_excluded_from_returns': int((~usable).sum()),
        'excluded_scopes': list(exclude_scopes),
        'first_valid_date': {f: (str(market_state.loc[market_state[f].notna(), 'trading_date'].min())[:10]
                                 if market_state[f].notna().any() else None) for f in MARKET_FEATURES},
        'non_null_counts': {**{f: int(market_state[f].notna().sum()) for f in MARKET_FEATURES},
                            **{f: int(asset_features[f].notna().sum()) for f in ASSET_FEATURES}},
        'market_state_sha256': _state_hash(market_state),
    }
    return FeatureSet(market_state, asset_features, meta)


def write_features(fs: FeatureSet, out_dir) -> dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = {'market_state': out / 'market_state.parquet', 'asset_features': out / 'asset_features.parquet',
             'metadata': out / 'features_metadata.json'}
    fs.market_state.to_parquet(paths['market_state'], index=False)
    fs.asset_features.to_parquet(paths['asset_features'], index=False)
    paths['metadata'].write_text(json.dumps(fs.meta, ensure_ascii=False, indent=2) + '\n', encoding='utf8')
    return {k: str(v) for k, v in paths.items()}


def main(argv=None):
    p = argparse.ArgumentParser(description='시장 상태와 종목 피처 계산')
    p.add_argument('source', nargs='?', default=str(DEFAULT_SOURCE),
                   help='Gold Parquet/Delta (생략하면 data/dev_gold/gold_stress_daily.parquet)')
    p.add_argument('--out', default=str(DEFAULT_OUT), help='저장 폴더 (기본: analytics/outputs/features)')
    p.add_argument('--strict', action='store_true', help='공개 시각이 NULL이면 중단')
    a = p.parse_args(argv)
    df = load_gold(a.source, strict=a.strict)
    fs = build_features(df, source=a.source)
    paths = write_features(fs, a.out)
    print(json.dumps({'files': paths, 'rows': fs.meta['rows'], 'dates': fs.meta['dates'],
                      'point_in_time': fs.meta['point_in_time'], 'first_valid_date': fs.meta['first_valid_date'],
                      'market_state_sha256': fs.meta['market_state_sha256']}, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
