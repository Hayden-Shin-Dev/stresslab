"""시장 상태 X, 실제 충격 S, 종목 정답 y를 연결한 학습 표를 만듭니다. (analytics/README.md 6절)

    python analytics/src/build_samples.py           # VS Code ▶ 실행도 같습니다
    -> analytics/outputs/samples/training_samples.parquet
       analytics/outputs/samples/samples_metadata.json

한 행은 기준일 t의 (날짜, 종목)입니다. 열은 세 그룹으로 나뉩니다.
  X  기준일 t까지의 정보만 쓴 상태 피처(시장 + 종목 변동성)
  S  t에서 t+5까지의 실제 시장 충격 (학습에서는 과거 충격, 서비스에서는 사용자 충격이 대신 들어감)
  y  t에서 t+5까지의 종목 로그수익률 정답
S와 y는 미래 값을 쓰므로 현재 상태 피처나 A(시장 검색)의 입력에 들어가면 안 됩니다.
split_xsy()로 그룹을 분리해서 쓰세요.

행은 지우지 않습니다. 학습에 쓸 수 없는 행은 exclude_reasons에 사유를 남기고 train_ready=False입니다.
마지막 5거래일처럼 정답이 없는 행, 필수 가격/충격 자료가 t~t+5 사이에 빠진 행, WTI가 0 이하인 행이 해당합니다.
인접한 날짜의 5거래일 구간은 서로 겹칩니다. 독립 사건으로 세지 않습니다. 시간 분리는 splits.py에서 다룹니다.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

try:
    from features import ANALYTICS_ROOT, ASSET_FEATURES, FEATURE_VERSION, MARKET_FEATURES, build_features
    from load_gold import DEFAULT_SOURCE, load_gold
    from targets import (HORIZON, OBS_COLUMNS, SHOCK_COLUMNS, TARGET_SPEC, TARGET_VERSION, Y_COLUMN,
                         build_asset_targets, build_market_shocks, join_reasons)
except ImportError:  # 패키지로 가져올 때
    from .features import ANALYTICS_ROOT, ASSET_FEATURES, FEATURE_VERSION, MARKET_FEATURES, build_features
    from .load_gold import DEFAULT_SOURCE, load_gold
    from .targets import (HORIZON, OBS_COLUMNS, SHOCK_COLUMNS, TARGET_SPEC, TARGET_VERSION, Y_COLUMN,
                          build_asset_targets, build_market_shocks, join_reasons)

DEFAULT_OUT = ANALYTICS_ROOT / 'outputs/samples'
KEY_COLUMNS = ['trading_date', 'asset_id']
X_COLUMNS = MARKET_FEATURES + ASSET_FEATURES
S_COLUMNS = list(SHOCK_COLUMNS)
Y_COLUMNS = [Y_COLUMN]
assert not set(X_COLUMNS) & set(S_COLUMNS + Y_COLUMNS), 'X에 미래 값(S, y) 이름이 섞였습니다.'

SAMPLE_COLUMNS = (['dataset_version', 'feature_version', 'target_version', 'trading_date', 'target_date', 'asset_id']
                  + X_COLUMNS + S_COLUMNS + Y_COLUMNS + OBS_COLUMNS
                  + ['point_in_time_verified', 'row_usable', 'exclude_reasons', 'train_ready'])


def build_samples(df: pd.DataFrame, fs=None, *, require_complete_interval: bool = True):
    """load_gold가 반환한 표에서 학습 표를 만듭니다. 반환: (samples, meta)."""
    fs = fs or build_features(df)
    clean = df[~df['is_mock']].reset_index(drop=True)          # build_features와 같은 입력(mock 제외)
    af = fs.asset_features
    rows = clean[['dataset_version', 'trading_date', 'asset_id', 'close']].merge(
        af[KEY_COLUMNS + ['row_usable', 'point_in_time_verified'] + X_COLUMNS],
        on=KEY_COLUMNS, how='left', validate='one_to_one')
    assert len(rows) == len(af) and rows['row_usable'].notna().all(), 'features와 Gold의 행이 맞지 않습니다.'

    shocks = build_market_shocks(clean)
    targets = build_asset_targets(rows, fs.market_state['trading_date'])
    s = (rows.drop(columns=['close'])
         .merge(targets, on=KEY_COLUMNS, how='left', validate='one_to_one')
         .merge(shocks, on='trading_date', how='left', validate='many_to_one'))

    flags = {
        'no_horizon': s['flag_no_horizon'],
        'state_incomplete': s[X_COLUMNS].isna().any(axis=1),
        'price_unusable_t': s['flag_price_unusable_t'],
        'price_unusable_t5': s['flag_price_unusable_t5'],
    }
    if require_complete_interval:
        flags['price_interval_gap'] = s['flag_price_interval_gap']
    flags.update({'shock_endpoint_missing': s['flag_shock_endpoint_missing'],
                  'wti_nonpositive': s['flag_wti_nonpositive'],
                  'shock_interval_gap': s['flag_shock_interval_gap']})
    s['exclude_reasons'] = join_reasons(flags, s.index)
    s['train_ready'] = s['exclude_reasons'].eq('')
    s['feature_version'], s['target_version'] = FEATURE_VERSION, TARGET_VERSION
    samples = s[SAMPLE_COLUMNS].sort_values(KEY_COLUMNS).reset_index(drop=True)

    ready = samples[samples['train_ready']]
    assert not ready[X_COLUMNS + S_COLUMNS + Y_COLUMNS].isna().any().any(), 'train_ready 행에 결측이 있습니다.'

    reasons = samples.loc[~samples['train_ready'], 'exclude_reasons'].str.split(';').explode()
    span = {f: {k: (None if ready[f'{f}_obs_span_days'].dropna().empty else float(v))
                for k, v in ready[f'{f}_obs_span_days'].astype(float).agg(['min', 'median', 'max']).items()}
            for f in ['usdkrw', 'us_treasury_10y', 'wti', 'vix']}
    meta = {
        'target_version': TARGET_VERSION, 'feature_version': FEATURE_VERSION,
        'created_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'dataset_version': fs.meta['dataset_version'], 'adjustment_versions': fs.meta['adjustment_versions'],
        'market_state_sha256': fs.meta['market_state_sha256'],
        'horizon_trading_days': HORIZON,
        'calendar': 'Gold에 있는 한국 거래일. t+5는 달력 행 기준이며 달력상 5일이나 종목의 다음 5개 유효 행이 아님',
        'rows': int(len(samples)), 'train_ready_rows': int(len(ready)),
        'assets': int(samples['asset_id'].nunique()),
        'train_ready_start': str(ready['trading_date'].min())[:10] if len(ready) else None,
        'train_ready_end': str(ready['trading_date'].max())[:10] if len(ready) else None,
        'exclude_reason_counts': {k: int(v) for k, v in reasons.value_counts().items()},
        'require_complete_interval': require_complete_interval,
        'columns': {'key': KEY_COLUMNS, 'x': X_COLUMNS, 's': S_COLUMNS, 'y': Y_COLUMNS, 'observation': OBS_COLUMNS},
        'definitions': TARGET_SPEC,
        'shock_start_values': 'Gold가 t에 연결한 관측값. 상태 계산용 별도 공표 지연 값으로 바꾸지 않음',
        'observation_span_days_train_ready': span,
        'notes': [
            'S와 y는 t+5 값을 쓰므로 현재 상태 피처나 시장 검색(A)의 입력에 쓰지 않는다.',
            '미국 관측 구간은 한국 종가 구간과 같지 않다. *_obs_start/_obs_end/_obs_span_days로 실제 관측일을 확인한다.',
            '인접 날짜의 5거래일 구간은 겹친다. 독립 사건 수와 행 수를 구분한다.',
            '학습 정답과 충격은 연구용 연결 데이터이며 공개 시각이 NULL이면 시점 검증이 끝난 자료가 아니다.',
        ],
        'point_in_time': fs.meta['point_in_time'],
    }
    return samples, meta


def split_xsy(samples: pd.DataFrame, train_only: bool = True):
    """(X, S, y)로 분리합니다. 검색과 상태 입력에는 X만 넘기세요."""
    d = samples[samples['train_ready']] if train_only else samples
    return d[KEY_COLUMNS + X_COLUMNS], d[KEY_COLUMNS + S_COLUMNS], d[KEY_COLUMNS + Y_COLUMNS]


def write_samples(samples: pd.DataFrame, meta: dict, out_dir) -> dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = {'samples': out / 'training_samples.parquet', 'metadata': out / 'samples_metadata.json'}
    samples.to_parquet(paths['samples'], index=False)
    paths['metadata'].write_text(json.dumps(meta, ensure_ascii=False, indent=2) + '\n', encoding='utf8')
    return {k: str(v) for k, v in paths.items()}


def main(argv=None):
    p = argparse.ArgumentParser(description='X, S, y 학습 표 생성')
    p.add_argument('source', nargs='?', default=str(DEFAULT_SOURCE),
                   help='Gold Parquet/Delta (생략하면 data/dev_gold/gold_stress_daily.parquet)')
    p.add_argument('--out', default=str(DEFAULT_OUT), help='저장 폴더 (기본: analytics/outputs/samples)')
    p.add_argument('--strict', action='store_true', help='공개 시각이 NULL이면 중단')
    p.add_argument('--allow-interval-gap', action='store_true',
                   help='t~t+5 사이 종목 가격이 빠져도 끝점이 있으면 학습 가능으로 둠(기본은 제외)')
    a = p.parse_args(argv)
    df = load_gold(a.source, strict=a.strict)
    samples, meta = build_samples(df, require_complete_interval=not a.allow_interval_gap)
    paths = write_samples(samples, meta, a.out)
    print(json.dumps({'files': paths, 'rows': meta['rows'], 'train_ready_rows': meta['train_ready_rows'],
                      'train_ready_period': [meta['train_ready_start'], meta['train_ready_end']],
                      'exclude_reason_counts': meta['exclude_reason_counts']}, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
