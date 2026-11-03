"""A: 시장 상태 검색. 지금과 비슷했던 과거 날짜를 찾고 그때 실제로 있었던 반응을 보여줍니다. (analytics/README.md 8절)

    python analytics/src/market_search.py                    # 가장 최근 상태로 검색 (VS Code ▶ 실행도 같습니다)
    python analytics/src/market_search.py --as-of 2024-03-15  # 그날 시점의 상태로, 그 이전 자료만 검색
    -> analytics/outputs/market_search/*.csv, search_config.json
    먼저 features.py, build_samples.py, splits.py를 실행해 두세요.

무엇을 하나
  5절의 시장 상태(8개)만 사용합니다. 학습 구간의 평균과 표준편차로 표준화한 뒤 유클리드 거리가 가까운
  과거 날짜 K개를 후보로 냅니다. 후보마다 거리, 어떤 상태가 비슷하거나 달랐는지, 당시 실제 충격(S)과
  종목 반응(y)을 함께 보여줍니다.

지키는 규칙
  - 사용자 충격은 입력이 아닙니다. 같은 상태와 같은 평가 시점이면 충격을 바꿔도 후보가 같습니다.
  - 평가 시점 as_of 이후 자료는 검색하지 않습니다. 후보 날짜 < as_of 이고, 후속 5거래일 반응이 끝나는
    날짜(target_date) < as_of 인 날짜만 후보가 됩니다. as_of 시점에 아직 관측되지 않은 반응은 보여주지 않습니다.
  - 표준화 기준은 학습 구간 날짜에서만 구합니다.
  - 인접 날짜는 같은 사건입니다. 검색된 행 수(n_rows)와 겹치지 않는 사건 수(n_events)를 구분해 보고합니다.

이 검색은 과거에 비슷했던 사례를 보여줄 뿐 예측이나 인과 검증이 아닙니다. 비슷한 사례가 적거나 먼 경우
거리 값으로 그 한계를 드러냅니다.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

try:
    from features import ANALYTICS_ROOT, MARKET_FEATURES
    from targets import HORIZON, SHOCK_COLUMNS, to_simple_return_pct
except ImportError:  # 패키지로 가져올 때
    from .features import ANALYTICS_ROOT, MARKET_FEATURES
    from .targets import HORIZON, SHOCK_COLUMNS, to_simple_return_pct

SEARCH_VERSION = 'market-search-v1.0'
DEFAULT_MARKET_STATE = ANALYTICS_ROOT / 'outputs/features/market_state.parquet'
DEFAULT_SAMPLES = ANALYTICS_ROOT / 'outputs/samples/training_samples.parquet'
DEFAULT_ASSIGNMENTS = ANALYTICS_ROOT / 'outputs/splits/split_assignments.parquet'
DEFAULT_OUT = ANALYTICS_ROOT / 'outputs/market_search'
# 날짜 단위(시장 공통)의 학습 제외 사유. 종목별 사유(가격, 상태 피처)는 후보 자격과 무관합니다.
MARKET_REASON_TOKENS = ['no_horizon', 'shock_endpoint_missing', 'wti_nonpositive', 'shock_interval_gap']


@dataclass
class SearchConfig:
    k: int = 20                          # 후보 행 수
    event_gap_trading_days: int = 10     # 후보 날짜 간격이 이 이하이면 같은 사건으로 묶음
    similar_z: float = 0.5               # |표준화 차이| <= 이 값이면 "비슷한 상태"
    different_z: float = 1.0             # |표준화 차이| > 이 값이면 "다른 상태"
    features: list = field(default_factory=lambda: list(MARKET_FEATURES))
    weights: dict | None = None          # None이면 모든 변수 동일 가중치
    metric: str = 'euclidean on train-standardized state'
    version: str = SEARCH_VERSION


@dataclass
class SearchResult:
    as_of: pd.Timestamp
    query_raw: dict
    query_z: dict
    candidates: pd.DataFrame      # 후보 행: 순위, 날짜, 거리, 사건, 상태 차이
    events: pd.DataFrame          # 사건 단위 요약
    outcomes: pd.DataFrame        # 후보 날짜의 실제 충격 S와 종목 반응 y (로그수익률 %)
    pool_size: int                # as_of 시점에 후보가 될 수 있었던 날짜 수
    config: SearchConfig

    @property
    def n_rows(self) -> int:
        return int(len(self.candidates))

    @property
    def n_events(self) -> int:
        return int(len(self.events))


def _label_events(positions: np.ndarray, gap: int) -> np.ndarray:
    """달력 위치가 gap 이내로 이어진 후보를 한 사건으로 묶습니다. 번호는 순위 순으로 붙입니다."""
    order = np.argsort(positions, kind='stable')
    new = np.r_[True, np.diff(positions[order]) > gap]
    chain = np.empty(len(positions), dtype=int)
    chain[order] = np.cumsum(new) - 1
    relabel, out = {}, np.empty(len(positions), dtype=int)
    for i, c in enumerate(chain):                      # positions는 순위 순서
        out[i] = relabel.setdefault(c, len(relabel) + 1)
    return out


class MarketSearch:
    def __init__(self, market_state: pd.DataFrame, samples: pd.DataFrame, train_dates, config: SearchConfig | None = None):
        self.config = cfg = config or SearchConfig()
        ms = market_state.sort_values('trading_date').reset_index(drop=True)
        self.dates = pd.DatetimeIndex(ms['trading_date'])
        self.X = ms[cfg.features].to_numpy(dtype=float)
        finite = np.isfinite(self.X).all(axis=1)

        # 표준화 기준: 학습 구간 날짜에서만 구함
        in_train = self.dates.isin(pd.DatetimeIndex(train_dates)) & finite
        if in_train.sum() < 30:
            raise ValueError('표준화 기준을 구할 학습 구간 날짜가 너무 적습니다.')
        self.mean = self.X[in_train].mean(axis=0)
        self.std = self.X[in_train].std(axis=0, ddof=1)
        if not (self.std > 0).all():
            raise ValueError('표준편차가 0인 상태 변수가 있습니다.')
        self.scaler_info = {'train_dates': int(in_train.sum()),
                            'train_start': str(self.dates[in_train].min())[:10], 'train_end': str(self.dates[in_train].max())[:10],
                            'mean': dict(zip(cfg.features, self.mean.round(8).tolist())),
                            'std': dict(zip(cfg.features, self.std.round(8).tolist()))}
        self.Z = (self.X - self.mean) / self.std
        w = cfg.weights or {}
        self.w = np.array([float(w.get(f, 1.0)) for f in cfg.features])

        # 날짜별 후속 반응(충격 S), 정답 종료일, 후보 자격은 build_samples 결과에서 가져옴
        s = samples.copy()
        s['exclude_reasons'] = s['exclude_reasons'].fillna('')
        s['trading_date'] = pd.to_datetime(s['trading_date'])
        by_date = s.groupby('trading_date')
        info = pd.DataFrame({'target_date': by_date['target_date'].first()})
        info['market_flag'] = s['exclude_reasons'].str.contains('|'.join(MARKET_REASON_TOKENS)).groupby(s['trading_date']).any()
        shocks = by_date[SHOCK_COLUMNS].first()
        if not info.index.equals(pd.DatetimeIndex(self.dates)):
            raise ValueError('market_state와 학습 표의 거래일이 다릅니다. 같은 입력으로 다시 만드세요.')
        self.target = pd.DatetimeIndex(pd.to_datetime(info['target_date'])).to_numpy()
        self.shocks = shocks
        self.eligible = (finite & ~info['market_flag'].to_numpy() & shocks.notna().all(axis=1).to_numpy()
                         & pd.notna(self.target))
        # 종목 반응: 가격 문제가 있는 행은 보여주지 않음
        ok = s['y_log_return_5d'].notna() & ~s['exclude_reasons'].str.contains('price_')
        self.y = (s[ok].pivot(index='trading_date', columns='asset_id', values='y_log_return_5d')
                  .reindex(self.dates).add_prefix('y_'))

    # ------------------------------------------------------------ 검색
    def _query(self, state) -> np.ndarray:
        q = np.array([float(state[f]) for f in self.config.features])
        if not np.isfinite(q).all():
            raise ValueError('상태에 결측이 있어 검색할 수 없습니다: ' +
                             str([f for f, v in zip(self.config.features, q) if not np.isfinite(v)]))
        return q

    def _core(self, zq: np.ndarray, as_of, k: int):
        as_of = np.datetime64(pd.Timestamp(as_of))
        pool = self.eligible & (self.dates.to_numpy() < as_of) & (self.target < as_of)   # 후속 반응이 as_of 전에 끝난 날짜만
        idx = np.flatnonzero(pool)
        if idx.size == 0:
            raise ValueError('검색 가능한 과거 날짜가 없습니다.')
        diff = self.Z[idx] - zq
        dist = np.sqrt((self.w * diff ** 2).sum(axis=1))
        order = np.argsort(dist, kind='stable')[:k]       # 거리가 같으면 오래된 날짜가 먼저
        return idx[order], dist[order], diff[order], int(idx.size)

    def search(self, state, as_of, k: int | None = None) -> SearchResult:
        """state: 8개 시장 상태 값(dict 또는 Series). 충격은 입력이 아닙니다."""
        q = self._query(state)
        return self._result(q, (q - self.mean) / self.std, as_of, k or self.config.k)

    def _result(self, q, zq, as_of, k) -> SearchResult:
        cfg, feats = self.config, self.config.features
        sel, dist, dz, pool_size = self._core(zq, as_of, k)
        events = _label_events(sel, cfg.event_gap_trading_days)
        cand = pd.DataFrame({'rank': np.arange(1, len(sel) + 1), 'trading_date': self.dates[sel],
                             'target_date': pd.DatetimeIndex(self.target[sel]), 'distance': dist, 'event_id': events})
        for j, f in enumerate(feats):
            cand[f] = self.X[sel, j]
        for j, f in enumerate(feats):
            cand[f'dz_{f}'] = dz[:, j]
        cand['similar_features'] = [';'.join(f for _, f in sorted((abs(d), f) for d, f in zip(row, feats) if abs(d) <= cfg.similar_z))
                                    for row in dz]
        cand['different_features'] = [';'.join(f for _, f in sorted(((abs(d), f) for d, f in zip(row, feats) if abs(d) > cfg.different_z),
                                                                     reverse=True)) for row in dz]
        assert (cand['trading_date'] < pd.Timestamp(as_of)).all() and (cand['target_date'] < pd.Timestamp(as_of)).all()

        pos = {d: i for i, d in enumerate(self.dates)}
        g = cand.assign(pos=cand['trading_date'].map(pos)).groupby('event_id')
        ev = g.agg(n_rows=('rank', 'size'), first_date=('trading_date', 'min'), last_date=('trading_date', 'max'),
                   best_rank=('rank', 'min'), best_distance=('distance', 'min'), mean_distance=('distance', 'mean'),
                   span_trading_days=('pos', lambda p: int(p.max() - p.min()))).reset_index()
        best = cand.sort_values('rank').drop_duplicates('event_id').set_index('event_id')['trading_date']
        ev.insert(2, 'best_date', ev['event_id'].map(best))

        outcomes = pd.concat([self.shocks.loc[cand['trading_date']].reset_index(),
                              self.y.loc[cand['trading_date']].reset_index(drop=True)], axis=1)
        return SearchResult(pd.Timestamp(as_of), dict(zip(feats, map(float, q))), dict(zip(feats, map(float, zq))),
                            cand, ev, outcomes, pool_size, cfg)


# ---------------------------------------------------------------- 결과 요약과 점검
def _summarize(outcomes: pd.DataFrame, event_of_date: pd.Series, columns) -> pd.DataFrame:
    """행이 아니라 사건 단위로 평균을 낸 뒤 사건들의 중앙값을 봅니다. 한 사건이 여러 행으로 결과를 좌우하지 못합니다."""
    o = outcomes.assign(event_id=outcomes['trading_date'].map(event_of_date))
    ev_mean = o.groupby('event_id')[columns].mean()
    rows = []
    for c in columns:
        e = ev_mean[c].dropna()
        med = float(e.median()) if len(e) else np.nan
        rows.append({'outcome': c, 'rows_with_data': int(o[c].notna().sum()), 'events_with_data': int(len(e)),
                     'event_median': med, 'event_mean': float(e.mean()) if len(e) else np.nan,
                     'share_negative_events': float((e < 0).mean()) if len(e) else np.nan,
                     'event_median_display': (float(to_simple_return_pct(med)) if c.startswith('y_') else med)})
    return pd.DataFrame(rows)


def summarize_outcomes(result: SearchResult, columns=None) -> pd.DataFrame:
    cols = columns or [c for c in result.outcomes.columns if c != 'trading_date']
    mapping = result.candidates.set_index('trading_date')['event_id']
    return _summarize(result.outcomes, mapping, cols)


def leave_one_event_out(result: SearchResult, columns=None) -> pd.DataFrame:
    """사건을 하나씩 빼고 다시 요약합니다. event_median의 부호가 뒤집히면 sign_flipped=True입니다."""
    cols = columns or [c for c in result.outcomes.columns if c != 'trading_date']
    mapping = result.candidates.set_index('trading_date')['event_id']
    base = _summarize(result.outcomes, mapping, cols).set_index('outcome')
    rows = []
    if result.n_events < 2:
        return pd.DataFrame(columns=['dropped_event', 'outcome', 'event_median_without', 'delta', 'sign_flipped', 'events_remaining'])
    for e in result.events['event_id']:
        keep = mapping[mapping != e].index
        s = _summarize(result.outcomes[result.outcomes['trading_date'].isin(keep)], mapping, cols).set_index('outcome')
        for c in cols:
            b, n = base.loc[c, 'event_median'], s.loc[c, 'event_median']
            rows.append({'dropped_event': int(e), 'outcome': c, 'event_median_without': n, 'delta': n - b,
                         'sign_flipped': bool(np.isfinite(b) and np.isfinite(n) and b != 0 and np.sign(b) != np.sign(n)),
                         'events_remaining': int(result.n_events - 1)})
    return pd.DataFrame(rows)


def stability_report(searcher: MarketSearch, state, as_of, levels=(0.0, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0),
                     n_draws: int = 200, seed: int = 0, k: int | None = None) -> pd.DataFrame:
    """표준화한 상태에 표준편차 단위의 잡음을 더해 다시 검색합니다.
    작은 잡음에서 겹침 비율이 높고, 잡음이 커질수록 겹침이 줄고 가장 가까운 거리가 늘어야 합니다."""
    k = k or searcher.config.k
    q = searcher._query(state)
    z0 = (q - searcher.mean) / searcher.std
    base_idx = set(searcher._core(z0, as_of, k)[0].tolist())
    rng = np.random.default_rng(seed)
    rows = []
    for lv in levels:
        overlap, nearest, n_events = [], [], []
        for _ in range(1 if lv == 0 else n_draws):
            sel, dist, _, _ = searcher._core(z0 + lv * rng.standard_normal(z0.size), as_of, k)
            overlap.append(len(base_idx & set(sel.tolist())) / len(base_idx))
            nearest.append(dist[0])
            n_events.append(len(set(_label_events(sel, searcher.config.event_gap_trading_days))))
        rows.append({'noise_sigma': lv, 'draws': len(overlap), 'overlap_mean': float(np.mean(overlap)),
                     'overlap_p05': float(np.percentile(overlap, 5)), 'nearest_distance_median': float(np.median(nearest)),
                     'n_events_median': float(np.median(n_events))})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- 저장과 진입점
def write_search(result: SearchResult, searcher: MarketSearch, stability: pd.DataFrame, loeo: pd.DataFrame,
                 out_dir, data_meta: dict | None = None) -> dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    summary = summarize_outcomes(result)
    tables = {'candidates': result.candidates, 'events': result.events, 'outcomes': result.outcomes,
              'outcome_summary': summary, 'stability': stability, 'leave_one_event_out': loeo}
    paths = {}
    for name, t in tables.items():
        p = out / f'search_{name}.csv'
        t.to_csv(p, index=False, encoding='utf-8-sig', date_format='%Y-%m-%d', float_format='%.6g')
        paths[name] = str(p)
    flips = (loeo.loc[loeo['sign_flipped'], ['dropped_event', 'outcome']] if len(loeo) else loeo)
    config = {
        'search_version': SEARCH_VERSION, 'created_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'config': asdict(result.config), 'scaler': searcher.scaler_info,
        'query': {'as_of': str(result.as_of)[:10], 'state_raw': result.query_raw, 'state_z': result.query_z},
        'pool_size': result.pool_size, 'n_rows': result.n_rows, 'n_events': result.n_events,
        'nearest_distance': float(result.candidates['distance'].min()), 'kth_distance': float(result.candidates['distance'].max()),
        'leave_one_event_out': {'events_tested': int(loeo['dropped_event'].nunique()) if len(loeo) else 0,
                                'sign_flips': int(len(flips)),
                                'flipping_events': sorted({int(e) for e in flips['dropped_event']}) if len(flips) else []},
        'data': data_meta or {},
        'rules': ['사용자 충격은 검색 입력이 아니다.', '후보 날짜 < as_of 이고 정답 종료일 < as_of 인 날짜만 후보다.',
                  '표준화 기준은 학습 구간에서만 구한다.', 'n_rows(검색 행 수)와 n_events(겹치지 않는 사건 수)를 구분한다.'],
        'notes': ['과거에 비슷했던 사례를 보여줄 뿐 예측이나 인과 검증이 아니다.',
                  '후보 평가 구간 결과를 보고 k나 규칙을 바꿨다면 splits.mark_evaluation_exposed()로 기록한다.'],
    }
    p = out / 'search_config.json'
    p.write_text(json.dumps(config, ensure_ascii=False, indent=2, default=str) + '\n', encoding='utf8')
    paths['config'] = str(p)
    return paths


def main(argv=None):
    a = argparse.ArgumentParser(description='시장 상태 검색(A)')
    a.add_argument('--as-of', help='평가 시점(YYYY-MM-DD). 그날의 상태로 검색하고 그 이전 자료만 씁니다. 기본: 마지막 날짜')
    a.add_argument('--k', type=int, default=SearchConfig.k, help='후보 행 수 (기본 20)')
    a.add_argument('--event-gap', type=int, default=SearchConfig.event_gap_trading_days, help='같은 사건으로 묶는 거래일 간격 (기본 10)')
    a.add_argument('--market-state', default=str(DEFAULT_MARKET_STATE))
    a.add_argument('--samples', default=str(DEFAULT_SAMPLES))
    a.add_argument('--assignments', default=str(DEFAULT_ASSIGNMENTS))
    a.add_argument('--out', default=str(DEFAULT_OUT), help='저장 폴더 (기본: analytics/outputs/market_search)')
    args = a.parse_args(argv)
    for p in [args.market_state, args.samples, args.assignments]:
        if not Path(p).exists():
            raise SystemExit(f'{p} 가 없습니다. features.py, build_samples.py, splits.py를 먼저 실행하세요.')

    ms, samples, assign = pd.read_parquet(args.market_state), pd.read_parquet(args.samples), pd.read_parquet(args.assignments)
    train_dates = assign.loc[assign['split'] == 'train', 'trading_date'].unique()
    cfg = SearchConfig(k=args.k, event_gap_trading_days=args.event_gap)
    searcher = MarketSearch(ms, samples, train_dates, cfg)
    as_of = pd.Timestamp(args.as_of) if args.as_of else searcher.dates.max()
    row = ms.loc[ms['trading_date'] == as_of]
    if row.empty:
        raise SystemExit(f'{as_of.date()} 는 거래일 목록에 없습니다.')
    state = row.iloc[0]
    result = searcher.search(state, as_of)
    stability = stability_report(searcher, state, as_of)
    loeo = leave_one_event_out(result)
    meta_path = Path(args.samples).with_name('samples_metadata.json')
    smeta = json.loads(meta_path.read_text(encoding='utf8')) if meta_path.exists() else {}
    data_meta = {k: smeta.get(k) for k in ['dataset_version', 'feature_version', 'target_version', 'market_state_sha256']}
    paths = write_search(result, searcher, stability, loeo, args.out, data_meta)
    print(json.dumps({'as_of': str(as_of)[:10], 'n_rows': result.n_rows, 'n_events': result.n_events,
                      'pool_size': result.pool_size, 'nearest_distance': round(float(result.candidates['distance'].min()), 4),
                      'kth_distance': round(float(result.candidates['distance'].max()), 4),
                      'events': result.events[['event_id', 'n_rows', 'best_date', 'best_distance']].astype(str).to_dict('records'),
                      'files': paths}, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
