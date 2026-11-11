"""일별 파이프라인 계산 점검. (analytics/README.md 11절)

    python analytics/tests/test_daily_pipeline.py       # VS Code ▶ 실행, 인자 없음
    pytest analytics/tests                               # pytest로도 같은 검사를 돌립니다

합성 데이터만 사용하므로 Gold 파일 없이 몇 초 안에 끝납니다.
확인: 종목 사이 섞임 없음 / 5거래일 달력 / 미래 정보 차단 / 단위 변환 / 동일 날짜 결합 표본 /
      손익 합계와 ES 기여도 / 재현성 / 분할 경계.
"""
from __future__ import annotations

import math
import sys
import traceback
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
import build_samples as BS  # noqa: E402
import features as FT  # noqa: E402
import load_gold as LG  # noqa: E402
import portfolio as PF  # noqa: E402
import splits as SP  # noqa: E402
import targets as TG  # noqa: E402
sys.path.insert(0, str(ROOT / 'model_compare'))
from distribution import ScaledRidgeModel, with_scales  # noqa: E402
import extra_features as XF  # noqa: E402

ASSETS = ('000001', '000002', '000003')
N = 1000
_cache: dict = {}


def synth_gold(n=N, assets=ASSETS, seed=0, price_by_asset=None) -> pd.DataFrame:
    """Gold 계약 열을 모두 가진 합성 표. 종목별 가격은 서로 다른 난수 보행입니다."""
    rng = np.random.default_rng(seed)
    days = pd.bdate_range('2019-01-01', periods=n)
    mk = pd.DataFrame({'trading_date': days})
    mk['kospi_close'] = 2000 * np.exp(np.cumsum(rng.normal(0, .01, n)))
    mk['usdkrw'] = 1100 * np.exp(np.cumsum(rng.normal(0, .004, n)))
    mk['us_treasury_10y'] = 2 + np.cumsum(rng.normal(0, .03, n))
    mk['wti'] = 60 * np.exp(np.cumsum(rng.normal(0, .015, n)))
    mk['vix'] = np.abs(18 + np.cumsum(rng.normal(0, .5, n))) + 5
    mk['korea_3y'] = 2 + np.cumsum(rng.normal(0, .02, n))
    rows = []
    for a in assets:
        px = np.round(10000 * np.exp(np.cumsum(rng.normal(0, .015, n)))).astype(int)
        if price_by_asset and a in price_by_asset:
            px = np.asarray(price_by_asset[a])
        d = mk.copy()
        d['asset_id'], d['close'], d['volume'] = a, px, 1_000_000
        rows.append(d)
    df = pd.concat(rows, ignore_index=True)
    defaults = dict(sector_id=None, instrument_kind='stock', price_basis='adjusted', adjustment_version='synthetic-v1',
                    price_available_at=np.nan, source_ref='synthetic', dataset_version='synthetic-v1', quality_status='valid',
                    is_mock=False)
    for c, v in defaults.items():
        df[c] = v
    for f in ['usdkrw', 'us_treasury_10y', 'wti', 'vix', 'korea_3y']:
        df[f'{f}_observation_date'] = df.groupby('asset_id')['trading_date'].shift(1)
        df[f'{f}_observation_date'] = df[f'{f}_observation_date'].fillna(df['trading_date'] - pd.Timedelta(days=3))
        for suf in ('observed_at', 'available_at'):
            df[f'{f}_{suf}'] = np.nan
    return df


def pipeline(seed=0, **kw):
    key = (seed, tuple(sorted((k, str(v)) for k, v in kw.items())))
    if key not in _cache:
        gold = LG.load_gold(synth_gold(seed=seed, **kw))
        fs = FT.build_features(gold)
        samples, meta = BS.build_samples(gold, fs)
        _cache[key] = (gold, fs, samples, meta)
    return _cache[key]


# ------------------------------------------------------------ 5거래일 달력과 단위
def test_target_is_five_trading_days_ahead_per_asset():
    gold, fs, s, _ = pipeline()
    ok = s.dropna(subset=['y_log_return_5d'])
    assert len(ok) > 500
    px = gold.set_index(['asset_id', 'trading_date'])['close']
    cal = pd.Index(sorted(gold['trading_date'].unique()))
    for _, r in ok.sample(40, random_state=1).iterrows():
        i = cal.get_loc(r['trading_date'])
        t5 = cal[i + 5]
        assert pd.Timestamp(r['target_date']) == t5, '목표일이 5거래일 뒤가 아님'
        want = 100 * math.log(px[(r['asset_id'], t5)] / px[(r['asset_id'], r['trading_date'])])
        assert abs(r['y_log_return_5d'] - want) < 1e-9, '로그수익률 계산이 다름'


def test_no_cross_asset_mixing():
    """한 종목 가격을 바꿔도 다른 종목의 정답/특징은 그대로여야 합니다."""
    _, _, base, _ = pipeline()
    rng = np.random.default_rng(99)
    px2 = np.round(10000 * np.exp(np.cumsum(rng.normal(0, .03, N)))).astype(int)
    _, _, alt, _ = pipeline(price_by_asset={'000002': px2})
    for a in ('000001', '000003'):
        x = base[base['asset_id'] == a].reset_index(drop=True)
        y = alt[alt['asset_id'] == a].reset_index(drop=True)
        cols = [c for c in x.columns if c in y.columns and x[c].dtype.kind in 'fi']
        pd.testing.assert_frame_equal(x[cols], y[cols], check_exact=False, rtol=1e-12)
    xa = base[base['asset_id'] == '000002']['y_log_return_5d'].to_numpy()
    ya = alt[alt['asset_id'] == '000002']['y_log_return_5d'].to_numpy()
    assert not np.allclose(xa, ya, equal_nan=True), '바꾼 종목의 정답이 그대로임(검사 무효)'


def test_shock_units():
    gold, _, _, _ = pipeline()
    sh = TG.build_market_shocks(gold).dropna(subset=['shock_usdkrw_pct', 'shock_us10y_bp', 'shock_wti_pct', 'shock_vix_pt'])
    m = FT.market_table(gold).set_index('trading_date')
    cal = list(m.index)
    for _, r in sh.sample(15, random_state=2).iterrows():
        i = cal.index(r['trading_date'])
        a, b = m.iloc[i], m.iloc[i + 5]
        assert abs(r['shock_usdkrw_pct'] - (b['usdkrw'] / a['usdkrw'] - 1) * 100) < 1e-9
        assert abs(r['shock_wti_pct'] - (b['wti'] / a['wti'] - 1) * 100) < 1e-9
        assert abs(r['shock_us10y_bp'] - (b['us_treasury_10y'] - a['us_treasury_10y']) * 100) < 1e-9, '금리는 %p→bp(×100)'
        assert abs(r['shock_vix_pt'] - (b['vix'] - a['vix'])) < 1e-9


def test_log_to_simple_return_conversion():
    assert abs(TG.to_simple_return_pct(100 * math.log(66500 / 70000)) - (-5.0)) < 1e-9
    assert abs(float(TG.to_simple_return_pct(0.0))) < 1e-12
    assert float(TG.to_simple_return_pct(-1000.0)) > -100.0, '일반 수익률은 -100% 아래로 내려가지 않음'


# ------------------------------------------------------------ 미래 정보 차단
def test_state_features_use_only_past_data():
    """t 이후 가격/시장값을 바꿔도 t 시점 상태와 종목 특징은 변하지 않아야 합니다."""
    gold, fs, _, _ = pipeline()
    cut = sorted(gold['trading_date'].unique())[700]
    g2 = gold.copy()
    late = g2['trading_date'] > cut
    rng = np.random.default_rng(5)
    days = sorted(gold['trading_date'].unique())
    for c in ['kospi_close', 'usdkrw', 'wti', 'vix', 'us_treasury_10y', 'korea_3y']:
        f = pd.Series(1 + rng.uniform(0.2, 0.5, len(days)), index=days)     # 날짜별 같은 배율(시장값은 종목 공통)
        g2.loc[late, c] = g2.loc[late, c] * g2.loc[late, 'trading_date'].map(f)
    g2.loc[late, 'close'] = (g2.loc[late, 'close'] * 1.7).round().astype(int)
    fs2 = FT.build_features(LG.load_gold(g2))
    a = fs.market_state[fs.market_state['trading_date'] <= cut].reset_index(drop=True)
    b = fs2.market_state[fs2.market_state['trading_date'] <= cut].reset_index(drop=True)
    num = [c for c in a.columns if a[c].dtype.kind == 'f']
    pd.testing.assert_frame_equal(a[num], b[num], check_exact=False, rtol=1e-12)
    fa = fs.asset_features[fs.asset_features['trading_date'] <= cut].reset_index(drop=True)
    fb = fs2.asset_features[fs2.asset_features['trading_date'] <= cut].reset_index(drop=True)
    num = [c for c in fa.columns if fa[c].dtype.kind == 'f']
    pd.testing.assert_frame_equal(fa[num], fb[num], check_exact=False, rtol=1e-12)


def test_splits_by_date_without_label_leak():
    _, _, s, _ = pipeline()
    a = SP.assign_splits(s, calibration_start='2021-07-01', evaluation_start='2022-06-01')
    cal0, ev0 = pd.Timestamp('2021-07-01'), pd.Timestamp('2022-06-01')
    t = SP.select_split(s, a, 'train')
    c = SP.select_split(s, a, 'calibration')
    assert len(t) and len(c)
    assert (t['target_date'] < cal0).all(), '학습 정답이 보정 구간 이후에 걸침'
    assert (c['trading_date'] >= cal0).all() and (c['target_date'] < ev0).all(), '보정 정답이 평가 구간 이후에 걸침'
    ev = SP.select_split(s, a, 'evaluation') if 'evaluation' in set(a['split']) else s.iloc[:0]
    if len(ev):
        assert (ev['trading_date'] >= ev0).all()
    assert len(set(map(tuple, t[['trading_date', 'asset_id']].to_numpy())) &
               set(map(tuple, c[['trading_date', 'asset_id']].to_numpy()))) == 0


# ------------------------------------------------------------ 결합 표본·재현성
def _fit(seed=0):
    _, fs, s, _ = pipeline(seed)
    a = SP.assign_splits(s, calibration_start='2021-07-01', evaluation_start='2022-06-01')
    ks = pd.DataFrame({'trading_date': fs.market_state['trading_date'], 'scale_kospi': 1.0})
    d = with_scales(s, ks)
    return ScaledRidgeModel(alpha=30).fit(SP.select_split(d, a, 'train')).calibrate(SP.select_split(d, a, 'calibration')), d, a


def test_joint_samples_same_date_rows():
    """같은 draw_id의 종목별 잔차는 같은 날짜의 잔차 행에서 와야 하고, 부족하면 insufficient로 표시합니다."""
    model, d, a = _fit()
    assets = model.assets[:2]
    idx = pd.bdate_range('2020-01-01', periods=60)
    rng = np.random.default_rng(3)
    res = pd.DataFrame(rng.normal(0, 1, (60, 2)), index=idx, columns=assets)
    res.iloc[:20, 1] = np.nan                       # 두 번째 종목은 앞 20일 잔차 없음
    model.residuals = res.reindex(columns=model.residuals.columns).copy() if False else res
    model.models = {k: model.models[k] for k in assets}
    q = d.dropna(subset=model.required_columns).iloc[0]
    sc = pd.Series({a_: 1.0 for a_ in assets})
    dr, info = model.draws(q, sc, assets)
    assert info['joint_sample_status'] == 'ok' and info['joint_rows'] == 40
    got = [pd.Timestamp(t) for t in info['residual_dates']]
    assert all(t >= idx[20] for t in got), '한 종목에 잔차가 없는 날짜가 결합 표본에 섞임'
    dr2, _ = model.draws(q, sc, assets)
    pd.testing.assert_frame_equal(dr, dr2)
    # 결합 가능한 날짜가 최소 개수보다 적으면 insufficient
    res2 = res.copy()
    res2.iloc[:, 1] = np.nan
    res2.iloc[:10, 1] = 0.1
    model.residuals = res2
    _, info2 = model.draws(q, sc, assets)
    assert info2['joint_sample_status'] == 'insufficient' and 'warning' in info2


def test_reproducible_with_same_input():
    m1, d, _ = _fit()
    m2, _, _ = _fit()
    q = d.dropna(subset=m1.required_columns + ['asset_scale']).iloc[0]
    sc = pd.Series({a: 1.5 for a in m1.assets})
    x, _ = m1.draws(q, sc)
    y, _ = m2.draws(q, sc)
    pd.testing.assert_frame_equal(x, y)
    assert m1.card['calibration']['dates'] == m2.card['calibration']['dates']


def test_extra_features_use_only_past_data_and_per_asset():
    """비교 실험용 추가 특징: t 이후 값을 바꿔도 t 이전 특징이 같고, 한 종목 가격이 다른 종목 베타를 바꾸지 않음."""
    gold, fs, _, _ = pipeline()
    clean = gold[~gold['is_mock']].reset_index(drop=True)
    base = XF.build_extra_features(clean, fs)
    cut = sorted(gold['trading_date'].unique())[700]
    g2 = gold.copy()
    late = g2['trading_date'] > cut
    rng = np.random.default_rng(8)
    days = sorted(gold['trading_date'].unique())
    for c in ['kospi_close', 'usdkrw', 'wti', 'vix', 'us_treasury_10y', 'korea_3y']:
        f = pd.Series(1 + rng.uniform(0.2, 0.5, len(days)), index=days)
        g2.loc[late, c] = g2.loc[late, c] * g2.loc[late, 'trading_date'].map(f)
    g2.loc[late, 'close'] = (g2.loc[late, 'close'] * 1.7).round().astype(int)
    g2 = LG.load_gold(g2)
    alt = XF.build_extra_features(g2[~g2['is_mock']].reset_index(drop=True), FT.build_features(g2))
    a = base[base['trading_date'] <= cut].reset_index(drop=True)
    b = alt[alt['trading_date'] <= cut].reset_index(drop=True)
    num = [c for c in a.columns if a[c].dtype.kind == 'f']
    pd.testing.assert_frame_equal(a[num], b[num], check_exact=False, rtol=1e-10)
    # 종목 격리: 000002 가격만 바꾸면 000001/000003 특징은 그대로
    rng2 = np.random.default_rng(77)
    px2 = np.round(10000 * np.exp(np.cumsum(rng2.normal(0, .03, N)))).astype(int)
    g3, fs3, _, _ = pipeline(price_by_asset={'000002': px2})
    alt3 = XF.build_extra_features(g3[~g3['is_mock']].reset_index(drop=True), fs3)
    for aid in ('000001', '000003'):
        x = base[base['asset_id'] == aid].reset_index(drop=True)
        y = alt3[alt3['asset_id'] == aid].reset_index(drop=True)
        cols = [c for c in XF.EXTRA_COLUMNS if c in x]
        pd.testing.assert_frame_equal(x[cols], y[cols], check_exact=False, rtol=1e-10)


# ------------------------------------------------------------ 손익
def test_pnl_sum_and_readme_example():
    d = pd.DataFrame({'005930': [100 * math.log(.95)], '005380': [100 * math.log(.97)]})
    p = PF.pnl_by_asset(d, {'005930': 5e7, '005380': 5e7})
    assert abs(p.sum(axis=1).iloc[0] - (-4_000_000)) < 1e-6, '5천만×(-5%)+5천만×(-3%) = -400만 원'
    assert abs(p['005930'].iloc[0] - (-2_500_000)) < 1e-6 and abs(p['005380'].iloc[0] - (-1_500_000)) < 1e-6


def test_es_contributions_sum_to_es_and_var_independent():
    rng = np.random.default_rng(0)
    for n in (30, 123, 400, 1000):
        d = pd.DataFrame(rng.normal(0, 6, (n, 3)), columns=list('abc'))
        h = {'a': 3e7, 'b': 1e7, 'c': 6e7}
        r = PF.risk_summary(PF.pnl_by_asset(d, h))
        tot = sum(h[c] * (np.exp(d[c] / 100) - 1) for c in 'abc').to_numpy()
        m = math.ceil(.05 * n - 1e-12)
        assert np.isclose(r['var95_krw'], -np.quantile(tot, .05))
        assert np.isclose(r['es95_krw'], -np.sort(tot)[:m].mean())
        assert np.isclose(r['contributions']['es_contribution_krw'].sum(), r['es95_krw'])
        assert r['es95_krw'] >= r['var95_krw'] - 1e-9


def test_holdings_validation():
    for bad in ({}, {'a': -1}, {'a': 0}, {'a': float('nan')}):
        try:
            PF.validate_holdings(bad)
        except ValueError:
            continue
        raise AssertionError(f'잘못된 보유가 통과: {bad}')


def test_missing_asset_draws_not_aggregated():
    d = pd.DataFrame({'a': [1.0, 2.0], 'b': [np.nan, 1.0]})
    try:
        PF.pnl_by_asset(d, {'a': 1e6, 'b': 1e6})
    except ValueError:
        return
    raise AssertionError('결측 표본이 합산됨')


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
