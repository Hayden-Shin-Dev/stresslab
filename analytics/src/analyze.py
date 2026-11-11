"""보유 종목과 충격으로 포트폴리오 손익 구간, 손실 위험, 종목별 기여도, 유사 사례를 만듭니다. (analytics/README.md 10절)

    python analytics/src/analyze.py          # VS Code ▶ 실행도 같습니다 (예시: 삼성전자 5천만 + 현대차 5천만, 환율 +2%, 미국 10년 +50bp)
    python analytics/src/analyze.py --holding 005930=30000000 --holding 000660=20000000 --usdkrw 3 --wti -10
    -> analytics/outputs/analyze/{analysis_summary.json, portfolio_pnl_samples.csv, portfolio_contributions.csv,
                                  similar_candidates.csv, similar_events.csv}
    먼저 train.py를 실행해 모델을 만들어 두세요(features, samples, splits도 필요).

구성
  B(predict.py)가 종목별 수익률 표본을 만들고, portfolio.py가 평가금액을 곱해 합산합니다.
  A(market_search.py)는 지금과 비슷했던 과거 날짜를 찾아 그때 실제 관측된 결과를 보여줍니다.
  관측된 과거 사실(observed, observed_history)과 모델 추정(model_estimate)은 서로 다른 항목에 둡니다.

재계산 규칙
  같은 일별 상태 + 같은 충격 + 같은 종목 집합이면 모델 수익률 표본을 다시 만들지 않고 재사용합니다.
  장중 현재가가 바뀌어 평가금액만 달라지면 표본은 그대로 두고 손익만 다시 곱합니다.
  충격이나 보유 종목이 바뀌면 표본부터 다시 만듭니다. (Analyzer.analyze의 draws_reused 필드 참고)

결과는 확정적인 예상 손실이나 검증된 인과효과가 아닙니다.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

try:
    import portfolio as PF
    import predict as P
    from distribution import MODEL_VERSION
    from features import ANALYTICS_ROOT
    from market_search import MarketSearch, SearchConfig, summarize_outcomes
    from targets import to_simple_return_pct
except ImportError:  # 패키지로 가져올 때
    from . import portfolio as PF
    from . import predict as P
    from .distribution import MODEL_VERSION
    from .features import ANALYTICS_ROOT
    from .market_search import MarketSearch, SearchConfig, summarize_outcomes
    from .targets import to_simple_return_pct

DEFAULT_OUT = ANALYTICS_ROOT / 'outputs/analyze'
EXAMPLE_HOLDINGS = {'005930': 50_000_000, '005380': 50_000_000}
DISCLAIMER = ('이 결과는 확정적인 예상 손실이 아닙니다. 과거 보정 구간(2020~2022)의 모델 잔차를 입력한 보유 금액과 충격에 적용한 '
              '시나리오 분포이며, 인과효과를 검증한 값도 아닙니다. 모델은 승인 전 비교용 연구 모델입니다.')


def normalize_holdings(raw: dict) -> tuple[pd.Series, dict]:
    """{종목: 금액} 또는 {종목: {'shares', 'price', 'reference_close'(선택)}} -> (평가금액 Series, 관측 정보)."""
    values, intraday = {}, {}
    for a, v in raw.items():
        if isinstance(v, dict):
            if 'value' in v:
                values[a] = float(v['value'])
            else:
                values[a] = float(v['shares']) * float(v['price'])
            if 'shares' in v and 'price' in v and v.get('reference_close') is not None:
                intraday[a] = float(v['shares']) * (float(v['price']) - float(v['reference_close']))
        else:
            values[a] = float(v)
    s = PF.validate_holdings(values)
    return s, {'intraday_pnl_krw_by_asset': intraday,
               'intraday_pnl_krw_total': float(sum(intraday.values())) if intraday else None}


class Analyzer:
    def __init__(self, model, card, kospi_scale, market_state, asset_features, searcher: MarketSearch | None = None):
        self.model, self.card, self.scale = model, card, kospi_scale
        self.ms, self.af, self.searcher = market_state, asset_features, searcher
        self._cache: dict = {}

    def _draws(self, assets, shocks, as_of):
        key = (str(pd.Timestamp(as_of))[:10] if as_of is not None else None, tuple(sorted(assets)),
               tuple(sorted((k, float(v)) for k, v in (shocks or {}).items() if v is not None)), MODEL_VERSION)
        if key in self._cache:
            return self._cache[key], True
        long, quant, meta = P.predict(self.model, self.ms, self.af, self.scale, shocks, as_of=as_of,
                                      assets=list(assets), card=self.card)
        wide = long.pivot(index='draw_id', columns='asset_id', values='log_return_pct')
        dates = long.drop_duplicates('draw_id').set_index('draw_id')['residual_date']
        self._cache[key] = (wide, dates, quant, meta)
        return self._cache[key], False

    def analyze(self, holdings: dict, shocks: dict | None = None, as_of=None, k: int = 20) -> dict:
        values, obs_hold = normalize_holdings(holdings)
        modelable = [a for a in values.index if a in self.model.models]
        excluded = {a: {'value_krw': float(values[a]), 'reason': 'no_model(학습 이력 없음 또는 보정 표본 부족)'}
                    for a in values.index if a not in self.model.models}
        if not modelable:
            raise ValueError('모델이 있는 보유 종목이 없습니다.')
        (wide, dates, quant, meta), reused = self._draws(modelable, shocks, as_of)
        if meta['model_estimate']['joint']['joint_sample_status'] != 'ok':
            raise ValueError('같은 날짜 잔차를 묶은 결합 표본이 부족해 포트폴리오를 계산하지 않습니다. 종목 수를 줄이거나 보정 구간을 넓히세요.')
        kept = values[modelable]
        pnl = PF.pnl_by_asset(wide, kept.to_dict())
        risk = PF.risk_summary(pnl)
        as_of_used = meta['observed']['state_as_of_trading_date']
        total_value = float(values.sum())
        warnings = list(meta['warnings']) + risk['warnings']
        if excluded:
            warnings.append(f"분포를 만들 수 없는 보유 종목 {sorted(excluded)}이(가) 계산에서 빠졌습니다. 결과는 보유 금액의 "
                            f"{kept.sum() / total_value:.1%}만 반영합니다.")
        similar = self._similar(as_of_used, kept, k)

        out = {
            'analysis_version': 'analyze-v1.0', 'created_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'),
            'model_version': MODEL_VERSION, 'model_status': meta['model_status'],
            'reproduction_status': meta['reproduction_status'], 'portfolio_version': PF.PORTFOLIO_VERSION,
            'horizon_trading_days': 5,
            'inputs': {'holdings_krw': {a: float(v) for a, v in values.items()}, 'total_value_krw': total_value,
                       'modeled_value_krw': float(kept.sum()), 'modeled_share': float(kept.sum() / total_value),
                       'excluded_holdings': excluded, 'shocks': meta['shocks']},
            'observed': {**meta['observed'], 'holdings': obs_hold},
            'model_estimate': {
                'draws_reused_from_cache': reused, 'n_samples': risk['n_samples'],
                'draw_basis': meta['model_estimate']['joint']['draw_basis'],
                'residual_dates_range': [str(dates.min()), str(dates.max())],
                'pnl_band_krw': risk['pnl_band_krw'], 'median_pnl_krw': risk['median_pnl_krw'],
                'share_of_samples_with_loss': risk['share_of_samples_with_loss'],
                'var95_krw': risk['var95_krw'], 'es95_krw': risk['es95_krw'],
                'var95_pct_of_modeled_value': risk['var95_krw'] / float(kept.sum()),
                'es95_pct_of_modeled_value': risk['es95_krw'] / float(kept.sum()),
                'method': {'loss_sign': risk['loss_sign'], 'quantile_method': risk['quantile_method'],
                           'tail_definition': risk['tail_definition'], 'tail_count': risk['tail_count'],
                           'tail_draw_ids': risk['tail_draw_ids'],
                           'contribution_rule': '포트폴리오 하위 꼬리에 해당한 같은 표본에서 종목 손익을 평균',
                           'return_conversion': '로그수익률 -> 일반 수익률 -> 평가금액 곱'},
                'contributions': risk['contributions'].to_dict('records')},
            'similar_cases': similar['summary'],
            'warnings': warnings, 'disclaimer': DISCLAIMER}
        out['_tables'] = {'pnl_samples': pnl.assign(portfolio_pnl_krw=risk['total_pnl_krw'], residual_date=dates.reindex(pnl.index)),
                          'contributions': risk['contributions'],
                          'similar_candidates': similar['candidates'], 'similar_events': similar['events']}
        return out

    # ---------------------------------------------------------------- A: 유사 사례
    def _similar(self, as_of_used, kept: pd.Series, k: int) -> dict:
        empty = pd.DataFrame()
        if self.searcher is None:
            return {'summary': {'status': 'unavailable', 'reason': '시장 검색(A) 입력이 없습니다.'}, 'candidates': empty, 'events': empty}
        as_of = pd.Timestamp(as_of_used)
        row = self.ms.loc[self.ms['trading_date'] == as_of]
        try:
            res = self.searcher.search(row.iloc[0], as_of, k)
        except ValueError as e:
            return {'summary': {'status': 'unavailable', 'reason': str(e)}, 'candidates': empty, 'events': empty}
        o = res.outcomes.copy()
        cols = [f'y_{a}' for a in kept.index]
        have = o[cols].notna().all(axis=1) if all(c in o.columns for c in cols) else pd.Series(False, index=o.index)
        simple = to_simple_return_pct(o.reindex(columns=cols).to_numpy(dtype=float)) / 100
        hist = pd.Series(np.where(have, (simple * kept.to_numpy()[None, :]).sum(axis=1), np.nan), index=o.index)
        ev_of = res.candidates.set_index('trading_date')['event_id']
        cand = res.candidates[['rank', 'trading_date', 'target_date', 'distance', 'event_id',
                               'similar_features', 'different_features']].copy()
        cand['observed_portfolio_pnl_krw'] = hist.to_numpy()
        ev_pnl = pd.DataFrame({'event_id': o['trading_date'].map(ev_of), 'p': hist}).groupby('event_id')['p'].mean()
        events = res.events.copy()
        events['observed_portfolio_pnl_krw_mean'] = events['event_id'].map(ev_pnl)
        valid = ev_pnl.dropna()
        summary = {
            'status': 'ok', 'as_of': str(as_of)[:10], 'search_version': res.config.version, 'metric': res.config.metric,
            'n_rows': res.n_rows, 'n_events': res.n_events, 'pool_size': res.pool_size,
            'nearest_distance': float(res.candidates['distance'].min()), 'kth_distance': float(res.candidates['distance'].max()),
            'observed_history': {
                'meaning': '비슷했던 과거 날짜에 현재 보유 금액을 그대로 들고 있었다면 실제 5거래일 뒤 손익(관측값, 예측 아님)',
                'events_with_all_assets': int(len(valid)),
                'event_median_pnl_krw': float(valid.median()) if len(valid) else None,
                'share_of_events_with_loss': float((valid < 0).mean()) if len(valid) else None},
            'caveats': ['후보 행은 인접 날짜라 같은 사건으로 묶입니다. 행 수보다 사건 수(n_events)를 보세요.',
                        '총 거리가 가까워도 개별 상태 변수는 다를 수 있습니다. similar_features/different_features 참고.',
                        '과거 사례는 현재 충격 입력과 무관하게 상태만으로 고른 것입니다.']}
        return {'summary': summary, 'candidates': cand, 'events': events}


def write_analysis(result: dict, out_dir) -> dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    tables = result['_tables']
    summary = {k: v for k, v in result.items() if k != '_tables'}
    paths = {'summary': out / 'analysis_summary.json', 'pnl_samples': out / 'portfolio_pnl_samples.csv',
             'contributions': out / 'portfolio_contributions.csv', 'similar_candidates': out / 'similar_candidates.csv',
             'similar_events': out / 'similar_events.csv'}
    paths['summary'].write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str) + '\n', encoding='utf8')
    tables['pnl_samples'].to_csv(paths['pnl_samples'], index_label='draw_id')
    tables['contributions'].to_csv(paths['contributions'], index=False)
    tables['similar_candidates'].to_csv(paths['similar_candidates'], index=False)
    tables['similar_events'].to_csv(paths['similar_events'], index=False)
    return {k: str(v) for k, v in paths.items()}


def build_analyzer(model_dir=P.MODEL_DIR, features_dir=P.FEATURE_DIR, samples_path=None, assignments_path=None) -> Analyzer:
    model, card, scale = P.load_model(model_dir)
    fd = Path(features_dir)
    ms, af = pd.read_parquet(fd / 'market_state.parquet'), pd.read_parquet(fd / 'asset_features.parquet')
    searcher = None
    sp = Path(samples_path or ANALYTICS_ROOT / 'outputs/samples/training_samples.parquet')
    ap = Path(assignments_path or ANALYTICS_ROOT / 'outputs/splits/split_assignments.parquet')
    if sp.exists() and ap.exists():
        assign = pd.read_parquet(ap)
        searcher = MarketSearch(ms, pd.read_parquet(sp), assign.loc[assign['split'] == 'train', 'trading_date'].unique(),
                                SearchConfig())
    return Analyzer(model, card, scale, ms, af, searcher)


def main(argv=None):
    p = argparse.ArgumentParser(description='포트폴리오 분석')
    p.add_argument('--holding', action='append', default=None, metavar='종목코드=금액(원)',
                   help='보유 종목과 평가금액. 여러 번 지정 가능. 생략하면 예시(삼성전자, 현대차 각 5천만 원)')
    p.add_argument('--as-of', default=None)
    p.add_argument('--k', type=int, default=20, help='유사 사례 후보 행 수')
    p.add_argument('--model-dir', default=str(P.MODEL_DIR))
    p.add_argument('--features-dir', default=str(P.FEATURE_DIR))
    p.add_argument('--out', default=str(DEFAULT_OUT))
    for k, unit in P.SHOCK_UNITS.items():
        p.add_argument('--' + k.split('_')[0], dest=k, type=float, default=None,
                       help=f'{k} 충격 ({unit}); 생략하면 0 가정'.replace('%', '%%'))
    a = p.parse_args(argv)
    holdings = dict(EXAMPLE_HOLDINGS)
    if a.holding:
        holdings = {}
        for h in a.holding:
            code, _, amount = h.partition('=')
            if not amount:
                raise SystemExit(f'--holding 형식은 종목코드=금액 입니다: {h}')
            holdings[code.strip()] = float(amount)
    shocks = {k: getattr(a, k) for k in P.SHOCK_KEYS}
    if all(v is None for v in shocks.values()):
        shocks = dict(P.EXAMPLE_SHOCKS)
        print('충격을 지정하지 않아 예시 충격을 사용합니다:', shocks)
    an = build_analyzer(a.model_dir, a.features_dir)
    result = an.analyze(holdings, shocks, as_of=a.as_of, k=a.k)
    paths = write_analysis(result, a.out)
    m = result['model_estimate']
    print(json.dumps({'files': paths, 'as_of': result['observed']['state_as_of_trading_date'],
                      'total_value_krw': result['inputs']['total_value_krw'], 'n_samples': m['n_samples'],
                      'pnl_band_krw': m['pnl_band_krw'], 'var95_krw': round(m['var95_krw']), 'es95_krw': round(m['es95_krw']),
                      'similar_cases': {k: result['similar_cases'].get(k) for k in ('status', 'n_rows', 'n_events')},
                      'warnings': result['warnings']}, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
