"""모델 D/E 공통: 입력 만들기, 구간 분리, 지표, 결과 저장. (기존 파일은 수정하지 않음)

분리는 기존 프로젝트 설정을 그대로 씁니다: 학습 <2020, 보정 2020~2022, 시험 2023~.
정답 종료일이 다음 구간에 걸치는 행은 splits.assign_splits가 제외(purge)합니다. 20일은 제외 폭이 더 큽니다.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ANALYTICS_ROOT = HERE.parent
sys.path.insert(0, str(ANALYTICS_ROOT / 'src'))
sys.path.insert(0, str(HERE))
from distribution import INPUT_ORDER, MIN_ASSET_TRAIN_ROWS, SHOCK_ORDER, _floor, asset_scale, kospi_scale_table  # noqa: E402
from features import build_features, market_table  # noqa: E402
from horizon_samples import S_COLUMNS, build_horizon_samples, y_column  # noqa: E402
from splits import assign_splits, select_split  # noqa: E402

VERSION = 'model-de-v1.0'
SEED = 20261105
OUT = ANALYTICS_ROOT / 'outputs/model_de'
HORIZONS = (1, 5, 20)
LEVELS = (0.80, 0.90, 0.95)
LEVEL_Q = {0.80: (0.10, 0.90), 0.90: (0.05, 0.95), 0.95: (0.025, 0.975)}     # 수준별 분위수 쌍
MIN_ASSET_ROWS = 100                                                         # 종목별 보정 최소 행


def lv(level: float) -> str:
    return f'{int(round(level * 100))}'


# ---------------------------------------------------------------- 입력
def design(frame: pd.DataFrame, cols=INPUT_ORDER) -> np.ndarray:
    """충격(shock_*)은 scale_kospi로 나누고 나머지는 그대로. 기존 ScaledRidgeModel.inputs와 같은 규칙."""
    scale = _floor(frame['scale_kospi'].to_numpy())
    out = []
    for c in cols:
        v = frame[c].to_numpy(float)
        out.append(v / scale if c.startswith('shock_') else v)
    return np.column_stack(out)


def load_inputs(gold: pd.DataFrame):
    clean = gold[~gold['is_mock']].reset_index(drop=True)
    fs = build_features(gold)
    market = market_table(clean)
    return clean, fs, market


class Context:
    """한 예측 기간(h)의 표본, 구간 분리, 정규화 척도."""

    def __init__(self, clean, fs, market, h: int):
        self.h, self.ycol = h, y_column(h)
        samples = build_horizon_samples(clean, fs, h)
        ks = kospi_scale_table(market, horizon=h)
        d = samples.merge(ks, on='trading_date', how='left', validate='many_to_one')
        d['asset_scale'] = asset_scale(d['asset_vol20'], d['asset_vol60'], h)
        self.all = d
        self.assign = assign_splits(samples, horizon=h)
        need = INPUT_ORDER + ['scale_kospi', 'asset_scale', self.ycol, 'target_date']
        usable = d.dropna(subset=need)
        self.train = select_split(usable, self.assign, 'train').reset_index(drop=True)
        self.cal = select_split(usable, self.assign, 'calibration').reset_index(drop=True)
        self.test = select_split(usable, self.assign, 'evaluation').reset_index(drop=True)
        n = self.train.groupby('asset_id').size()
        self.assets = sorted((set(n[n >= MIN_ASSET_TRAIN_ROWS].index) & set(self.cal['asset_id'])) & set(self.test['asset_id']))
        for name in ('train', 'cal', 'test'):
            df = getattr(self, name)
            setattr(self, name, df[df['asset_id'].isin(self.assets)].reset_index(drop=True))
        self.calendar = pd.Index(sorted(d['trading_date'].unique()))
        blocks = self.assign.set_index(['trading_date', 'asset_id'])['overlap_block']
        for name in ('train', 'cal', 'test'):
            df = getattr(self, name)
            df['overlap_block'] = blocks.reindex(pd.MultiIndex.from_frame(df[['trading_date', 'asset_id']])).to_numpy()
            df['row_pos'] = self.calendar.get_indexer(df['trading_date'])
            df['target_pos'] = self.calendar.get_indexer(df['target_date'])

    @property
    def y(self):
        return {n: getattr(self, n)[self.ycol].to_numpy(float) for n in ('train', 'cal', 'test')}

    def scale(self, frame):
        return _floor(frame['asset_scale'].to_numpy())

    def summary(self) -> dict:
        a = self.assign
        return {'horizon': self.h, 'assets': len(self.assets), 'assets_list': self.assets,
                'train_rows': int(len(self.train)), 'cal_rows': int(len(self.cal)), 'test_rows': int(len(self.test)),
                'train_period': [str(self.train['trading_date'].min())[:10], str(self.train['trading_date'].max())[:10]],
                'cal_period': [str(self.cal['trading_date'].min())[:10], str(self.cal['trading_date'].max())[:10]],
                'test_period': [str(self.test['trading_date'].min())[:10], str(self.test['trading_date'].max())[:10]],
                'test_independent_blocks': int(self.test['overlap_block'].nunique()),
                'purged_rows': int((a['split'] == 'purged').sum())}


# ---------------------------------------------------------------- 지표
def pinball(y, q, tau):
    d = np.asarray(y) - np.asarray(q)
    return float(np.mean(np.maximum(tau * d, (tau - 1) * d)))


def point_metrics(y, pred) -> dict:
    e = y - pred
    sst = float(np.sum((y - y.mean()) ** 2))
    nz = (y != 0) & (pred != 0)
    return {'mae': float(np.abs(e).mean()), 'rmse': float(np.sqrt((e ** 2).mean())), 'r2': float(1 - np.sum(e ** 2) / sst),
            'directional_accuracy': float((np.sign(y[nz]) == np.sign(pred[nz])).mean()) if nz.any() else float('nan')}


def interval_metrics(y, lo, hi, level) -> dict:
    a = 1 - level
    inside = (y >= lo) & (y <= hi)
    w = hi - lo
    iscore = w + (2 / a) * np.maximum(lo - y, 0) + (2 / a) * np.maximum(y - hi, 0)
    return {'coverage': float(inside.mean()), 'coverage_gap': float(inside.mean() - level), 'mean_width': float(w.mean()),
            'median_width': float(np.median(w)), 'interval_score': float(iscore.mean()),
            'pinball': float((pinball(y, lo, a / 2) + pinball(y, hi, 1 - a / 2)) / 2),
            'miss_below': float((y < lo).mean()), 'miss_above': float((y > hi).mean())}


# ---------------------------------------------------------------- 시장충격 유형(기준은 학습 구간 분포)
def regime_masks(train: pd.DataFrame, frame: pd.DataFrame) -> dict:
    q = {c: train[c].quantile([0.01, 0.10, 0.90, 0.99]).to_numpy() for c in SHOCK_ORDER}

    def lo(c): return frame[c] <= q[c][1]
    def hi(c): return frame[c] >= q[c][2]
    rate_up, rate_dn = hi('shock_us10y_bp'), lo('shock_us10y_bp')
    fx_up, fx_dn = hi('shock_usdkrw_pct'), lo('shock_usdkrw_pct')
    calm = pd.Series(True, index=frame.index)
    extreme = pd.Series(False, index=frame.index)
    for c in SHOCK_ORDER:
        calm &= (frame[c] > q[c][1]) & (frame[c] < q[c][2])
        extreme |= (frame[c] < q[c][0]) | (frame[c] > q[c][3])
    return {'all': pd.Series(True, index=frame.index), 'normal': calm, 'rate_up': rate_up, 'rate_down': rate_dn,
            'fx_up': fx_up, 'fx_down': fx_dn, 'rate_and_fx_both_large': (rate_up | rate_dn) & (fx_up | fx_dn),
            'extreme_any_shock': extreme}


REGIME_NOTE = ('기준은 학습 구간 충격 분포. 평상시=네 충격이 모두 10~90% 안, 급등/급락=상위/하위 10%, '
               '동시 변화=금리와 환율이 모두 상/하위 10%(방향 무관), 극단=어느 충격이든 학습 구간 1%/99% 밖')


def range_check(train: pd.DataFrame, shocks: dict) -> dict:
    """가상 충격이 학습 구간 범위 안인지. 반환: {충격: (값, 최소, 최대, 이탈 여부)}."""
    out = {}
    for c in SHOCK_ORDER:
        v = float(shocks.get(c, 0.0))
        lo_, hi_ = float(train[c].min()), float(train[c].max())
        out[c] = {'value': v, 'train_min': lo_, 'train_max': hi_, 'outside': bool(v < lo_ or v > hi_)}
    return out


# ---------------------------------------------------------------- 저장
def write_table(df: pd.DataFrame, path) -> str:
    """parquet(pyarrow가 있을 때) 아니면 같은 이름의 csv로 저장합니다."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        import pyarrow  # noqa: F401
        df.to_parquet(path, index=False)
        return str(path)
    except ImportError:
        p = path.with_suffix('.csv')
        df.to_csv(p, index=False, encoding='utf-8-sig')
        print(f'pyarrow가 없어 {p.name} 로 저장했습니다.')
        return str(p)


def read_table(path) -> pd.DataFrame:
    path = Path(path)
    if path.exists():
        return pd.read_parquet(path)
    alt = path.with_suffix('.csv')
    if alt.exists():
        return pd.read_csv(alt, parse_dates=[c for c in ['trading_date', 'target_date'] if c in pd.read_csv(alt, nrows=0).columns],
                           dtype={'asset_id': str}, encoding='utf-8-sig')
    raise FileNotFoundError(path)


class Timer:
    def __enter__(self):
        self.t = time.perf_counter()
        return self

    def __exit__(self, *a):
        self.seconds = time.perf_counter() - self.t
