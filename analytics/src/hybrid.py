"""Ridge + LightGBM 결합 모델과 롤링 검증. (분포 모델의 '중심값'을 어떻게 만들지 비교)

    python analytics/src/hybrid.py        # VS Code ▶ 실행, 인자 없음
    -> analytics/outputs/hybrid/{fold_metrics.csv, summary.csv, paired_vs_ridge.csv, hybrid_summary.json}

비교하는 중심값(모두 정규화 단위의 y, 즉 y / asset_scale 을 예측)
  volatility   입력 없음. 학습 중앙값(기준선)
  ridge        종목별 Ridge(현재 B 모델의 충격+상태 10개)
  gbm          전 종목을 합쳐 학습한 LightGBM
  blend        w * ridge + (1-w) * gbm
  residual     Ridge를 먼저 쓰고, 남은 잔차를 LightGBM이 약하게 보정(ridge + shrink * gbm)

검증: 평가 구간(2023~)은 열지 않습니다. 연도 Y마다 'Y년 1월 1일 전에 정답이 끝난 행'으로 학습하고
Y년 행으로 검증합니다(롤링 오리진). 같은 행 집합에서 모델끼리 비교하고, 겹치는 5일 구간은
블록(달력 위치 // 5) 부트스트랩으로 불확실성을 봅니다.
LightGBM이 없으면 같은 계열인 scikit-learn HistGradientBoostingRegressor로 대신하고 그 사실을 결과에 남깁니다.
(설치: .venv 에서 `pip install lightgbm`)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ANALYTICS_ROOT = HERE.parent
sys.path.insert(0, str(HERE))
from distribution import ALPHA, INPUT_ORDER, SHOCK_ORDER, ScaledRidgeModel, _floor, with_scales  # noqa: E402
from splits import DEFAULT_SAMPLES  # noqa: E402

HYBRID_VERSION = 'hybrid-v1.0'
SEED = 20261105
DEFAULT_OUT = ANALYTICS_ROOT / 'outputs/hybrid'
FIRST_VALID_YEAR, LAST_VALID_YEAR = 2010, 2022          # 2023~ 평가 구간은 쓰지 않음
GBM_PARAMS = dict(n_estimators=200, learning_rate=0.03, num_leaves=7, min_child_samples=400, subsample=0.7,
                  subsample_freq=1, colsample_bytree=0.8, reg_lambda=10.0)
BLEND_WEIGHTS = (0.3, 0.5, 0.7)                         # ridge 비중
RESIDUAL_SHRINK = (0.5, 1.0)
VARIANTS_BASE = ['volatility', 'ridge', 'gbm']


def gbm_backend() -> str:
    try:
        import lightgbm  # noqa: F401
        return 'lightgbm'
    except ImportError:
        return 'sklearn_hist_gradient_boosting'


def make_gbm(seed: int = SEED, objective: str = 'l2'):
    p = GBM_PARAMS
    if gbm_backend() == 'lightgbm':
        import lightgbm as lgb
        return lgb.LGBMRegressor(objective='huber' if objective == 'huber' else 'regression', n_estimators=p['n_estimators'],
                                 learning_rate=p['learning_rate'], num_leaves=p['num_leaves'], min_child_samples=p['min_child_samples'],
                                 subsample=p['subsample'], subsample_freq=p['subsample_freq'], colsample_bytree=p['colsample_bytree'],
                                 reg_lambda=p['reg_lambda'], random_state=seed, n_jobs=1, verbose=-1)
    from sklearn.ensemble import HistGradientBoostingRegressor
    return HistGradientBoostingRegressor(loss='absolute_error' if objective == 'huber' else 'squared_error',
                                         max_iter=p['n_estimators'], learning_rate=p['learning_rate'], max_leaf_nodes=p['num_leaves'],
                                         min_samples_leaf=p['min_child_samples'], l2_regularization=p['reg_lambda'], random_state=seed)


def gbm_inputs(frame: pd.DataFrame) -> np.ndarray:
    """GBM 입력: Ridge와 같은 10개(충격은 scale_kospi로 나눔). 종목 번호는 쓰지 않습니다."""
    x = frame[INPUT_ORDER].to_numpy(dtype=float).copy()
    x[:, : len(SHOCK_ORDER)] /= _floor(frame['scale_kospi'].to_numpy())[:, None]
    return x


class HybridCenter:
    """정규화 단위 중심값을 여러 방식으로 냅니다. 분포(잔차 표본)는 별도 단계에서 붙입니다."""

    def __init__(self, alpha: float = ALPHA, seed: int = SEED, objective: str = 'l2'):
        self.alpha, self.seed, self.objective = alpha, seed, objective

    def fit(self, train: pd.DataFrame):
        self.ridge = ScaledRidgeModel(alpha=self.alpha).fit(train)
        d = train.dropna(subset=self.ridge.required_columns)
        d = d[d['asset_id'].isin(self.ridge.models)]
        y = d['y_log_return_5d'].to_numpy(float) / _floor(d['asset_scale'].to_numpy())
        self.median = float(np.median(y))
        self.gbm = make_gbm(self.seed, self.objective).fit(gbm_inputs(d), y)
        r = self.ridge_center(d)
        self.resid_gbm = make_gbm(self.seed, self.objective).fit(gbm_inputs(d), y - r)
        self.n_train = int(len(d))
        return self

    def ridge_center(self, frame: pd.DataFrame) -> np.ndarray:
        out = np.full(len(frame), np.nan)
        x = self.ridge.inputs(frame)
        for a, idx in frame.groupby('asset_id').indices.items():
            if a in self.ridge.models:
                out[idx] = self.ridge.models[a].predict(x[idx])
        return out

    def centers(self, frame: pd.DataFrame) -> dict:
        r = self.ridge_center(frame)
        x = gbm_inputs(frame)
        g = self.gbm.predict(x)
        rg = self.resid_gbm.predict(x)
        out = {'volatility': np.full(len(frame), self.median), 'ridge': r, 'gbm': g}
        for w in BLEND_WEIGHTS:
            out[f'blend_w{int(w * 100):02d}'] = w * r + (1 - w) * g
        for s in RESIDUAL_SHRINK:
            out[f'residual_s{int(s * 100):03d}'] = r + s * rg
        return out


def valid_frame(d: pd.DataFrame) -> pd.DataFrame:
    need = INPUT_ORDER + ['scale_kospi', 'asset_scale', 'y_log_return_5d', 'target_date']
    return d.dropna(subset=need)


def rolling_validation(samples_scaled: pd.DataFrame, years=range(FIRST_VALID_YEAR, LAST_VALID_YEAR + 1)):
    d = valid_frame(samples_scaled)
    rows, fold_info = [], []
    for y in years:
        start, end = pd.Timestamp(f'{y}-01-01'), pd.Timestamp(f'{y + 1}-01-01')
        train = d[d['target_date'] < start]
        val = d[(d['trading_date'] >= start) & (d['target_date'] < end)]
        if len(train) < 5000 or len(val) < 100:
            continue
        m = HybridCenter().fit(train)
        val = val[val['asset_id'].isin(m.ridge.models)]
        if val.empty:
            continue
        sc = _floor(val['asset_scale'].to_numpy())
        y_act = val['y_log_return_5d'].to_numpy(float)
        cal = val[['trading_date', 'asset_id']].copy()
        cal['year'] = y
        cal['actual'] = y_act
        for name, c in m.centers(val).items():
            cal[f'pred__{name}'] = c * sc                      # 원래 단위(로그수익률 %)
        rows.append(cal)
        fold_info.append({'year': y, 'train_rows': int(len(train)), 'val_rows': int(len(val)), 'assets': int(val['asset_id'].nunique())})
    return pd.concat(rows, ignore_index=True), pd.DataFrame(fold_info)


def metrics(preds: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    names = [c[6:] for c in preds.columns if c.startswith('pred__')]
    a = preds['actual'].to_numpy()
    recs = []
    for y, g in preds.groupby('year'):
        for n in names:
            e = g['actual'].to_numpy() - g[f'pred__{n}'].to_numpy()
            recs.append({'year': y, 'model': n, 'rows': len(g), 'mae_pct': float(np.abs(e).mean()), 'rmse_pct': float(np.sqrt((e ** 2).mean()))})
    fold = pd.DataFrame(recs)
    summ = []
    for n in names:
        e = a - preds[f'pred__{n}'].to_numpy()
        pf = fold[fold['model'] == n]
        summ.append({'model': n, 'rows': len(preds), 'mae_pct': float(np.abs(e).mean()), 'rmse_pct': float(np.sqrt((e ** 2).mean())),
                     'years_better_than_ridge_mae': int((pf.set_index('year')['mae_pct'] <
                                                         fold[fold['model'] == 'ridge'].set_index('year')['mae_pct']).sum()),
                     'years': int(pf['year'].nunique())})
    return fold, pd.DataFrame(summ).sort_values('mae_pct').reset_index(drop=True)


def paired_vs_ridge(preds: pd.DataFrame, n_boot: int = 500, seed: int = SEED) -> pd.DataFrame:
    """모델별 (ridge 대비) 절대오차 차이. 겹치는 5일 구간을 한 블록으로 묶어 부트스트랩합니다. 음수 = ridge보다 좋음."""
    cal = {d: i for i, d in enumerate(sorted(preds['trading_date'].unique()))}
    blk = preds['trading_date'].map(cal).to_numpy() // 5
    ub, inv = np.unique(blk, return_inverse=True)
    rng = np.random.default_rng(seed)
    names = [c[6:] for c in preds.columns if c.startswith('pred__') and c != 'pred__ridge']
    base = np.abs(preds['actual'] - preds['pred__ridge']).to_numpy()
    out = []
    for n in names:
        diff = np.abs(preds['actual'] - preds[f'pred__{n}']).to_numpy() - base
        s = np.bincount(inv, weights=diff, minlength=len(ub))
        c = np.bincount(inv, minlength=len(ub)).astype(float)
        idx = rng.integers(0, len(ub), (n_boot, len(ub)))
        bs = s[idx].sum(1) / c[idx].sum(1)
        out.append({'model': n, 'mean_abs_error_diff_vs_ridge_pct': float(diff.mean()),
                    'ci95_low': float(np.quantile(bs, .025)), 'ci95_high': float(np.quantile(bs, .975)),
                    'significant': bool(np.quantile(bs, .025) > 0 or np.quantile(bs, .975) < 0), 'blocks': int(len(ub))})
    return pd.DataFrame(out).sort_values('mean_abs_error_diff_vs_ridge_pct').reset_index(drop=True)


def run(samples: pd.DataFrame, kospi_scale: pd.DataFrame, n_boot: int = 500) -> dict:
    d = with_scales(samples, kospi_scale)
    preds, folds = rolling_validation(d)
    fold_m, summ = metrics(preds)
    paired = paired_vs_ridge(preds, n_boot)
    best = summ.iloc[0]['model']
    info = {'hybrid_version': HYBRID_VERSION, 'gbm_backend': gbm_backend(), 'gbm_params': GBM_PARAMS, 'alpha': ALPHA,
            'validation': {'kind': 'rolling_origin_by_year', 'years': [int(preds['year'].min()), int(preds['year'].max())],
                           'rows': int(len(preds)), 'evaluation_split_used': False},
            'best_model_by_mae': best, 'ridge_mae': float(summ.loc[summ.model == 'ridge', 'mae_pct'].iloc[0]),
            'volatility_mae': float(summ.loc[summ.model == 'volatility', 'mae_pct'].iloc[0]),
            'notes': ['중심값 정확도만 비교한 것입니다. 분포(구간/VaR) 품질은 따로 확인해야 합니다.',
                      '검증은 2010~2022 롤링입니다. 2023년 이후 평가 구간은 열지 않았습니다.',
                      '현재 종목 결과를 코스피 전체에 일반화하지 않습니다.']}
    return {'folds': folds, 'fold_metrics': fold_m, 'summary': summ, 'paired': paired, 'info': info}


def write(res: dict, out_dir) -> dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = {}
    for k, f in [('folds', 'folds.csv'), ('fold_metrics', 'fold_metrics.csv'), ('summary', 'summary.csv'), ('paired', 'paired_vs_ridge.csv')]:
        paths[k] = out / f
        res[k].to_csv(paths[k], index=False, encoding='utf-8-sig')
    paths['info'] = out / 'hybrid_summary.json'
    paths['info'].write_text(json.dumps(res['info'], ensure_ascii=False, indent=2, default=str) + '\n', encoding='utf8')
    return {k: str(v) for k, v in paths.items()}


def main(argv=None):
    p = argparse.ArgumentParser(description='Ridge + LightGBM 결합 롤링 검증')
    p.add_argument('--samples', default=str(DEFAULT_SAMPLES))
    p.add_argument('--gold', default=None)
    p.add_argument('--out', default=str(DEFAULT_OUT))
    p.add_argument('--bootstrap', type=int, default=500)
    a = p.parse_args(argv)
    from load_gold import DEFAULT_SOURCE, load_gold
    from train import market_scale_from_gold
    scale = market_scale_from_gold(load_gold(a.gold or DEFAULT_SOURCE))
    res = run(pd.read_parquet(a.samples), scale, a.bootstrap)
    paths = write(res, a.out)
    print(f"GBM 백엔드: {res['info']['gbm_backend']}")
    print(res['summary'].round(4).to_string(index=False))
    print(res['paired'].round(4).to_string(index=False))
    print(json.dumps(paths, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
