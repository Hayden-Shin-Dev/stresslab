"""모델 E 하이퍼파라미터 탐색과 효과 확인. 인자 없이 VS Code ▶ 로 실행합니다.

    python analytics/model_de/tune_model_e.py
    -> analytics/outputs/model_de/tuning/{tuning_grid.csv, best_params.json, tuning_effect.csv, tuning_effect_paired.csv}

절차(예측 기간 1/5/20일 각각)
  1) 탐색은 학습 구간(2020년 전) 안의 롤링 검증만 사용: 연도 Y 검증은 정답이 Y년 전에 끝난 행으로 학습, Y년 행으로 평가.
     보정 구간(2020~2022)과 시험 구간(2023~)은 설정 선택에 쓰지 않습니다.
  2) 격자를 단계로 나눠 좁혀 갑니다: 1단계 depth x iterations(lr, l2 기본) -> 2단계 learning_rate x l2(1단계 최적 고정).
  3) 점수는 7개 분위수 pinball 손실 평균(정규화 단위). 1표준오차 규칙: 최고 점수와 1 표준오차 이내인 설정 중 가장 단순한 것을 고릅니다.
  4) 마지막에 기본 설정과 선택 설정을 같은 보정/시험 절차로 각각 한 번 평가해 비교합니다(시험 구간은 이미 본 적이 있어 blind 아님).
D와 공정하게 비교하려면 D의 GBM도 같은 방식으로 튜닝해야 합니다(이 스크립트는 E만 다룹니다).
"""
from __future__ import annotations

import json
import sys
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402
import compare_models as CM  # noqa: E402
import model_e_catboost_quantile_conformal as E  # noqa: E402

VAL_YEARS = (2015, 2017, 2019)                      # 학습 구간(<2020) 안 검증 연도
STAGE1 = {'depth': (3, 4, 6), 'iterations': (150, 300, 600)}
STAGE2 = {'learning_rate': (0.03, 0.05, 0.10), 'l2_leaf_reg': (3.0, 10.0, 30.0)}
HORIZONS = C.HORIZONS


def pinball_mean(z, q):
    """z: 정규화 y, q: 열=TAUS 분위수 예측(정렬 후). 7개 분위수 평균 pinball."""
    return float(np.mean([C.pinball(z, q[:, i], t) for i, t in enumerate(E.TAUS)]))


def cv_score(ctx: C.Context, params: dict, seed=C.SEED) -> dict:
    tr = ctx.train
    per = []
    for y in VAL_YEARS:
        start, end = pd.Timestamp(f'{y}-01-01'), pd.Timestamp(f'{y + 1}-01-01')
        fit = tr[tr['target_date'] < start]
        val = tr[(tr['trading_date'] >= start) & (tr['target_date'] < end)]
        if len(fit) < 5000 or len(val) < 100:
            continue
        m = E.QuantileSet(ctx.ycol, seed, params).fit(fit)
        q = np.sort(m.predict_norm(val), axis=1)
        z = val[ctx.ycol].to_numpy(float) / C._floor(val['asset_scale'].to_numpy())
        per.append(pinball_mean(z, q))
    per = np.array(per)
    return {'cv_pinball': float(per.mean()), 'cv_se': float(per.std(ddof=1) / np.sqrt(len(per))) if len(per) > 1 else 0.0, 'folds': len(per)}


def simplicity(p):                                   # 작을수록 단순
    return (p['depth'], p['iterations'], -p['l2_leaf_reg'], p['learning_rate'])


def pick(rows: list) -> dict:
    best = min(rows, key=lambda r: r['cv_pinball'])
    ok = [r for r in rows if r['cv_pinball'] <= best['cv_pinball'] + best['cv_se']]
    return min(ok, key=lambda r: simplicity(r['params']))


def search(ctx: C.Context) -> tuple[dict, pd.DataFrame]:
    ck = C.OUT / 'tuning' / f'checkpoint_h{ctx.h}.json'
    if ck.exists():                                   # 이미 끝난 기간은 건너뜁니다(중단 후 이어서 실행)
        d = json.loads(ck.read_text(encoding='utf-8'))
        if d.get('backend') == E.backend() and d.get('val_years') == list(VAL_YEARS) and d.get('stage1') == {k: list(v) for k, v in STAGE1.items()}:
            print(f'  h={ctx.h}: 저장된 탐색 결과를 불러옵니다({ck.name})', flush=True)
            return d['params'], pd.DataFrame(d['grid'])
    rows, base = [], dict(E.CATBOOST_PARAMS)
    for stage, grid in ((1, STAGE1), (2, STAGE2)):
        stage_rows = []
        keys = list(grid)
        for vals in product(*grid.values()):
            p = {**base, **dict(zip(keys, vals))}
            r = {'horizon': ctx.h, 'stage': stage, **p, **cv_score(ctx, p)}
            r['params'] = p
            stage_rows.append(r)
            rows.append(r)
            print(f'  h={ctx.h} 단계{stage} {dict(zip(keys, vals))}: pinball {r["cv_pinball"]:.5f} ± {r["cv_se"]:.5f}', flush=True)
        base = pick(stage_rows)['params']
    final = pick(rows)
    grid = pd.DataFrame([{k: v for k, v in r.items() if k != 'params'} for r in rows])
    ck.parent.mkdir(parents=True, exist_ok=True)
    ck.write_text(json.dumps({'backend': E.backend(), 'val_years': list(VAL_YEARS), 'stage1': {k: list(v) for k, v in STAGE1.items()},
                              'params': final['params'], 'grid': grid.to_dict('records')}, ensure_ascii=False, indent=1), encoding='utf-8')
    return final['params'], grid


def evaluate(ctx: C.Context, params: dict | None, label: str) -> tuple[dict, pd.DataFrame]:
    r = E.run(ctx, params=params)
    p = r['pred']
    y, c = p['y_actual'].to_numpy(float), p['center'].to_numpy(float)
    row = {'horizon': ctx.h, 'setting': label, **C.point_metrics(y, c), 'train_seconds': r['info']['train_seconds'],
           'crossing_rate_test': r['info']['quantile_crossing']['test']['rows_with_any_crossing']}
    for L in C.LEVELS:
        tag = C.lv(L)
        for v in ('raw', 'cqr'):
            m = C.interval_metrics(y, p[f'lo_{v}_{tag}'].to_numpy(float), p[f'hi_{v}_{tag}'].to_numpy(float), L)
            for k in ('coverage', 'mean_width', 'interval_score', 'pinball'):
                row[f'{v}_{k}_{tag}'] = m[k]
    return row, p


def paired(ctx, p_def, p_tun) -> list:
    out = []
    y = p_def['y_actual'].to_numpy(float)
    err = (y - p_def['center']).abs().to_numpy() - (y - p_tun['center']).abs().to_numpy()
    for L in C.LEVELS:
        tag, a = C.lv(L), 1 - L

        def isc(p):
            lo, hi = p[f'lo_cqr_{tag}'].to_numpy(float), p[f'hi_cqr_{tag}'].to_numpy(float)
            return (hi - lo) + (2 / a) * np.maximum(lo - y, 0) + (2 / a) * np.maximum(y - hi, 0)
        t = pd.DataFrame({'b': p_def['overlap_block'].to_numpy(), 'abs_err': err, 'iscore': isc(p_def) - isc(p_tun), 'n': 1.0})
        g = t.groupby('b')[['abs_err', 'iscore', 'n']].sum()
        ci = CM.block_bootstrap(g)
        for c, nm in (('abs_err', 'MAE 개선(기본-튜닝)'), ('iscore', 'Interval Score 개선(기본-튜닝)')):
            out.append({'horizon': ctx.h, 'target_coverage': L, 'metric': nm, 'mean_gain': float(t[c].mean()), 'ci_lo': float(ci.loc[c, 'lo']),
                        'ci_hi': float(ci.loc[c, 'hi']), 'significant_at_95': bool(ci.loc[c, 'lo'] > 0 or ci.loc[c, 'hi'] < 0),
                        'note': '양수=튜닝이 더 좋음. 구간이 0을 포함하면 개선을 단정하지 않음'})
    return out


def run_all(gold=None, horizons=HORIZONS):
    if gold is None:
        from load_gold import DEFAULT_SOURCE, load_gold
        gold = load_gold(DEFAULT_SOURCE)
    clean, fs, market = C.load_inputs(gold)
    grids, best, effect, pair = [], {}, [], []
    for h in horizons:
        ctx = C.Context(clean, fs, market, h)
        params, grid = search(ctx)
        grids.append(grid)
        best[str(h)] = params
        r_def, p_def = evaluate(ctx, None, 'default')
        r_tun, p_tun = evaluate(ctx, params, 'tuned')
        effect += [r_def, r_tun]
        pair += paired(ctx, p_def, p_tun)
        print(f'h={h} 선택: {params}', flush=True)
    return pd.concat(grids, ignore_index=True), best, pd.DataFrame(effect), pd.DataFrame(pair)


def save(grid, best, effect, pair, out=None):
    out = Path(out or C.OUT / 'tuning')
    out.mkdir(parents=True, exist_ok=True)
    grid.to_csv(out / 'tuning_grid.csv', index=False, encoding='utf-8-sig')
    effect.to_csv(out / 'tuning_effect.csv', index=False, encoding='utf-8-sig')
    pair.to_csv(out / 'tuning_effect_paired.csv', index=False, encoding='utf-8-sig')
    (out / 'best_params.json').write_text(json.dumps({'backend': E.backend(), 'val_years': VAL_YEARS, 'stage1': STAGE1, 'stage2': STAGE2,
                                                      'selection': '1표준오차 규칙(가장 단순한 설정)', 'best': best}, ensure_ascii=False, indent=2), encoding='utf-8')
    return str(out)


def main():
    grid, best, effect, pair = run_all()
    path = save(grid, best, effect, pair)
    show = ['horizon', 'setting', 'mae', 'rmse', 'cqr_coverage_90', 'cqr_mean_width_90', 'cqr_interval_score_90', 'raw_coverage_90', 'crossing_rate_test', 'train_seconds']
    print('\n[기본 vs 튜닝 (시험 구간, 90%)]')
    print(effect[show].round(4).to_string(index=False))
    print('\n[쌍대 차이 (양수=튜닝이 좋음), 90%]')
    print(pair[pair.target_coverage == 0.9].round(4).to_string(index=False))
    print('저장:', path)
    if E.backend() != 'catboost':
        print('\n주의: CatBoost가 없어 scikit-learn 대체 모델로 계산했습니다. 최종 수치가 아닙니다.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
