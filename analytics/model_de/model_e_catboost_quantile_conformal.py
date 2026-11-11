"""모델 E: CatBoost 분위수 회귀 + Conformal(CQR) 구간 보정.

    python analytics/model_de/model_e_catboost_quantile_conformal.py   # 인자 없음, VS Code ▶
    -> analytics/outputs/model_de/model_e_predictions.parquet (pyarrow 없으면 .csv), model_e_summary.json

역할 분리
  1) 분위수 모델: 분위수 2.5/5/10/50/90/95/97.5%를 각각 학습(학습 구간만, 종목 변동성으로 정규화한 y).
     Q50이 중심 예측값. 분위수가 서로 역전되면(crossing) 비율을 기록한 뒤 정렬해서 사용.
  2) Conformal 보정(CQR): 보정 구간(2020~2022)에서 점수 max(하한-y, y-상한)의 유한 표본 분위수만큼 구간을 넓히거나 좁힘.
     보정 구간은 학습/설정 선택에 쓰지 않음.
변형: raw(보정 전) / cqr(전체 보정) / cqr_roll(최근 250거래일 롤링 보정)
CatBoost가 없으면 같은 분위수 손실의 scikit-learn HistGradientBoosting으로 대신하고 backend에 그 사실을 남깁니다.
(설치: .venv 에서 `pip install catboost`)
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402
import conformal as CF  # noqa: E402

TAUS = (0.025, 0.05, 0.10, 0.50, 0.90, 0.95, 0.975)
CATBOOST_PARAMS = dict(iterations=300, depth=4, learning_rate=0.05, l2_leaf_reg=10.0)
HGB_PARAMS = dict(max_iter=200, learning_rate=0.05, max_leaf_nodes=7, min_samples_leaf=400, l2_regularization=10.0)
ROLLING_WINDOW = 250
VARIANTS = ('raw', 'cqr', 'cqr_roll')


def qtag(t: float) -> str:
    return f'q{int(round(t * 1000)):03d}'


def backend() -> str:
    try:
        import catboost  # noqa: F401
        return 'catboost'
    except ImportError:
        return 'sklearn_hist_gradient_boosting_quantile'


HGB_LEAVES = {2: 3, 3: 5, 4: 7, 5: 11, 6: 15, 8: 31}      # CatBoost depth -> 대체 모델의 리프 수


def make_quantile_model(tau: float, seed: int, params: dict | None = None):
    """params: {depth, iterations, learning_rate, l2_leaf_reg}. None이면 기본값(CATBOOST_PARAMS)."""
    p = {**CATBOOST_PARAMS, **(params or {})}
    if backend() == 'catboost':
        from catboost import CatBoostRegressor
        return CatBoostRegressor(loss_function=f'Quantile:alpha={tau}', random_seed=seed, verbose=0, thread_count=1,
                                 allow_writing_files=False, **p)
    from sklearn.ensemble import HistGradientBoostingRegressor
    h = {**HGB_PARAMS, 'max_iter': p['iterations'], 'learning_rate': p['learning_rate'], 'l2_regularization': p['l2_leaf_reg'],
         'max_leaf_nodes': HGB_LEAVES.get(p['depth'], 7)} if params else dict(HGB_PARAMS)
    return HistGradientBoostingRegressor(loss='quantile', quantile=tau, random_state=seed, **h)


def _fit_one(tau, seed, params, x, z):
    return make_quantile_model(tau, seed, params).fit(x, z)


class QuantileSet:
    def __init__(self, ycol: str, seed: int = C.SEED, params: dict | None = None):
        self.ycol, self.seed, self.params = ycol, seed, params

    def fit(self, train: pd.DataFrame):
        x = C.design(train)
        z = train[self.ycol].to_numpy(float) / C._floor(train['asset_scale'].to_numpy())
        n_jobs = max(1, min(len(TAUS), os.cpu_count() or 1))
        if n_jobs > 1:
            # 모델마다 1스레드로 고정한 채 분위수 7개를 동시에 학습: 순차 학습과 결과가 같고 시간만 줄어듭니다.
            from joblib import Parallel, delayed
            fitted = Parallel(n_jobs=n_jobs)(delayed(_fit_one)(t, self.seed, self.params, x, z) for t in TAUS)
        else:
            fitted = [_fit_one(t, self.seed, self.params, x, z) for t in TAUS]
        self.models = dict(zip(TAUS, fitted))
        return self

    def predict_norm(self, frame: pd.DataFrame) -> np.ndarray:
        """열 순서 = TAUS. 정렬 전 원본(crossing 검사용)."""
        x = C.design(frame)
        return np.column_stack([self.models[t].predict(x) for t in TAUS])


def crossing_report(raw: np.ndarray) -> dict:
    d = np.diff(raw, axis=1)
    return {'rows_with_any_crossing': float((d < 0).any(axis=1).mean()),
            'adjacent_pair_crossing_rate': {f'{qtag(TAUS[i])}>{qtag(TAUS[i + 1])}': float((d[:, i] < 0).mean()) for i in range(len(TAUS) - 1)},
            'mean_magnitude_when_crossed_norm': float(-d[d < 0].mean()) if (d < 0).any() else 0.0}


def intervals(ctx: C.Context, qc: np.ndarray, qt: np.ndarray, window=ROLLING_WINDOW) -> dict:
    """qc/qt: 정렬된 정규화 분위수(열=TAUS). 반환 {(변형, 수준): (lo, hi)} 원래 단위."""
    sc_t = ctx.scale(ctx.test)
    yc = ctx.y['cal'] / ctx.scale(ctx.cal)
    yt = ctx.y['test'] / sc_t
    col = {t: i for i, t in enumerate(TAUS)}
    out = {}
    for L in C.LEVELS:
        a, b = C.LEVEL_Q[L]
        lo_c, hi_c, lo_t, hi_t = qc[:, col[a]], qc[:, col[b]], qt[:, col[a]], qt[:, col[b]]
        out[('raw', L)] = (lo_t * sc_t, hi_t * sc_t)
        s_c = CF.cqr_scores(yc, lo_c, hi_c)
        k = CF.conformal_quantile(s_c, L)
        out[('cqr', L)] = ((lo_t - k) * sc_t, (hi_t + k) * sc_t)
        s_t = CF.cqr_scores(yt, lo_t, hi_t)
        pool = np.concatenate([s_c, s_t])
        pool_tp = np.concatenate([ctx.cal['target_pos'], ctx.test['target_pos']])
        kr = CF.rolling_quantiles(pool, pool_tp, ctx.test['row_pos'], L, window, fallback=k)
        out[('cqr_roll', L)] = ((lo_t - kr) * sc_t, (hi_t + kr) * sc_t)
    return out


def run(ctx: C.Context, seed: int = C.SEED, params: dict | None = None) -> dict:
    with C.Timer() as t_fit:
        m = QuantileSet(ctx.ycol, seed, params).fit(ctx.train)
    with C.Timer() as t_inf:
        raw_t = m.predict_norm(ctx.test)
    raw_c = m.predict_norm(ctx.cal)
    cross = {'test': crossing_report(raw_t), 'calibration': crossing_report(raw_c)}
    qt, qc = np.sort(raw_t, axis=1), np.sort(raw_c, axis=1)
    with C.Timer() as t_cal:
        iv = intervals(ctx, qc, qt)
    sc = ctx.scale(ctx.test)
    pred = ctx.test[['trading_date', 'target_date', 'asset_id', 'overlap_block']].copy()
    pred['horizon'] = ctx.h
    pred['y_actual'] = ctx.y['test']
    pred['asset_scale'] = sc
    pred['center'] = qt[:, TAUS.index(0.50)] * sc
    for i, t in enumerate(TAUS):
        pred[qtag(t)] = qt[:, i] * sc
    for (v, L), (lo, hi) in iv.items():
        pred[f'lo_{v}_{C.lv(L)}'], pred[f'hi_{v}_{C.lv(L)}'] = lo, hi
    for c in C.SHOCK_ORDER:
        pred[c] = ctx.test[c].to_numpy()
    k_all = {C.lv(L): CF.conformal_quantile(CF.cqr_scores(ctx.y['cal'] / ctx.scale(ctx.cal), qc[:, TAUS.index(C.LEVEL_Q[L][0])],
                                                          qc[:, TAUS.index(C.LEVEL_Q[L][1])]), L) for L in C.LEVELS}
    info = {'horizon': ctx.h, 'backend': backend(), 'params': {**CATBOOST_PARAMS, **(params or {})} if backend() == 'catboost' else (HGB_PARAMS if not params else params),
            'quantile_levels': list(TAUS), 'quantile_crossing': cross, 'cqr_adjustment_norm_units': k_all,
            'train_seconds': t_fit.seconds, 'inference_seconds_test': t_inf.seconds, 'inference_rows': int(len(ctx.test)),
            'inference_ms_per_row': t_inf.seconds / max(len(ctx.test), 1) * 1000, 'calibration_seconds': t_cal.seconds,
            'calibration_rows': int(len(ctx.cal)), 'rolling_window_days': ROLLING_WINDOW, 'seed': seed}
    return {'pred': pred, 'model': m, 'info': info, 'raw_cal': raw_c}


def main():
    from load_gold import DEFAULT_SOURCE, load_gold
    gold = load_gold(DEFAULT_SOURCE)
    clean, fs, market = C.load_inputs(gold)
    frames, infos = [], []
    for h in C.HORIZONS:
        ctx = C.Context(clean, fs, market, h)
        r = run(ctx)
        frames.append(r['pred'])
        infos.append({**ctx.summary(), **r['info']})
        print(f'E h={h}: backend={r["info"]["backend"]}, 학습 {r["info"]["train_seconds"]:.1f}초, '
              f'crossing(시험) {r["info"]["quantile_crossing"]["test"]["rows_with_any_crossing"]:.1%}')
    C.OUT.mkdir(parents=True, exist_ok=True)
    path = C.write_table(pd.concat(frames, ignore_index=True), C.OUT / 'model_e_predictions.parquet')
    (C.OUT / 'model_e_summary.json').write_text(json.dumps(infos, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
    print('저장:', path)


if __name__ == '__main__':
    main()
