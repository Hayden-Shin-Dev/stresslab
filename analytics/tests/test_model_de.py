"""모델 D/E(Conformal) 계산 점검. 합성 데이터만 사용합니다.

    python analytics/tests/test_model_de.py      # VS Code ▶ 실행, 인자 없음
    pytest analytics/tests

확인: 유한 표본 conformal 분위수 / 독립 자료 포함률 / CQR 보정 방향 / 롤링 보정의 미래 정보 차단 /
      1·5·20일 정답 달력 / h=5 기존 표본과 일치 / 구간 분리와 purging / 보정 구간이 학습에 쓰이지 않음 /
      충격 유형 기준은 학습 구간 / 범위 이탈 표시 / 같은 시드 재현 / 분위수 역전 검사 / 저장 대체 경로 / 전체 흐름.
"""
from __future__ import annotations

import copy
import sys
import tempfile
import traceback
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'model_de'))
import build_samples as BS  # noqa: E402
import features as FT  # noqa: E402
import load_gold as LG  # noqa: E402
from test_daily_pipeline import synth_gold  # noqa: E402

import common as C  # noqa: E402
import conformal as CF  # noqa: E402
import horizon_samples as HS  # noqa: E402
import model_d_ridge_lightgbm_conformal as D  # noqa: E402
import model_e_catboost_quantile_conformal as E  # noqa: E402
import compare_models as CM  # noqa: E402

_cache: dict = {}
SHIFT = pd.Timedelta(days=364 * 7)          # 요일을 보존하며 2012년 시작으로 이동


def gold(n=3200):
    if ('g', n) not in _cache:
        g = synth_gold(n=n, assets=('000001', '000002', '000003'), seed=3)
        for c in g.columns:
            if str(g[c].dtype).startswith('datetime64'):
                g[c] = g[c] - SHIFT
        _cache[('g', n)] = LG.load_gold(g)
    return _cache[('g', n)]


def inputs():
    if 'in' not in _cache:
        _cache['in'] = C.load_inputs(gold())
    return _cache['in']


def ctx(h):
    if ('ctx', h) not in _cache:
        _cache[('ctx', h)] = C.Context(*inputs(), h)
    return _cache[('ctx', h)]


# ------------------------------------------------------------ conformal 계산
def test_finite_sample_conformal_quantile():
    s = np.arange(1, 10, dtype=float)                      # n=9
    assert CF.conformal_quantile(s, 0.8) == 8.0            # ceil(10*0.8)=8
    assert CF.conformal_quantile(s, 0.9) == 9.0            # ceil(10*0.9)=9
    assert CF.conformal_quantile(s, 0.95) == float('inf')  # ceil(9.5)=10 > n: 보장 불가
    assert CF.conformal_quantile([], 0.9) == float('inf')


def test_coverage_on_independent_data():
    rng = np.random.default_rng(0)
    cal, te = rng.standard_t(5, 3000), rng.standard_t(5, 40000)
    for L in (0.8, 0.9, 0.95):
        q = CF.sym_halfwidth(cal, L)
        cov = (np.abs(te) <= q).mean()
        assert L - 0.012 < cov < L + 0.02, (L, cov)


def test_asymmetric_halfwidths_follow_skew():
    rng = np.random.default_rng(1)
    r = rng.gamma(2.0, 1.0, 5000) - 2.0                    # 오른쪽 꼬리가 긴 잔차
    lo, hi = CF.asym_halfwidths(r, 0.9)
    assert hi > lo * 1.5


def test_cqr_adjusts_in_both_directions_and_covers():
    rng = np.random.default_rng(2)
    y = rng.normal(0, 1, 6000)
    narrow = CF.cqr_adjustment(y[:3000], np.full(3000, -0.5), np.full(3000, 0.5), 0.9)
    wide = CF.cqr_adjustment(y[:3000], np.full(3000, -5.0), np.full(3000, 5.0), 0.9)
    assert narrow > 0 and wide < 0                         # 좁으면 넓히고 넓으면 줄임
    cov = ((y[3000:] >= -0.5 - narrow) & (y[3000:] <= 0.5 + narrow)).mean()
    assert 0.88 < cov < 0.93


def test_rolling_calibration_uses_only_realized_labels():
    rng = np.random.default_rng(3)
    n = 3000
    pos = np.arange(n)                                     # 정답 종료 위치
    sc = np.abs(rng.normal(size=n))
    q = np.array([100, 1500, 2500])                        # 질의 위치
    base = CF.rolling_quantiles(sc, pos, q, 0.9, 250, fallback=9.0)
    sc2 = sc.copy()
    sc2[pos >= 2500] = 1e6                                 # 가장 늦은 질의 이후에 실현되는 정답을 크게 바꿈
    again = CF.rolling_quantiles(sc2, pos, q, 0.9, 250, fallback=9.0)
    assert np.array_equal(base, again)
    assert base[0] == 9.0                                  # 풀 부족(<200) -> 전체 보정값 사용
    sc3 = sc.copy()
    sc3[(pos >= 1250) & (pos < 1500)] = 1e6                # 질의 1500 직전 250일은 반영되어야 함
    assert CF.rolling_quantiles(sc3, pos, q, 0.9, 250, fallback=9.0)[1] > 1e5


# ------------------------------------------------------------ 표본과 분리
def test_horizon_targets_per_asset_calendar():
    clean, fs, _ = inputs()
    for h in (1, 5, 20):
        s = HS.build_horizon_samples(clean, fs, h)
        s = s[s['train_ready']]
        px = clean.pivot(index='trading_date', columns='asset_id', values='close').sort_index()
        i = len(s) // 2
        r = s.iloc[i]
        cal = list(px.index)
        t0 = cal.index(r['trading_date'])
        want = 100 * np.log(px.iloc[t0 + h][r['asset_id']] / px.iloc[t0][r['asset_id']])
        assert abs(r[HS.y_column(h)] - want) < 1e-9, (h, r[HS.y_column(h)], want)
        assert r['target_date'] == cal[t0 + h]


def test_h5_equals_existing_build_samples():
    clean, fs, _ = inputs()
    new = HS.build_horizon_samples(clean, fs, 5)
    old, _m = BS.build_samples(gold(), fs)
    a = new[new['train_ready']].set_index(['trading_date', 'asset_id']).sort_index()
    b = old[old['train_ready']].set_index(['trading_date', 'asset_id']).sort_index()
    assert a.index.equals(b.index)
    assert np.allclose(a['y_log_return_5d'], b['y_log_return_5d'], atol=1e-12)
    for c in C.SHOCK_ORDER:
        assert np.allclose(a[c], b[c], atol=1e-12, equal_nan=True)


def test_splits_do_not_leak_labels_and_purge_grows_with_horizon():
    purged = {}
    for h in (1, 5, 20):
        c = ctx(h)
        assert (c.train['target_date'] < pd.Timestamp('2020-01-01')).all()
        assert (c.cal['trading_date'] >= pd.Timestamp('2020-01-01')).all() and (c.cal['target_date'] < pd.Timestamp('2023-01-01')).all()
        assert (c.test['trading_date'] >= pd.Timestamp('2023-01-01')).all()
        assert len(c.train) and len(c.cal) and len(c.test)
        purged[h] = c.summary()['purged_rows']
    assert purged[1] <= purged[5] <= purged[20] and purged[20] > purged[1]


def test_no_cross_asset_mixing_in_ridge():
    c = ctx(5)
    m = D.RidgeGbmCenter(c.ycol).fit(c.train)
    assert set(m.ridge) == set(c.assets)
    a, b = c.assets[:2]
    fr = c.test[c.test['asset_id'] == a].copy()
    r1, _ = m.parts(fr)
    fr2 = fr.copy()
    fr2['asset_id'] = b                                    # 다른 종목 모델이 쓰이면 값이 달라야 함
    r2, _ = m.parts(fr2)
    assert not np.allclose(r1, r2)


def test_calibration_data_is_not_used_for_fitting():
    c = ctx(5)
    base_d, base_e = D.run(c, blend=0.3), E.run(c)
    c2 = copy.copy(c)
    c2.cal = c.cal.copy()
    c2.cal[c.ycol] = c2.cal[c.ycol] * 3 + 5                # 보정 정답을 바꿈
    d2, e2 = D.run(c2, blend=0.3), E.run(c2)
    assert np.array_equal(base_d['pred']['center'], d2['pred']['center'])     # 중심값 불변
    assert np.array_equal(base_e['pred']['center'], e2['pred']['center'])     # 분위수 불변
    assert np.array_equal(base_e['pred']['lo_raw_90'], e2['pred']['lo_raw_90'])
    assert not np.allclose(base_d['pred']['hi_sym_90'], d2['pred']['hi_sym_90'])   # 구간만 바뀜
    assert not np.allclose(base_e['pred']['hi_cqr_90'], e2['pred']['hi_cqr_90'])


# ------------------------------------------------------------ 충격 유형과 범위
def test_regimes_defined_from_train_distribution():
    c = ctx(5)
    fr = c.test.copy()
    fr.loc[fr.index[0], 'shock_usdkrw_pct'] = c.train['shock_usdkrw_pct'].max() * 10
    m = C.regime_masks(c.train, fr)
    assert bool(m['extreme_any_shock'].iloc[0])
    assert not bool(m['normal'].iloc[0])
    fr2 = fr.copy()
    fr2['shock_usdkrw_pct'] = fr2['shock_usdkrw_pct'] * 5                          # 시험 분포가 바뀌어도 기준은 그대로
    q_before = c.train['shock_usdkrw_pct'].quantile(0.9)
    C.regime_masks(c.train, fr2)
    assert c.train['shock_usdkrw_pct'].quantile(0.9) == q_before
    assert m['all'].all()


def test_range_check_flags_extrapolation():
    c = ctx(5)
    hi = float(c.train['shock_us10y_bp'].max())
    r = C.range_check(c.train, {'shock_us10y_bp': hi * 2 + 1, 'shock_usdkrw_pct': 0.0})
    assert r['shock_us10y_bp']['outside'] and not r['shock_usdkrw_pct']['outside']


# ------------------------------------------------------------ 재현성과 분위수
def test_same_seed_same_results():
    c = ctx(5)
    a, b = D.run(c, blend=0.3), D.run(c, blend=0.3)
    assert np.array_equal(a['pred']['center'], b['pred']['center'])
    e1, e2 = E.run(c), E.run(c)
    assert np.array_equal(e1['pred']['hi_cqr_90'], e2['pred']['hi_cqr_90'])


def test_quantile_crossing_report_and_sorted_use():
    raw = np.array([[0, 1, 2, 3, 4, 5, 6], [0, 2, 1, 3, 4, 5, 6], [0, 1, 2, 3, 5, 4, 6]], dtype=float)
    rep = E.crossing_report(raw)
    assert abs(rep['rows_with_any_crossing'] - 2 / 3) < 1e-12
    r = E.run(ctx(5))
    p = r['pred']
    cols = [E.qtag(t) for t in E.TAUS]
    assert (np.diff(p[cols].to_numpy(), axis=1) >= -1e-9).all()
    assert (p['hi_cqr_90'] > p['lo_cqr_90']).all() or (p['hi_cqr_90'] >= p['lo_cqr_90']).all()


def test_parallel_quantile_fit_matches_sequential():
    c = ctx(5)
    base = E.QuantileSet(c.ycol).fit(c.train).predict_norm(c.test)
    import os
    real = os.cpu_count
    os.cpu_count = lambda: 1                                # 순차 학습 경로 강제
    try:
        seq = E.QuantileSet(c.ycol).fit(c.train).predict_norm(c.test)
    finally:
        os.cpu_count = real
    assert np.array_equal(base, seq)


def test_wider_level_gives_wider_interval():
    p = D.run(ctx(5), blend=0.3)['pred']
    for v in D.VARIANTS:
        assert ((p[f'hi_{v}_95'] - p[f'lo_{v}_95']) >= (p[f'hi_{v}_90'] - p[f'lo_{v}_90']) - 1e-9).all()
        assert ((p[f'hi_{v}_90'] - p[f'lo_{v}_90']) >= (p[f'hi_{v}_80'] - p[f'lo_{v}_80']) - 1e-9).all()


# ------------------------------------------------------------ 저장과 전체 흐름
def test_write_table_roundtrip():
    df = pd.DataFrame({'trading_date': pd.to_datetime(['2024-01-02', '2024-01-03']), 'target_date': pd.to_datetime(['2024-01-09', '2024-01-10']),
                       'asset_id': ['000001', '000002'], 'v': [1.5, 2.5]})
    with tempfile.TemporaryDirectory() as d:
        path = C.write_table(df, Path(d) / 'x.parquet')
        back = C.read_table(Path(d) / 'x.parquet')
    assert Path(path).suffix in ('.parquet', '.csv')
    assert list(back['asset_id']) == ['000001', '000002'] and np.allclose(back['v'], df['v'])


def test_end_to_end_outputs_complete():
    ctxs, results, preds = {}, {}, {}
    for h in (5,):
        c = ctx(h)
        ctxs[h] = c
        for key, mod in (('D', D), ('E', E)):
            results[(key, h)] = mod.run(c)
            preds[(key, h)] = results[(key, h)]['pred']
    comp, final, cov, paired, scn = CM.build_outputs(ctxs, results, preds, horizons=(5,))
    assert len(final) == 2 and final[['mae', 'rmse', 'coverage_80', 'coverage_90', 'coverage_95']].notna().all().all()
    assert {'regime', 'year', 'asset', 'asymmetry', 'conformal_before_after'} <= set(cov['group_type'])
    assert scn['range_status'].isin(['IN_RANGE', 'RARE', 'OUT_OF_RANGE']).all()
    ext = scn[scn['scenario'] == 'extreme_combo']
    assert (ext['range_status'] == 'OUT_OF_RANGE').all()                              # 극단 충격은 외삽 표시
    assert (scn['lower_pct'] <= scn['center_pct'] + 1e-9).all() and (scn['upper_pct'] >= scn['center_pct'] - 1e-9).all()
    assert scn['asof'].nunique() == 1 if 'asof' in scn else scn['as_of'].nunique() == 1
    # 모델 D는 같은 종목에서 충격이 바뀌어도 구간 폭이 같다(구조상), E는 달라질 수 있음
    d = scn[(scn['model'] == 'Model D') & (scn['target_coverage'] == 0.9) & (scn['asset_id'] == c.assets[0])]
    assert np.allclose(d['width_pct'], d['width_pct'].iloc[0])


def run_all() -> int:
    tests = [(k, v) for k, v in sorted(globals().items()) if k.startswith('test_') and callable(v)]
    bad = 0
    for name, fn in tests:
        try:
            fn()
            print(f'  통과  {name}')
        except Exception:
            bad += 1
            print(f'  실패  {name}')
            traceback.print_exc()
    print(f'\n{len(tests) - bad}/{len(tests)} 통과')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(run_all())
