"""사용자 충격을 넣어 종목별 5거래일 수익률 분포를 만듭니다. (analytics/README.md 9절)

    python analytics/src/predict.py                       # 최신 상태 + 예시 충격(환율 +2%, 미국 10년 +50bp)
    python analytics/src/predict.py --as-of 2026-10-30 --usdkrw 5 --us10y 100
    -> analytics/outputs/predict/{prediction_samples.csv, prediction_quantiles.csv, prediction_meta.json}

사용자가 지정하지 않은 충격은 0으로 두며, 어떤 충격을 0으로 가정했는지 prediction_meta.json의 shocks.assumed_zero에 남깁니다.
관측된 과거 사실(observed)과 모델 추정(model_estimate)은 파일 안에서 구분해 둡니다.
모델은 요청마다 다시 학습하지 않습니다(train.py가 만든 model.joblib를 읽음).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

try:
    from distribution import (INPUT_ORDER, MODEL_VERSION, QUANTILE_LEVELS, SHOCK_ORDER, STATE_ORDER, ScaledRidgeModel,
                              asset_scale)
    from features import ANALYTICS_ROOT
    from targets import to_simple_return_pct
except ImportError:  # 패키지로 가져올 때
    from .distribution import (INPUT_ORDER, MODEL_VERSION, QUANTILE_LEVELS, SHOCK_ORDER, STATE_ORDER, ScaledRidgeModel,
                               asset_scale)
    from .features import ANALYTICS_ROOT
    from .targets import to_simple_return_pct

MODEL_DIR = ANALYTICS_ROOT / 'outputs/model'
FEATURE_DIR = ANALYTICS_ROOT / 'outputs/features'
DEFAULT_OUT = ANALYTICS_ROOT / 'outputs/predict'
SHOCK_KEYS = {'usdkrw_pct': 'shock_usdkrw_pct', 'us10y_bp': 'shock_us10y_bp',
              'wti_pct': 'shock_wti_pct', 'vix_pt': 'shock_vix_pt'}
SHOCK_UNITS = {'usdkrw_pct': '%', 'us10y_bp': 'bp', 'wti_pct': '%', 'vix_pt': '지수 차이'}
EXAMPLE_SHOCKS = {'usdkrw_pct': 2.0, 'us10y_bp': 50.0}


def load_model(model_dir=MODEL_DIR):
    d = Path(model_dir)
    return (ScaledRidgeModel.from_state(joblib.load(d / 'model.joblib')),
            json.loads((d / 'model_card.json').read_text(encoding='utf8')),
            pd.read_parquet(d / 'market_scale.parquet'))


def resolve_shocks(user: dict | None) -> tuple[dict, dict]:
    """사용자 충격을 모델 열 이름으로 바꿉니다. 지정하지 않은 충격은 0. 반환: (모델 열 값, 설명)."""
    user = {k: v for k, v in (user or {}).items() if v is not None}
    unknown = set(user) - set(SHOCK_KEYS)
    if unknown:
        raise KeyError(f'알 수 없는 충격: {sorted(unknown)} (가능: {sorted(SHOCK_KEYS)})')
    if 'wti_pct' in user and user['wti_pct'] <= -100:
        raise ValueError('WTI 충격은 -100% 초과여야 합니다(가격이 0 이하가 되는 충격은 비율로 표현하지 않음).')
    values = {SHOCK_KEYS[k]: float(user.get(k, 0.0)) for k in SHOCK_KEYS}
    info = {'specified': {k: float(v) for k, v in user.items()},
            'assumed_zero': [k for k in SHOCK_KEYS if k not in user],
            'units': SHOCK_UNITS,
            'note': '지정하지 않은 충격은 0으로 가정했습니다.' if len(user) < len(SHOCK_KEYS) else '모든 충격을 사용자가 지정했습니다.'}
    return values, info


def range_check(model: ScaledRidgeModel, values: dict) -> dict:
    out = {}
    for i, col in enumerate(SHOCK_ORDER):
        lo, hi = model.card['train_range'][col]
        v = values[col]
        n_ge = int((np.abs(model.train_shocks[:, i]) >= abs(v)).sum()) if v != 0 else int(len(model.train_shocks))
        out[col] = {'value': v, 'train_min': lo, 'train_max': hi, 'in_train_range': bool(lo <= v <= hi),
                    'train_rows_with_abs_shock_at_least': n_ge}
    out['all_in_train_range'] = all(out[c]['in_train_range'] for c in SHOCK_ORDER)
    return out


def predict(model: ScaledRidgeModel, market_state: pd.DataFrame, asset_features: pd.DataFrame,
            kospi_scale: pd.DataFrame, shocks: dict | None, *, as_of=None, assets=None, card: dict | None = None):
    """반환: (samples 긴 표, quantiles 표, meta dict)."""
    ms = market_state.sort_values('trading_date')
    if as_of is None:
        ok = ms.dropna(subset=STATE_ORDER).merge(kospi_scale.dropna(), on='trading_date')
        as_of = ok['trading_date'].max()
    as_of = pd.Timestamp(as_of)
    row = ms[ms['trading_date'] == as_of]
    if row.empty:
        raise ValueError(f'{as_of.date()}는 시장 상태 표에 없는 거래일입니다.')
    row = row.iloc[0]
    state = row[STATE_ORDER]
    if state.isna().any():
        raise ValueError(f'{as_of.date()}의 상태 피처에 결측이 있습니다: {list(state.index[state.isna()])}')
    ks = kospi_scale.loc[kospi_scale['trading_date'] == as_of, 'scale_kospi']
    if ks.empty or pd.isna(ks.iloc[0]):
        raise ValueError(f'{as_of.date()}의 scale_kospi를 만들 수 없습니다(지수 종가 60거래일 필요).')

    af = asset_features[asset_features['trading_date'] == as_of].set_index('asset_id')
    wanted = list(model.assets if assets is None else assets)
    dropped = {}
    for a in list(wanted):
        if a not in model.models:
            dropped[a] = 'no_model'
        elif a not in af.index or not bool(af.loc[a, 'row_usable']) or af.loc[a, ['asset_vol20', 'asset_vol60']].isna().any():
            dropped[a] = 'asset_state_unavailable_at_as_of'
        if a in dropped:
            wanted.remove(a)
    if not wanted:
        raise ValueError('예측할 수 있는 종목이 없습니다.')
    scales = pd.Series({a: float(asset_scale(af.loc[a, 'asset_vol20'], af.loc[a, 'asset_vol60'])) for a in wanted})

    values, shock_info = resolve_shocks(shocks)
    query = pd.concat([pd.Series(values), state])[INPUT_ORDER]
    query['scale_kospi'] = float(ks.iloc[0])
    draws, info = model.draws(query, scales, wanted)

    simple = to_simple_return_pct(draws)
    dates = info.get('residual_dates')
    long = pd.DataFrame({
        'draw_id': np.repeat(np.arange(len(draws)), len(wanted)),
        'residual_date': np.repeat(dates, len(wanted)) if dates else None,
        'asset_id': np.tile(wanted, len(draws)),
        'log_return_pct': draws.to_numpy().ravel(),
        'simple_return_pct': simple.to_numpy().ravel()})
    q = simple.quantile(QUANTILE_LEVELS, interpolation='linear').T
    q.columns = [f'q{int(round(l * 100)):02d}' for l in QUANTILE_LEVELS]
    quant = q.reset_index(names='asset_id')
    quant.insert(1, 'center_simple_return_pct', [float(to_simple_return_pct(info['center_log_return_pct'][a])) for a in wanted])
    quant['n_draws'] = len(draws)

    meta = {
        'model_version': MODEL_VERSION, 'created_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'model_status': (card or {}).get('status', 'research_comparison_model_not_approved'),
        'reproduction_status': (card or {}).get('reproduction_status', 'code_equivalent_only'),
        'horizon_trading_days': 5,
        'observed': {   # 기준일까지 관측된 사실
            'state_as_of_trading_date': str(as_of)[:10],
            'as_of_available_at': None if pd.isna(row.get('as_of_available_at')) else str(row['as_of_available_at']),
            'point_in_time_verified': bool(row.get('point_in_time_verified', False)),
            'state': {k: float(v) for k, v in state.items()},
            'scale_kospi': float(ks.iloc[0]),
            'asset_scale': {a: float(v) for a, v in scales.items()}},
        'shocks': {**shock_info, 'applied_model_values': values, 'applicable_range': range_check(model, values)},
        'model_estimate': {   # 모델이 만든 값
            'return_definition': 'simple_return_pct = 100*(exp(log_return/100)-1), 5거래일',
            'quantile_levels': QUANTILE_LEVELS, 'quantile_method': 'numpy linear interpolation on draws',
            'n_draws': int(len(draws)), 'joint': {k: info[k] for k in
                                                ('joint_sample_status', 'draw_basis', 'joint_rows') if k in info},
            'joint_warning': info.get('warning'),
            'draws_share_residual_dates_across_assets': info['joint_sample_status'] == 'ok',
            'center_log_return_pct': info['center_log_return_pct']},
        'assets': wanted, 'assets_dropped': dropped,
        'warnings': [w for w in [info.get('warning'),
                                 None if shock_info['assumed_zero'] == [] else shock_info['note'],
                                 '공개 시각이 확인되지 않은 연구용 상태입니다.' if not bool(row.get('point_in_time_verified', False)) else None,
                                 None if range_check(model, values)['all_in_train_range'] else '입력 충격이 학습 충격 범위를 벗어납니다.']
                     if w],
    }
    return long, quant, meta


def write_prediction(long, quant, meta, out_dir) -> dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = {'samples': out / 'prediction_samples.csv', 'quantiles': out / 'prediction_quantiles.csv',
             'meta': out / 'prediction_meta.json'}
    long.to_csv(paths['samples'], index=False)
    quant.to_csv(paths['quantiles'], index=False)
    paths['meta'].write_text(json.dumps(meta, ensure_ascii=False, indent=2, default=str) + '\n', encoding='utf8')
    return {k: str(v) for k, v in paths.items()}


def main(argv=None):
    p = argparse.ArgumentParser(description='사용자 충격으로 종목 수익률 분포 만들기')
    p.add_argument('--model-dir', default=str(MODEL_DIR))
    p.add_argument('--features-dir', default=str(FEATURE_DIR))
    p.add_argument('--out', default=str(DEFAULT_OUT))
    p.add_argument('--as-of', default=None, help='기준 거래일 (생략하면 상태가 완성된 최신 거래일)')
    p.add_argument('--assets', nargs='*', default=None)
    for k, unit in SHOCK_UNITS.items():
        p.add_argument('--' + k.split('_')[0], dest=k, type=float, default=None, help=f'{k} 충격 ({unit}); 생략하면 0 가정'.replace('%', '%%'))
    a = p.parse_args(argv)
    user = {k: getattr(a, k) for k in SHOCK_KEYS}
    if all(v is None for v in user.values()):
        user = dict(EXAMPLE_SHOCKS)
        print('충격을 지정하지 않아 예시 충격을 사용합니다:', user)
    model, card, scale = load_model(a.model_dir)
    fd = Path(a.features_dir)
    long, quant, meta = predict(model, pd.read_parquet(fd / 'market_state.parquet'),
                                pd.read_parquet(fd / 'asset_features.parquet'), scale, user,
                                as_of=a.as_of, assets=a.assets, card=card)
    paths = write_prediction(long, quant, meta, a.out)
    print(json.dumps({'files': paths, 'as_of': meta['observed']['state_as_of_trading_date'],
                      'assets': len(meta['assets']), 'joint': meta['model_estimate']['joint'],
                      'warnings': meta['warnings']}, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
