"""모델 D: Ridge + LightGBM 중심 예측 + Conformal Prediction 구간.

    python analytics/model_de/model_d_ridge_lightgbm_conformal.py     # 인자 없음, VS Code ▶
    -> analytics/outputs/model_de/model_d_predictions.parquet (pyarrow 없으면 .csv), model_d_summary.json

중심값: 종목별 Ridge(StandardScaler + alpha 30)와 전 종목 합친 GBM(LightGBM, 없으면 sklearn HGB 대체)의 가중 평균.
        기존 hybrid.py(blend)와 같은 구조이며 예측 기간(1/5/20일)별로 따로 학습합니다. 기존 파일은 수정하지 않습니다.
        가중치(Ridge 비중)는 학습 구간 안의 롤링 검증(연도별)에서만 고르고, 보정/시험 구간은 쓰지 않습니다.
구간:   보정 구간(2020~2022)의 정규화 잔차에 split conformal 분위수를 적용(평균/표준편차 방식이 아님).
        sym=대칭, asym=아래/위 꼬리 따로, asset=종목별(행 부족하면 전체), roll=최근 250거래일 롤링 보정.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402
import conformal as CF  # noqa: E402

sys.path.insert(0, str(C.ANALYTICS_ROOT / 'src'))
from distribution import ALPHA, INPUT_ORDER  # noqa: E402
from hybrid import gbm_backend, make_gbm  # noqa: E402

BLEND_CANDIDATES = (0.3, 0.5, 0.7)      # Ridge 비중
DEFAULT_BLEND = 0.3
ROLLING_WINDOW = 250
VAL_YEARS = range(2014, 2020)           # 학습 구간(<2020) 안에서만 검증
VARIANTS = ('sym', 'asym', 'asset', 'roll')


class RidgeGbmCenter:
    """정규화 단위 중심 = w*Ridge(종목별) + (1-w)*GBM(전종목). 예측 기간별 y 열을 씁니다."""

    def __init__(self, ycol: str, w: float = DEFAULT_BLEND, seed: int = C.SEED):
        self.ycol, self.w, self.seed = ycol, w, seed

    def fit(self, train: pd.DataFrame):
        self.ridge = {}
        for a, g in train.groupby('asset_id', sort=True):
            if len(g) >= C.MIN_ASSET_TRAIN_ROWS:
                self.ridge[a] = make_pipeline(StandardScaler(), Ridge(alpha=ALPHA)).fit(C.design(g), self._z(g))
        d = train[train['asset_id'].isin(self.ridge)]
        self.gbm = make_gbm(self.seed).fit(C.design(d), self._z(d))
        return self

    def _z(self, g):
        return g[self.ycol].to_numpy(float) / C._floor(g['asset_scale'].to_numpy())

    def parts(self, frame: pd.DataFrame):
        r = np.full(len(frame), np.nan)
        x = C.design(frame)
        for a, idx in frame.groupby('asset_id').indices.items():
            if a in self.ridge:
                r[idx] = self.ridge[a].predict(x[idx])
        return r, self.gbm.predict(x)

    def predict_norm(self, frame, w=None):
        r, g = self.parts(frame)
        w = self.w if w is None else w
        return w * r + (1 - w) * g

    def predict(self, frame, w=None):
        return self.predict_norm(frame, w) * C._floor(frame['asset_scale'].to_numpy())


def select_blend(ctx: C.Context, seed: int) -> dict:
    """학습 구간 안 롤링 오리진: 연도 Y 검증은 정답이 Y년 이전에 끝난 행으로만 학습. 보정/시험은 사용하지 않음."""
    tr = ctx.train
    err = {w: [] for w in BLEND_CANDIDATES}
    for y in VAL_YEARS:
        start, end = pd.Timestamp(f'{y}-01-01'), pd.Timestamp(f'{y + 1}-01-01')
        fit = tr[tr['target_date'] < start]
        val = tr[(tr['trading_date'] >= start) & (tr['target_date'] < end)]
        if len(fit) < 5000 or len(val) < 100:
            continue
        m = RidgeGbmCenter(ctx.ycol, seed=seed).fit(fit)
        val = val[val['asset_id'].isin(m.ridge)]
        yy = val[ctx.ycol].to_numpy(float)
        for w in BLEND_CANDIDATES:
            err[w].append(np.abs(yy - m.predict(val, w)).mean())
    mae = {w: float(np.mean(v)) for w, v in err.items() if v}
    best = min(mae, key=mae.get) if mae else DEFAULT_BLEND
    return {'candidates_mae': {str(k): v for k, v in mae.items()}, 'chosen_ridge_weight': best, 'folds': len(next(iter(err.values())))}


def intervals(ctx: C.Context, center_cal, center_test, window=ROLLING_WINDOW) -> dict:
    """{(변형, 수준): (lo, hi)} 원래 단위(로그수익률 %)."""
    sc_c, sc_t = ctx.scale(ctx.cal), ctx.scale(ctx.test)
    yc, yt = ctx.y['cal'], ctx.y['test']
    rc = (yc - center_cal) / sc_c                           # 보정 정규화 잔차
    rt = (yt - center_test) / sc_t                          # 시험 정규화 잔차(롤링 풀에 '실현된 뒤' 편입)
    pool_s = np.concatenate([np.abs(rc), np.abs(rt)])
    pool_tp = np.concatenate([ctx.cal['target_pos'], ctx.test['target_pos']])
    out = {}
    for L in C.LEVELS:
        q = CF.sym_halfwidth(rc, L)
        out[('sym', L)] = (center_test - q * sc_t, center_test + q * sc_t)
        ql, qu = CF.asym_halfwidths(rc, L)
        out[('asym', L)] = (center_test - ql * sc_t, center_test + qu * sc_t)
        qa = CF.by_asset_halfwidths(rc, ctx.cal['asset_id'], L, ctx.test['asset_id'])
        out[('asset', L)] = (center_test - qa * sc_t, center_test + qa * sc_t)
        qr = CF.rolling_quantiles(pool_s, pool_tp, ctx.test['row_pos'], L, window, fallback=q)
        out[('roll', L)] = (center_test - qr * sc_t, center_test + qr * sc_t)
    return out


def run(ctx: C.Context, seed: int = C.SEED, blend: float | None = None) -> dict:
    sel = select_blend(ctx, seed) if blend is None else {'chosen_ridge_weight': blend, 'note': '고정값 사용'}
    w = sel['chosen_ridge_weight']
    with C.Timer() as t_fit:
        m = RidgeGbmCenter(ctx.ycol, w=w, seed=seed).fit(ctx.train)
    with C.Timer() as t_inf:
        c_test = m.predict(ctx.test)
    c_cal = m.predict(ctx.cal)
    with C.Timer() as t_cal:
        iv = intervals(ctx, c_cal, c_test)
    pred = ctx.test[['trading_date', 'target_date', 'asset_id', 'overlap_block']].copy()
    pred['horizon'] = ctx.h
    pred['y_actual'] = ctx.y['test']
    pred['asset_scale'] = ctx.scale(ctx.test)
    pred['center'] = c_test
    ridge_t, gbm_t = m.parts(ctx.test)
    pred['center_ridge'], pred['center_gbm'] = ridge_t * pred['asset_scale'], gbm_t * pred['asset_scale']
    for (v, L), (lo, hi) in iv.items():
        pred[f'lo_{v}_{C.lv(L)}'], pred[f'hi_{v}_{C.lv(L)}'] = lo, hi
    for c in C.SHOCK_ORDER:
        pred[c] = ctx.test[c].to_numpy()
    info = {'horizon': ctx.h, 'backend_gbm': gbm_backend(), 'blend_selection': sel,
            'train_seconds': t_fit.seconds, 'inference_seconds_test': t_inf.seconds, 'inference_rows': int(len(ctx.test)),
            'inference_ms_per_row': t_inf.seconds / max(len(ctx.test), 1) * 1000, 'calibration_seconds': t_cal.seconds,
            'calibration_rows': int(len(ctx.cal)), 'rolling_window_days': ROLLING_WINDOW, 'seed': seed,
            'conformal_quantile_levels': {C.lv(L): CF.sym_halfwidth((ctx.y['cal'] - c_cal) / ctx.scale(ctx.cal), L) for L in C.LEVELS}}
    return {'pred': pred, 'model': m, 'info': info, 'center_cal': c_cal}


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
        print(f'D h={h}: test {len(ctx.test):,}행, 학습 {r["info"]["train_seconds"]:.1f}초, 블렌드 Ridge비중 {r["info"]["blend_selection"]["chosen_ridge_weight"]}')
    C.OUT.mkdir(parents=True, exist_ok=True)
    path = C.write_table(pd.concat(frames, ignore_index=True), C.OUT / 'model_d_predictions.parquet')
    (C.OUT / 'model_d_summary.json').write_text(json.dumps(infos, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
    print('저장:', path)


if __name__ == '__main__':
    main()
