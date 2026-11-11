"""특징 구성별 Ridge / LightGBM / 결합 모델 비교. (새 폴더 실험, 기존 파일은 바꾸지 않습니다)

    python analytics/model_compare/compare_models.py        # VS Code ▶ 실행, 인자 없음
    -> analytics/outputs/model_compare/*.csv, model_compare_summary.json

특징 구성
  F10  현재 사용: 충격 4 + 상태 6
  F14  기존 계획 전부: F10 + ECOS 2(kr3y_level, kr3y_change20_bp) + 종목 변동성 2(asset_vol20, asset_vol60)
  F21  F10 + 추가 특징 11(extra_features.py: 단기 모멘텀, 낙폭, 베타, 충격x베타 등)
  (진단) F10+M / F10+A / F10+I : F10에 추가 특징 묶음을 하나씩만 더한 Ridge. 어느 묶음이 도움인지 봅니다.
모델: ridge(종목별), gbm(전 종목 합침), blend_w30/w50(Ridge 비중), baseline:volatility(입력 없음)

검증 1) 롤링 2012~2022: Y년마다 학습=Y-2년 전 정답 종료, 보정=Y-2~Y-1년, 평가=Y년.
검증 2) 고정 분할: 학습 <2020, 보정 2020~2022, 평가 2023~ (이미 한 번 쓴 구간이라 선택에는 쓰지 않음, 참고용).
같은 (날짜, 종목) 행에서 모든 모델을 비교합니다. 구간은 보정 잔차의 5%/95% 분위수로 만들어 모든 모델에 똑같이 적용합니다.
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

HERE = Path(__file__).resolve().parent
ANALYTICS_ROOT = HERE.parent
sys.path.insert(0, str(ANALYTICS_ROOT / 'src'))
sys.path.insert(0, str(HERE))
from distribution import ALPHA, INPUT_ORDER, MIN_ASSET_TRAIN_ROWS, _floor, with_scales  # noqa: E402
from extra_features import EXTRA_ASSET, EXTRA_COLUMNS, EXTRA_IX, EXTRA_MARKET, IX_SOURCES, build_extra_features  # noqa: E402
from hybrid import gbm_backend, make_gbm  # noqa: E402

VERSION = 'model-compare-v1.0'
SEED = 20261105
OUT = ANALYTICS_ROOT / 'outputs/model_compare'
ECOS = ['kr3y_level', 'kr3y_change20_bp']
ASSET_VOL = ['asset_vol20', 'asset_vol60']
FEATURE_SETS = {
    'F10': INPUT_ORDER,
    'F14': INPUT_ORDER + ECOS + ASSET_VOL,
    'F21': INPUT_ORDER + EXTRA_MARKET + EXTRA_ASSET + EXTRA_IX,
}
ABLATION = {'F10+M': INPUT_ORDER + EXTRA_MARKET, 'F10+A': INPUT_ORDER + EXTRA_ASSET,
            'F10+I': INPUT_ORDER + ['asset_beta60'] + EXTRA_IX}       # I는 곱셈 항에 필요한 베타를 함께 넣음
BLENDS = {'blend_w30': 0.3, 'blend_w50': 0.5}                          # Ridge 비중
REFERENCE_MODEL = 'F10:ridge'
MIN_CAL_ROWS_ASSET = 60
ALPHA_INTERVAL = 0.1
ROLL_YEARS = range(2012, 2023)
CAL_START, EVAL_START = pd.Timestamp('2020-01-01'), pd.Timestamp('2023-01-01')


def all_columns() -> list:
    cols = set(INPUT_ORDER)
    for v in list(FEATURE_SETS.values()) + list(ABLATION.values()):
        cols |= set(v)
    return sorted(cols)


# ---------------------------------------------------------------- 입력 만들기
def design(frame: pd.DataFrame, cols) -> np.ndarray:
    """충격은 scale_kospi로 나누고, ix_* 는 정규화한 충격 x 종목 베타, 나머지는 그대로."""
    scale = _floor(frame['scale_kospi'].to_numpy())
    out = []
    for c in cols:
        if c.startswith('shock_'):
            out.append(frame[c].to_numpy(float) / scale)
        elif c in IX_SOURCES:
            s, b = IX_SOURCES[c]
            out.append(frame[s].to_numpy(float) / scale * frame[b].to_numpy(float))
        else:
            out.append(frame[c].to_numpy(float))
    return np.column_stack(out)


class CenterModels:
    """한 특징 구성에 대한 종목별 Ridge와 전 종목 합친 GBM. 정규화한 y(= y / asset_scale)를 예측합니다."""

    def __init__(self, cols, with_gbm=True, alpha=ALPHA):
        self.cols, self.with_gbm, self.alpha = list(cols), with_gbm, alpha

    def fit(self, train: pd.DataFrame, assets):
        self.ridge = {}
        y_all = train['y_log_return_5d'].to_numpy(float) / _floor(train['asset_scale'].to_numpy())
        x_all = design(train, self.cols)
        for a, idx in train.groupby('asset_id').indices.items():
            if a in assets:
                self.ridge[a] = make_pipeline(StandardScaler(), Ridge(alpha=self.alpha)).fit(x_all[idx], y_all[idx])
        keep = train['asset_id'].isin(assets).to_numpy()
        self.gbm = make_gbm(SEED).fit(x_all[keep], y_all[keep]) if self.with_gbm else None
        return self

    def centers(self, frame: pd.DataFrame) -> dict:
        x = design(frame, self.cols)
        r = np.full(len(frame), np.nan)
        for a, idx in frame.groupby('asset_id').indices.items():
            if a in self.ridge:
                r[idx] = self.ridge[a].predict(x[idx])
        out = {'ridge': r}
        if self.gbm is not None:
            g = self.gbm.predict(x)
            out['gbm'] = g
            for k, w in BLENDS.items():
                out[k] = w * r + (1 - w) * g
        return out


# ---------------------------------------------------------------- 분포(구간)와 행별 지표
def residual_quantiles(res: pd.Series, assets: pd.Series) -> tuple[dict, tuple]:
    pooled = tuple(np.quantile(res.dropna(), [0.05, 0.95]))
    per = {}
    for a, g in res.groupby(assets):
        g = g.dropna()
        per[a] = tuple(np.quantile(g, [0.05, 0.95])) if len(g) >= MIN_CAL_ROWS_ASSET else pooled
    return per, pooled


def row_metrics(actual, center, scale, q):
    """모두 원래 단위(로그수익률 %). q: (q05 잔차, q95 잔차)는 정규화 단위."""
    lo = center * scale + q[:, 0] * scale
    hi = center * scale + q[:, 1] * scale
    pred = center * scale
    e = actual - pred
    pin = np.maximum(0.05 * (actual - lo), (0.05 - 1) * (actual - lo))
    iscore = (hi - lo) + (2 / ALPHA_INTERVAL) * np.maximum(lo - actual, 0) + (2 / ALPHA_INTERVAL) * np.maximum(actual - hi, 0)
    return {'abs': np.abs(e), 'sq': e ** 2, 'cover': ((actual >= lo) & (actual <= hi)).astype(float), 'width': hi - lo,
            'iscore': iscore, 'pin05': pin, 'breach': (actual < lo).astype(float)}


def run_fold(train, cal, test, label, sets: dict, ridge_only: set):
    """train/cal/test: with_scales 적용 + 결측 제거된 표. 반환: 행별 지표 표(wide)."""
    n_by_asset = train.groupby('asset_id').size()
    assets = set(n_by_asset[n_by_asset >= MIN_ASSET_TRAIN_ROWS].index) & set(cal['asset_id']) & set(test['asset_id'])
    train = train[train['asset_id'].isin(assets)]
    cal = cal[cal['asset_id'].isin(assets)].reset_index(drop=True)
    test = test[test['asset_id'].isin(assets)].reset_index(drop=True)
    y_cal = cal['y_log_return_5d'].to_numpy(float) / _floor(cal['asset_scale'].to_numpy())
    sc_t = _floor(test['asset_scale'].to_numpy())
    act = test['y_log_return_5d'].to_numpy(float)
    base = {'trading_date': test['trading_date'], 'asset_id': test['asset_id'], 'fold': label, 'actual': act, 'scale': sc_t}
    cols_out = {}

    def add(name, c_cal, c_test):
        per, pooled = residual_quantiles(pd.Series(y_cal - c_cal), cal['asset_id'])
        q = np.array([per.get(a, pooled) for a in test['asset_id']])
        for k, v in row_metrics(act, c_test, sc_t, q).items():
            cols_out[f'{name}|{k}'] = v

    med = float(np.median(train['y_log_return_5d'].to_numpy(float) / _floor(train['asset_scale'].to_numpy())))
    add('baseline:volatility', np.full(len(cal), med), np.full(len(test), med))
    for fs, cols in sets.items():
        m = CenterModels(cols, with_gbm=fs not in ridge_only).fit(train, assets)
        cc, ct = m.centers(cal), m.centers(test)
        for kind in ct:
            add(f'{fs}:{kind}', cc[kind], ct[kind])
    df = pd.DataFrame({**base, **cols_out})
    df.attrs['assets'] = sorted(assets)
    return df


# ---------------------------------------------------------------- 롤링 / 고정 분할
def prepare(samples, kospi_scale, extras):
    d = with_scales(samples, kospi_scale).merge(extras, on=['trading_date', 'asset_id'], how='left', suffixes=('', '_x'), validate='one_to_one')
    for c in EXTRA_COLUMNS:                                   # 샘플 표에 이미 있는 열(asset_vol 등)과 겹치면 샘플 쪽을 씁니다
        if c + '_x' in d:
            d[c] = d[c].fillna(d[c + '_x'])
    need = all_columns() + ['scale_kospi', 'asset_scale', 'y_log_return_5d', 'target_date']
    need = [c for c in need if c not in IX_SOURCES]
    d = d[d['train_ready']] if 'train_ready' in d else d
    n0 = len(d)
    d = d.dropna(subset=need).reset_index(drop=True)
    return d, {'rows_before_dropna': int(n0), 'rows_after_dropna': int(len(d))}


def all_sets():
    sets = {**FEATURE_SETS, **ABLATION}
    return sets, set(ABLATION)


def rolling(d: pd.DataFrame, years=ROLL_YEARS) -> pd.DataFrame:
    sets, ridge_only = all_sets()
    out = []
    for y in years:
        s0, t0, t1 = pd.Timestamp(f'{y - 2}-01-01'), pd.Timestamp(f'{y}-01-01'), pd.Timestamp(f'{y + 1}-01-01')
        train = d[d['target_date'] < s0]
        cal = d[(d['trading_date'] >= s0) & (d['target_date'] < t0)]
        test = d[(d['trading_date'] >= t0) & (d['target_date'] < t1)]
        if len(train) < 5000 or len(cal) < 500 or len(test) < 500:
            continue
        out.append(run_fold(train, cal, test, f'roll{y}', sets, ridge_only))
    return pd.concat(out, ignore_index=True)


def holdout(d: pd.DataFrame) -> pd.DataFrame:
    sets, ridge_only = all_sets()
    train = d[d['target_date'] < CAL_START]
    cal = d[(d['trading_date'] >= CAL_START) & (d['target_date'] < EVAL_START)]
    test = d[d['trading_date'] >= EVAL_START]
    return run_fold(train, cal, test, 'holdout', sets, ridge_only)


# ---------------------------------------------------------------- 요약
def model_names(res: pd.DataFrame) -> list:
    return sorted({c.split('|')[0] for c in res.columns if '|' in c})


def summarize(res: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for n in model_names(res):
        g = lambda k: res[f'{n}|{k}'].to_numpy()
        rows.append({'model': n, 'rows': len(res), 'mae_pct': g('abs').mean(), 'rmse_pct': float(np.sqrt(g('sq').mean())),
                     'coverage90': g('cover').mean(), 'mean_width_pct': g('width').mean(), 'interval_score': g('iscore').mean(),
                     'pinball05': g('pin05').mean(), 'var_breach_rate': g('breach').mean()})
    t = pd.DataFrame(rows)
    t['mae_vs_ridge_F10_%'] = 100 * (t['mae_pct'] / t.loc[t.model == REFERENCE_MODEL, 'mae_pct'].iloc[0] - 1)
    t['iscore_vs_ridge_F10_%'] = 100 * (t['interval_score'] / t.loc[t.model == REFERENCE_MODEL, 'interval_score'].iloc[0] - 1)
    return t.sort_values('mae_pct').reset_index(drop=True)


def by_fold(res: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for f, g in res.groupby('fold', sort=True):
        for n in model_names(res):
            rows.append({'fold': f, 'model': n, 'rows': len(g), 'mae_pct': g[f'{n}|abs'].mean(),
                         'interval_score': g[f'{n}|iscore'].mean(), 'coverage90': g[f'{n}|cover'].mean()})
    t = pd.DataFrame(rows)
    ref = t[t.model == REFERENCE_MODEL].set_index('fold')['mae_pct']
    t['better_than_ref_mae'] = t['mae_pct'] < t['fold'].map(ref)
    return t


def paired(res: pd.DataFrame, n_boot=500, seed=SEED) -> pd.DataFrame:
    """기준(F10:ridge) 대비 평균 차이와 블록 부트스트랩 95% 구간. 음수 = 기준보다 좋음."""
    cal = {d: i for i, d in enumerate(sorted(res['trading_date'].unique()))}
    blk = res['trading_date'].map(cal).to_numpy() // 5
    ub, inv = np.unique(blk, return_inverse=True)
    cnt = np.bincount(inv, minlength=len(ub)).astype(float)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(ub), (n_boot, len(ub)))
    rows = []
    for n in model_names(res):
        if n == REFERENCE_MODEL:
            continue
        for k, label in [('abs', 'mae_diff_pct'), ('iscore', 'interval_score_diff')]:
            diff = res[f'{n}|{k}'].to_numpy() - res[f'{REFERENCE_MODEL}|{k}'].to_numpy()
            s = np.bincount(inv, weights=diff, minlength=len(ub))
            bs = s[idx].sum(1) / cnt[idx].sum(1)
            lo, hi = np.quantile(bs, [.025, .975])
            rows.append({'model': n, 'metric': label, 'mean_diff': float(diff.mean()), 'ci95_low': float(lo), 'ci95_high': float(hi),
                         'significant': bool(lo > 0 or hi < 0), 'blocks': int(len(ub))})
    return pd.DataFrame(rows).sort_values(['metric', 'mean_diff']).reset_index(drop=True)


def by_asset(res: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame({n: res.groupby('asset_id')[f'{n}|abs'].mean() for n in model_names(res)}).round(4).reset_index()


def run(samples, kospi_scale, extras, n_boot=500) -> dict:
    d, prep = prepare(samples, kospi_scale, extras)
    roll = rolling(d)
    hold = holdout(d)
    out = {'rolling_summary': summarize(roll), 'rolling_by_fold': by_fold(roll), 'rolling_paired': paired(roll, n_boot),
           'holdout_summary': summarize(hold), 'holdout_paired': paired(hold, n_boot), 'holdout_by_asset': by_asset(hold)}
    best_roll = out['rolling_summary'].iloc[0]['model']
    cover = out['rolling_summary']
    out['summary'] = {
        'version': VERSION, 'gbm_backend': gbm_backend(), 'alpha': ALPHA, 'seed': SEED,
        'feature_sets': {k: v for k, v in {**FEATURE_SETS, **ABLATION}.items()},
        'prepare': prep,
        'rolling': {'years': [int(roll['fold'].str[4:].astype(int).min()), int(roll['fold'].str[4:].astype(int).max())],
                    'rows': int(len(roll)), 'assets': int(roll['asset_id'].nunique()),
                    'best_by_mae': best_roll, 'best_by_interval_score': cover.sort_values('interval_score').iloc[0]['model']},
        'holdout': {'period': [str(hold['trading_date'].min())[:10], str(hold['trading_date'].max())[:10]], 'rows': int(len(hold)),
                    'assets': int(hold['asset_id'].nunique()), 'note': '2023~ 구간은 이전 실험에서 이미 사용됨. 참고용이며 모델 선택에 쓰지 않았음.'},
        'notes': ['구간은 보정 잔차의 5%/95% 분위수를 모든 모델에 똑같이 적용했습니다(독립 비교).',
                  '인접 날짜의 5거래일 구간은 겹칩니다. 행 수가 독립 표본 수가 아닙니다. 블록 부트스트랩으로 불확실성을 봅니다.',
                  '현재 종목 결과를 코스피 전체로 일반화하지 않습니다.']}
    out['_raw'] = {'rolling': roll, 'holdout': hold}
    return out


def write(res: dict, out_dir=OUT) -> dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = {}
    for k, v in res.items():
        if k in ('summary', '_raw'):
            continue
        paths[k] = out / f'{k}.csv'
        v.to_csv(paths[k], index=False, encoding='utf-8-sig', float_format='%.5f')
    paths['summary'] = out / 'model_compare_summary.json'
    paths['summary'].write_text(json.dumps(res['summary'], ensure_ascii=False, indent=2, default=str) + '\n', encoding='utf8')
    return {k: str(v) for k, v in paths.items()}


def main(argv=None):
    from build_samples import DEFAULT_OUT as SAMPLES_DIR
    from features import build_features
    from load_gold import DEFAULT_SOURCE, load_gold
    from train import market_scale_from_gold
    gold = load_gold(DEFAULT_SOURCE)
    clean = gold[~gold['is_mock']].reset_index(drop=True)
    fs = build_features(gold)
    extras = build_extra_features(clean, fs)
    samples = pd.read_parquet(Path(SAMPLES_DIR) / 'training_samples.parquet')
    res = run(samples, market_scale_from_gold(gold), extras)
    paths = write(res)
    show = ['model', 'rows', 'mae_pct', 'rmse_pct', 'coverage90', 'mean_width_pct', 'interval_score', 'pinball05', 'var_breach_rate',
            'mae_vs_ridge_F10_%', 'iscore_vs_ridge_F10_%']
    print(f"GBM 백엔드: {res['summary']['gbm_backend']}")
    print('\n[롤링 2012~2022]'); print(res['rolling_summary'][show].round(4).to_string(index=False))
    print('\n[고정 분할 평가 2023~ (참고용)]'); print(res['holdout_summary'][show].round(4).to_string(index=False))
    print(json.dumps(paths, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
