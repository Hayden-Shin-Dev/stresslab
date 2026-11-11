"""B 모델: 시장 상태 X와 충격 S로 종목 5거래일 수익률의 분포를 만듭니다. (analytics/README.md 9절)

기존 로컬 연구의 Ridge(analytics/validation/20261103/reference, 브랜치 origin/5dt024/ml)를 같은 수식으로
옮긴 비교용 연구 모델입니다. 승인된 모델이 아닙니다. 옮긴 항목은 아래와 같습니다.

  입력 순서   충격 4개(환율, 미국 10년, WTI, VIX) + 상태 6개(kospi_vol20, kospi_trend20, vix_level,
              us10y_level, usdkrw_trend20, wti_level)
  충격 정규화 충격 4개를 max(scale_kospi, 0.05)로 나눔
  정답 정규화 종목 a의 정답을 max(scale_a, 0.05)로 나누어 학습하고, 예측에 scale_a를 다시 곱함
  변동성 척도 scale = sqrt((var20 + var60) / 2 * 5)   (일간 로그수익률 %의 분산, 5는 horizon)
  모델       StandardScaler + Ridge(alpha=30), 종목마다 하나
  보정       보정 구간 잔차(정규화 단위). Ridge는 위/아래 척도가 모두 1
  표본       잔차 행을 균등 간격으로 최대 400개 뽑아 중심값에 더함

기존과 다른 점 (의도한 변경):
  * 기존 PerAssetRidge는 종목마다 자기 잔차에서 따로 균등 간격 인덱스를 뽑았습니다. 종목별 보정 날짜가 다르면
    같은 날짜의 잔차가 아닌 것끼리 묶입니다. 여기서는 잔차를 (날짜 x 종목) 표로 두고 요청한 종목이 모두 있는
    날짜만 골라 같은 날짜의 잔차 행을 통째로 씁니다.
  * 결합 표본이 부족하면 joint_sample_status='insufficient'로 표시하고 종목별 독립 표본으로 대체했음을 남깁니다.
    이 경우 draw_id는 종목 사이에서 대응하지 않으므로 포트폴리오 합산에 쓰면 안 됩니다.

학습 구간: 학습/보정/평가 분리는 splits.py가 정합니다. 이 모듈은 구간을 직접 정하지 않습니다.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

MODEL_VERSION = 'ridge-scaled-v1.0'
REFERENCE = 'origin/5dt024/ml: analytics/validation/20261103/reference/stresslab (models.py, models_v2.py, point_in_time_daily.py)'
SHOCK_ORDER = ['shock_usdkrw_pct', 'shock_us10y_bp', 'shock_wti_pct', 'shock_vix_pt']
STATE_ORDER = ['kospi_vol20', 'kospi_trend20', 'vix_level', 'us10y_level', 'usdkrw_trend20', 'wti_level']
INPUT_ORDER = SHOCK_ORDER + STATE_ORDER
COLUMN_MAP_TO_REFERENCE = {
    'shock_usdkrw_pct': 's_usdkrw', 'shock_us10y_bp': 's_us_treasury_10y', 'shock_wti_pct': 's_wti',
    'shock_vix_pt': 's_vix', 'us10y_level': 'us_yield_level', 'usdkrw_trend20': 'fx_trend20',
    'wti_level': 'oil_level', 'kospi_vol20': 'kospi_vol20 (단, 우리 값은 연율화한 단순수익률 변동성)',
    'kospi_trend20': 'kospi_trend20', 'vix_level': 'vix_level'}
ECOS_ORDER = ['kr3y_level', 'kr3y_change20_bp']
# 11절 비교 실험용 변형. 기본(state_ridge)은 B 모델과 같습니다.
VARIANTS = {
    'volatility': {'input_columns': None, 'mode': 'median', 'label': '단순 변동성 기준(입력 없음, 학습 중앙값)'},
    'shock_only': {'input_columns': SHOCK_ORDER, 'mode': 'ridge', 'label': '충격만 사용'},
    'state_ridge': {'input_columns': INPUT_ORDER, 'mode': 'ridge', 'label': '일별 상태와 충격 사용(B 모델)'},
    'state_ecos_ridge': {'input_columns': INPUT_ORDER + ECOS_ORDER, 'mode': 'ridge', 'label': '일별 상태와 충격 + ECOS(국고채 3년)'},
}
ALPHA = 30.0
SCALE_FLOOR = 0.05
SCALE_HORIZON = 5
MAX_DRAWS = 400
MIN_ASSET_TRAIN_ROWS = 250      # 기존 검증의 적격 기준
MIN_ASSET_CAL_ROWS = 30
MIN_JOINT_ROWS = 30
QUANTILE_LEVELS = [0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99]


# ---------------------------------------------------------------- 변동성 척도
def asset_scale(vol20, vol60, horizon: int = SCALE_HORIZON):
    """sqrt((var20 + var60)/2 * horizon). vol은 일간 로그수익률(%)의 표준편차(ddof=1)."""
    v20, v60 = np.asarray(vol20, dtype=float), np.asarray(vol60, dtype=float)
    return np.sqrt((v20 ** 2 + v60 ** 2) / 2 * horizon)


def kospi_scale_table(market: pd.DataFrame, horizon: int = SCALE_HORIZON) -> pd.DataFrame:
    """KOSPI 지수의 날짜별 scale_kospi. market: features.market_table 결과(trading_date, kospi_close).

    기존 scale_kospi와 같은 정의입니다(일간 로그수익률 %, 20일/60일 분산, ddof=1, 창이 모두 찰 때만).
    t 이전 종가만 쓰므로 t 시점 정보입니다.
    """
    m = market[['trading_date', 'kospi_close']].sort_values('trading_date').reset_index(drop=True)
    px = m['kospi_close'].where(m['kospi_close'] > 0)
    r = 100 * np.log(px / px.shift(1))
    var20, var60 = r.rolling(20, min_periods=20).var(), r.rolling(60, min_periods=60).var()
    out = pd.DataFrame({'trading_date': m['trading_date']})
    out['scale_kospi'] = np.sqrt((var20 + var60) / 2 * horizon)
    return out


def with_scales(samples: pd.DataFrame, kospi_scale: pd.DataFrame) -> pd.DataFrame:
    """샘플 표에 scale_kospi와 종목별 asset_scale을 붙입니다."""
    d = samples.merge(kospi_scale, on='trading_date', how='left', validate='many_to_one')
    d['asset_scale'] = asset_scale(d['asset_vol20'], d['asset_vol60'])
    return d


def _floor(x):
    return np.maximum(np.asarray(x, dtype=float), SCALE_FLOOR)


# ---------------------------------------------------------------- 보정 날짜 선택
def nonoverlapping_dates(dates: pd.Series, target_dates: pd.Series) -> pd.DatetimeIndex:
    """기존 검증처럼 정답 구간이 겹치지 않게 날짜를 앞에서부터 고릅니다(다음 날짜 > 직전 선택일의 target_date)."""
    t = (pd.DataFrame({'d': dates, 'e': target_dates}).dropna().drop_duplicates('d')
         .sort_values('d').reset_index(drop=True))
    keep, last_end = [], None
    for d, e in zip(t['d'], t['e']):
        if last_end is None or d > last_end:
            keep.append(d)
            last_end = e
    return pd.DatetimeIndex(keep)


class _ConstantMedian:
    """입력과 무관하게 학습 정답(정규화 단위)의 중앙값을 내는 기준 모델."""

    def __init__(self, y):
        self.value = float(np.median(np.asarray(y, dtype=float)))

    def predict(self, x):
        return np.full(len(x), self.value)


# ---------------------------------------------------------------- 모델
class ScaledRidgeModel:
    def __init__(self, alpha: float = ALPHA, max_draws: int = MAX_DRAWS, min_joint_rows: int = MIN_JOINT_ROWS,
                 input_columns=None, mode: str = 'ridge'):
        assert mode in ('ridge', 'median')
        self.alpha, self.max_draws, self.min_joint_rows = alpha, max_draws, min_joint_rows
        self.input_columns = list(input_columns or INPUT_ORDER)
        self.mode = mode
        self.models: dict = {}
        self.residuals: pd.DataFrame | None = None     # 날짜 x 종목, 정규화 단위
        self.card: dict = {}

    @property
    def required_columns(self) -> list:
        base = ['asset_scale', 'y_log_return_5d']
        return base if self.mode == 'median' else self.input_columns + ['scale_kospi'] + base

    # 입력 행렬: 충격 열은 scale_kospi로 나눕니다. median 모드는 입력을 쓰지 않습니다.
    def inputs(self, frame: pd.DataFrame) -> np.ndarray:
        if self.mode == 'median':
            return np.zeros((len(frame), 1))
        x = frame[self.input_columns].to_numpy(dtype=float).copy()
        shock = np.array([c.startswith('shock_') for c in self.input_columns])
        x[:, shock] /= _floor(frame['scale_kospi'].to_numpy())[:, None]
        return x

    def fit(self, train: pd.DataFrame):
        d = train.dropna(subset=self.required_columns)
        self.card['train_rows_dropped_missing_scale_or_input'] = int(len(train) - len(d))
        self.models, ineligible = {}, {}
        for a, g in d.groupby('asset_id', sort=True):
            if len(g) < MIN_ASSET_TRAIN_ROWS:
                ineligible[a] = f'train_rows<{MIN_ASSET_TRAIN_ROWS} ({len(g)})'
                continue
            y = g['y_log_return_5d'].to_numpy(float) / _floor(g['asset_scale'].to_numpy())
            if self.mode == 'median':
                self.models[a] = _ConstantMedian(y)
            else:
                self.models[a] = make_pipeline(StandardScaler(), Ridge(alpha=self.alpha)).fit(self.inputs(g), y)
        self.card['input_columns'] = None if self.mode == 'median' else self.input_columns
        self.card['mode'] = self.mode
        self.card['train_rows_per_asset'] = {a: int(n) for a, n in d.groupby('asset_id').size().items()}
        self.card['ineligible_assets'] = ineligible
        self.card['train_range'] = {c: [float(d[c].min()), float(d[c].max())] for c in SHOCK_ORDER}
        self.card['train_range_basis'] = '학습 구간 충격의 최소/최대'
        self.train_shocks = d[SHOCK_ORDER].to_numpy(float)
        self.card['train_start'] = str(d['trading_date'].min())[:10]
        self.card['train_end'] = str(d['trading_date'].max())[:10]
        return self

    def calibrate(self, cal: pd.DataFrame, nonoverlap: bool = True):
        d = cal.dropna(subset=self.required_columns)
        d = d[d['asset_id'].isin(self.models)]
        if nonoverlap:
            keep = nonoverlapping_dates(d['trading_date'], d['target_date'])
            d = d[d['trading_date'].isin(keep)]
        cols = {}
        for a, g in d.groupby('asset_id', sort=True):
            if len(g) < MIN_ASSET_CAL_ROWS:
                self.card['ineligible_assets'][a] = f'calibration_rows<{MIN_ASSET_CAL_ROWS} ({len(g)})'
                continue
            z = g['y_log_return_5d'].to_numpy(float) / _floor(g['asset_scale'].to_numpy())
            center = self.models[a].predict(self.inputs(g))
            cols[a] = pd.Series(z - center, index=pd.DatetimeIndex(g['trading_date']))
        self.residuals = pd.DataFrame(cols).sort_index()
        self.models = {a: m for a, m in self.models.items() if a in self.residuals.columns}
        self.card['calibration'] = {
            'nonoverlapping_windows': bool(nonoverlap), 'dates': int(len(self.residuals)),
            'start': str(self.residuals.index.min())[:10], 'end': str(self.residuals.index.max())[:10],
            'rows_per_asset': {a: int(self.residuals[a].notna().sum()) for a in self.residuals.columns},
            'scale_up_down': [1.0, 1.0], 'note': 'Ridge는 위/아래 보정 척도가 모두 1(기존과 동일)'}
        return self

    @property
    def assets(self) -> list:
        return sorted(self.models)

    def joint_rows(self, assets) -> pd.DataFrame:
        """요청한 종목이 모두 있는 보정 날짜의 잔차 행."""
        return self.residuals[list(assets)].dropna()

    def draws(self, query: pd.Series, scales: pd.Series, assets=None) -> tuple[pd.DataFrame, dict]:
        """한 개 쿼리의 로그수익률(%) 표본. 반환: (draws[draw_id x 종목], 정보).

        query: INPUT_ORDER 열과 scale_kospi가 있는 한 행. scales: 종목별 asset_scale(예측 시점 값).
        """
        assets = list(self.assets if assets is None else assets)
        missing = [a for a in assets if a not in self.models]
        if missing:
            raise KeyError(f'모델이 없는 종목: {missing}')
        x = self.inputs(pd.DataFrame([query]))
        center = pd.Series({a: float(self.models[a].predict(x)[0]) for a in assets})
        joint = self.joint_rows(assets)
        info = {'assets': assets, 'joint_rows': int(len(joint))}
        if len(joint) >= self.min_joint_rows:
            ids = np.linspace(0, len(joint) - 1, min(self.max_draws, len(joint))).astype(int)
            z = joint.iloc[ids]
            info.update(joint_sample_status='ok', draw_basis='same_date_joint_residual_rows',
                        residual_dates=[str(t)[:10] for t in z.index])
            norm = z.to_numpy() + center.to_numpy()[None, :]
        else:
            info.update(joint_sample_status='insufficient', draw_basis='per_asset_marginal_residuals',
                        residual_dates=None,
                        warning=(f'요청 종목이 모두 있는 보정 날짜가 {len(joint)}개로 {self.min_joint_rows}개 미만입니다. '
                                 '종목별 독립 잔차로 대체했으므로 draw_id가 종목 사이에서 대응하지 않습니다. 합산에 쓰지 마세요.'))
            cols = []
            for a, c in zip(assets, center):
                r = self.residuals[a].dropna().to_numpy()
                ids = np.linspace(0, len(r) - 1, min(self.max_draws, len(r))).astype(int)
                cols.append(pd.Series(r[ids] + c))
            norm = pd.concat(cols, axis=1).to_numpy()
        out = norm * _floor(scales.reindex(assets).to_numpy(float))[None, :]
        return pd.DataFrame(out, columns=assets), {**info, 'center_log_return_pct':
                                                   {a: float(c * _floor(scales[a])) for a, c in center.items()}}

    # 저장/복원: 클래스 경로에 의존하는 피클을 피하려고 구성요소만 저장합니다.
    def to_state(self) -> dict:
        return {'version': MODEL_VERSION, 'alpha': self.alpha, 'max_draws': self.max_draws,
                'min_joint_rows': self.min_joint_rows, 'input_columns': self.input_columns, 'mode': self.mode,
                'models': self.models, 'residuals': self.residuals,
                'card': self.card, 'train_shocks': self.train_shocks}

    @classmethod
    def from_state(cls, s: dict):
        m = cls(s['alpha'], s['max_draws'], s['min_joint_rows'], s.get('input_columns'), s.get('mode', 'ridge'))
        m.models, m.residuals, m.card, m.train_shocks = s['models'], s['residuals'], s['card'], s['train_shocks']
        return m
