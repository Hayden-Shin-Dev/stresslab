"""모델 D(Ridge+LightGBM+Conformal)와 모델 E(CatBoost 분위수+CQR) 비교. 인자 없이 VS Code ▶ 로 실행.

    python analytics/model_de/compare_models.py
    -> analytics/outputs/model_de/
         model_d_predictions.parquet, model_e_predictions.parquet   (pyarrow 없으면 .csv)
         model_comparison.csv      모델 x 기간 x 변형 지표 + 학습/추론 시간
         final_table.csv           보고서용 최종 비교표(주 변형만)
         coverage_analysis.csv     전체/시장충격 유형별/연도별/종목별 포함률, 비대칭, 보정 전후
         paired_differences.csv    D-E 쌍대 차이와 블록 부트스트랩 구간
         scenario_comparison.csv   가상 시장충격 입력 비교
         run_info.json             설정, 백엔드, 시드, 분리 요약, crossing, 시간
이 스크립트가 D와 E를 모두 학습합니다(두 모델 스크립트는 같은 run()을 단독 실행하는 용도).
기존 Ridge / Ridge+LightGBM 파일과 결과는 건드리지 않습니다(새 폴더 outputs/model_de/ 에만 씁니다).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402
import model_d_ridge_lightgbm_conformal as D  # noqa: E402
import model_e_catboost_quantile_conformal as E  # noqa: E402

PRIMARY = {'D': 'sym', 'E': 'cqr'}
MODEL_NAME = {'D': 'Model D', 'E': 'Model E'}
VARIANTS = {'D': D.VARIANTS, 'E': E.VARIANTS}
N_BOOT = 500
BOOT_SEED = C.SEED

SCENARIOS = {                                   # 기간 h 동안의 누적 변화
    'no_shock': dict(shock_usdkrw_pct=0.0, shock_us10y_bp=0.0, shock_wti_pct=0.0, shock_vix_pt=0.0),
    'spec_rate+25bp_fx+1.5%': dict(shock_usdkrw_pct=1.5, shock_us10y_bp=25.0, shock_wti_pct=0.0, shock_vix_pt=0.0),
    'rate+50bp': dict(shock_usdkrw_pct=0.0, shock_us10y_bp=50.0, shock_wti_pct=0.0, shock_vix_pt=0.0),
    'rate-50bp': dict(shock_usdkrw_pct=0.0, shock_us10y_bp=-50.0, shock_wti_pct=0.0, shock_vix_pt=0.0),
    'fx+5%': dict(shock_usdkrw_pct=5.0, shock_us10y_bp=0.0, shock_wti_pct=0.0, shock_vix_pt=0.0),
    'fx-3%': dict(shock_usdkrw_pct=-3.0, shock_us10y_bp=0.0, shock_wti_pct=0.0, shock_vix_pt=0.0),
    'oil+20%': dict(shock_usdkrw_pct=0.0, shock_us10y_bp=0.0, shock_wti_pct=20.0, shock_vix_pt=0.0),
    'vix+15pt': dict(shock_usdkrw_pct=0.0, shock_us10y_bp=0.0, shock_wti_pct=0.0, shock_vix_pt=15.0),
    'stress_combo': dict(shock_usdkrw_pct=5.0, shock_us10y_bp=50.0, shock_wti_pct=-20.0, shock_vix_pt=20.0),
    'extreme_combo': dict(shock_usdkrw_pct=15.0, shock_us10y_bp=150.0, shock_wti_pct=-50.0, shock_vix_pt=60.0),
}
SCENARIO_NOTE = ('포함률(Coverage)은 과거 보정/시험 자료에서 측정한 통계적 포함률이며, 입력한 단일 시나리오가 그 확률로 '
                 '실현된다는 뜻이 아닙니다. 구간 폭은 입력 충격의 크기를 반영하지 않을 수 있습니다(종목 변동성 기준 폭).')


# ---------------------------------------------------------------- 지표 집계
def block_bootstrap(values_by_block: pd.DataFrame, n_boot=N_BOOT, seed=BOOT_SEED):
    """블록 합계표(행=블록)에서 블록을 복원 추출해 열별 평균의 2.5/97.5% 구간을 돌려줍니다."""
    rng = np.random.default_rng(seed)
    n = len(values_by_block)
    a = values_by_block.to_numpy(float)
    idx = rng.integers(0, n, size=(n_boot, n))
    tot = a[idx].sum(axis=1)                                   # n_boot x ncol (합)
    cnt = tot[:, -1:]                                          # 마지막 열 = 행 수
    means = tot[:, :-1] / cnt
    return pd.DataFrame(np.percentile(means, [2.5, 97.5], axis=0).T, index=values_by_block.columns[:-1], columns=['lo', 'hi'])


def prediction_frame(r: dict, key: str) -> pd.DataFrame:
    return r['pred']


def model_rows(key, h, pred, info, train_ref) -> tuple[list, list]:
    """(model_comparison 행들, coverage_analysis 행들)."""
    comp, cov = [], []
    y, c = pred['y_actual'].to_numpy(float), pred['center'].to_numpy(float)
    pm = C.point_metrics(y, c)
    masks = C.regime_masks(train_ref, pred)
    for v in VARIANTS[key]:
        row = {'model': MODEL_NAME[key], 'model_key': key, 'variant': v, 'is_primary': v == PRIMARY[key], 'horizon': h,
               'rows': len(pred), 'independent_blocks': int(pred['overlap_block'].nunique()), **pm,
               'train_seconds': info['train_seconds'], 'inference_ms_per_row': info['inference_ms_per_row'],
               'calibration_seconds': info['calibration_seconds'], 'gbm_backend': info.get('backend_gbm', info.get('backend'))}
        for L in C.LEVELS:
            tag = C.lv(L)
            lo, hi = pred[f'lo_{v}_{tag}'].to_numpy(float), pred[f'hi_{v}_{tag}'].to_numpy(float)
            m = C.interval_metrics(y, lo, hi, L)
            for k_, v_ in m.items():
                row[f'{k_}_{tag}'] = v_
            # 그룹별 포함률
            groups = {('overall', n): mk for n, mk in masks.items()}
            for yr, g in pred.groupby(pred['trading_date'].dt.year):
                groups[('year', str(yr))] = pd.Series(pred.index.isin(g.index), index=pred.index)
            for a, g in pred.groupby('asset_id'):
                groups[('asset', str(a))] = pd.Series(pred.index.isin(g.index), index=pred.index)
            for (gt, gn), mk in groups.items():
                mk = mk.to_numpy(bool)
                if mk.sum() == 0:
                    continue
                gm = C.interval_metrics(y[mk], lo[mk], hi[mk], L)
                cov.append({'model': MODEL_NAME[key], 'variant': v, 'is_primary': v == PRIMARY[key], 'horizon': h, 'target_coverage': L,
                            'group_type': 'regime' if gt == 'overall' else gt, 'group': gn, 'n': int(mk.sum()),
                            'independent_blocks': int(pred.loc[mk, 'overlap_block'].nunique()), 'coverage': gm['coverage'],
                            'coverage_gap': gm['coverage_gap'], 'miss_below': gm['miss_below'], 'miss_above': gm['miss_above'],
                            'mean_width': gm['mean_width'], 'median_width': gm['median_width'], 'interval_score': gm['interval_score']})
        comp.append(row)
    return comp, cov


def add_coverage_ci(cov: pd.DataFrame, preds: dict) -> pd.DataFrame:
    """전체 구간 포함률의 블록 부트스트랩 95% 구간(겹치는 5/20일 정답의 의존성 반영)."""
    lo, hi = [], []
    for _, r in cov.iterrows():
        if not (r['group_type'] == 'regime' and r['group'] == 'all'):
            lo.append(np.nan); hi.append(np.nan); continue
        key = 'D' if r['model'] == 'Model D' else 'E'
        p = preds[(key, r['horizon'])]
        tag = C.lv(r['target_coverage'])
        ins = ((p['y_actual'] >= p[f'lo_{r["variant"]}_{tag}']) & (p['y_actual'] <= p[f'hi_{r["variant"]}_{tag}'])).astype(float)
        t = pd.DataFrame({'ins': ins.to_numpy(), 'n': 1.0, 'b': p['overlap_block'].to_numpy()}).groupby('b').sum()
        ci = block_bootstrap(t[['ins', 'n']])
        lo.append(ci.loc['ins', 'lo']); hi.append(ci.loc['ins', 'hi'])
    cov = cov.copy()
    cov['coverage_ci_lo'], cov['coverage_ci_hi'] = lo, hi
    return cov


def asymmetry_rows(key, h, pred) -> list:
    out = []
    for v in VARIANTS[key]:
        for L in C.LEVELS:
            tag = C.lv(L)
            lo, hi, c = (pred[f'lo_{v}_{tag}'].to_numpy(float), pred[f'hi_{v}_{tag}'].to_numpy(float), pred['center'].to_numpy(float))
            y = pred['y_actual'].to_numpy(float)
            up, dn = hi - c, c - lo
            out.append({'model': MODEL_NAME[key], 'variant': v, 'is_primary': v == PRIMARY[key], 'horizon': h, 'target_coverage': L,
                        'group_type': 'asymmetry', 'group': 'all', 'n': len(pred), 'coverage': float(((y >= lo) & (y <= hi)).mean()),
                        'miss_below': float((y < lo).mean()), 'miss_above': float((y > hi).mean()),
                        'mean_width': float((hi - lo).mean()), 'median_width': float(np.median(hi - lo)),
                        'mean_up_half': float(up.mean()), 'mean_down_half': float(dn.mean()),
                        'up_over_down_ratio': float(up.mean() / dn.mean()) if dn.mean() else np.nan,
                        'tail_target_each_side': (1 - L) / 2})
    return out


def before_after_rows(h, e_pred) -> list:
    out = []
    for L in C.LEVELS:
        tag = C.lv(L)
        y = e_pred['y_actual'].to_numpy(float)
        for v in ('raw', 'cqr', 'cqr_roll'):
            lo, hi = e_pred[f'lo_{v}_{tag}'].to_numpy(float), e_pred[f'hi_{v}_{tag}'].to_numpy(float)
            m = C.interval_metrics(y, lo, hi, L)
            out.append({'model': 'Model E', 'variant': v, 'is_primary': v == 'cqr', 'horizon': h, 'target_coverage': L,
                        'group_type': 'conformal_before_after', 'group': 'before' if v == 'raw' else 'after', 'n': len(y),
                        'coverage': m['coverage'], 'coverage_gap': m['coverage_gap'], 'mean_width': m['mean_width'],
                        'median_width': m['median_width'], 'interval_score': m['interval_score'],
                        'miss_below': m['miss_below'], 'miss_above': m['miss_above']})
    return out


def paired_rows(h, pd_, pe) -> list:
    """같은 (날짜, 종목) 행에서 D-E 차이(주 변형끼리). 양수 = D의 오차/폭/점수가 더 큼(나쁨)."""
    m = pd_.add_suffix('_d').rename(columns={'trading_date_d': 'trading_date', 'asset_id_d': 'asset_id'}).merge(
        pe.add_suffix('_e').rename(columns={'trading_date_e': 'trading_date', 'asset_id_e': 'asset_id'}), on=['trading_date', 'asset_id'], validate='1:1')
    y = m['y_actual_d'].to_numpy(float)
    err = (y - m['center_d']).abs().to_numpy() - (y - m['center_e']).abs().to_numpy()
    label = {'abs_err': 'MAE 차이(D-E)', 'width': '평균 폭 차이(D-E)', 'iscore': 'Interval Score 차이(D-E)'}
    out = []
    for L in C.LEVELS:
        tag, a = C.lv(L), 1 - L

        def iscore(lo, hi):
            lo, hi = m[lo].to_numpy(float), m[hi].to_numpy(float)
            return (hi - lo) + (2 / a) * np.maximum(lo - y, 0) + (2 / a) * np.maximum(y - hi, 0)
        t = pd.DataFrame({'b': m['overlap_block_d'].to_numpy(), 'abs_err': err, 'n': 1.0})
        t['width'] = (m[f'hi_sym_{tag}_d'] - m[f'lo_sym_{tag}_d']).to_numpy() - (m[f'hi_cqr_{tag}_e'] - m[f'lo_cqr_{tag}_e']).to_numpy()
        t['iscore'] = iscore(f'lo_sym_{tag}_d', f'hi_sym_{tag}_d') - iscore(f'lo_cqr_{tag}_e', f'hi_cqr_{tag}_e')
        cols = ['abs_err', 'width', 'iscore']
        g = t.groupby('b')[cols + ['n']].sum()
        ci = block_bootstrap(g)
        for c in cols:
            out.append({'horizon': h, 'target_coverage': L, 'metric': label[c], 'mean_diff': float(t[c].mean()),
                        'ci_lo': float(ci.loc[c, 'lo']), 'ci_hi': float(ci.loc[c, 'hi']), 'blocks': int(len(g)),
                        'significant_at_95': bool(ci.loc[c, 'lo'] > 0 or ci.loc[c, 'hi'] < 0),
                        'note': '양수=D가 더 큼(나쁨). 구간이 0을 포함하면 차이를 단정하지 않음'})
    return out


# ---------------------------------------------------------------- 가상 시장충격 시나리오
def scenario_frame(ctx: C.Context) -> pd.DataFrame:
    d = ctx.all
    need = [c for c in C.INPUT_ORDER if not c.startswith('shock_')] + ['scale_kospi', 'asset_scale']
    ok = d.dropna(subset=need)
    ok = ok[ok['asset_id'].isin(ctx.assets)]
    day = ok.groupby('trading_date').size()
    asof = day[day >= max(1, int(0.8 * len(ctx.assets)))].index.max()
    return ok[ok['trading_date'] == asof].reset_index(drop=True)


def scenario_rows(results: dict, ctxs: dict, horizons=C.HORIZONS) -> pd.DataFrame:
    rows = []
    for h in horizons:
        ctx = ctxs[h]
        base = scenario_frame(ctx)
        asof = str(base['trading_date'].iloc[0])[:10]
        q = {c: ctx.train[c].quantile([0.01, 0.99]).to_numpy() for c in C.SHOCK_ORDER}
        for sname, shocks in SCENARIOS.items():
            fr = base.copy()
            for c, v in shocks.items():
                fr[c] = v
            rc = C.range_check(ctx.train, shocks)
            outside = [c for c, d in rc.items() if d['outside']]
            rare = [c for c in C.SHOCK_ORDER if not rc[c]['outside'] and (shocks[c] < q[c][0] or shocks[c] > q[c][1])]
            if outside:
                status, caution = 'OUT_OF_RANGE', '학습 자료에 없던 크기의 충격(외삽)입니다. 결과는 신뢰하기 어렵습니다: ' + ', '.join(outside)
            elif rare:
                status, caution = 'RARE', '학습 자료에서 상/하위 1% 밖의 드문 충격입니다. 해당 구간 학습 표본이 적어 불확실합니다: ' + ', '.join(rare)
            else:
                status, caution = 'IN_RANGE', '학습 범위 안의 충격입니다.'
            reg = C.regime_masks(ctx.train, fr)
            regime = next((n for n in ['extreme_any_shock', 'rate_and_fx_both_large', 'rate_up', 'rate_down', 'fx_up', 'fx_down', 'normal'] if bool(reg[n].iloc[0])), 'other')
            sc = fr['asset_scale'].to_numpy(float)
            for key in ('D', 'E'):
                r = results[(key, h)]
                if key == 'D':
                    cen = r['model'].predict(fr)
                    for L in C.LEVELS:
                        qv = r['info']['conformal_quantile_levels'][C.lv(L)]
                        rows += _scn(fr, key, h, sname, shocks, asof, L, cen, cen - qv * sc, cen + qv * sc, status, caution, regime, outside)
                else:
                    qt = np.sort(r['model'].predict_norm(fr), axis=1)
                    cen = qt[:, E.TAUS.index(0.50)] * sc
                    for L in C.LEVELS:
                        a_, b_ = C.LEVEL_Q[L]
                        k = r['info']['cqr_adjustment_norm_units'][C.lv(L)]
                        lo = (qt[:, E.TAUS.index(a_)] - k) * sc
                        hi = (qt[:, E.TAUS.index(b_)] + k) * sc
                        rows += _scn(fr, key, h, sname, shocks, asof, L, cen, lo, hi, status, caution, regime, outside)
    df = pd.DataFrame(rows)
    allrows = (df.groupby(['scenario', 'model', 'horizon', 'target_coverage'], sort=False)
               .agg(center_pct=('center_pct', 'mean'), lower_pct=('lower_pct', 'mean'), upper_pct=('upper_pct', 'mean'),
                    width_pct=('width_pct', 'mean'), center_simple_pct=('center_simple_pct', 'mean'),
                    lower_simple_pct=('lower_simple_pct', 'mean'), upper_simple_pct=('upper_simple_pct', 'mean'))
               .reset_index())
    meta = df.drop_duplicates(['scenario', 'model', 'horizon', 'target_coverage'])[
        ['scenario', 'model', 'horizon', 'target_coverage', 'as_of', 'shock_usdkrw_pct', 'shock_us10y_bp', 'shock_wti_pct', 'shock_vix_pt',
         'range_status', 'out_of_range_shocks', 'shock_regime', 'reliability_note', 'coverage_meaning']]
    allrows = allrows.merge(meta, on=['scenario', 'model', 'horizon', 'target_coverage'])
    allrows.insert(1, 'asset_id', 'ALL(종목 평균)')
    return pd.concat([allrows, df], ignore_index=True)[list(df.columns)]


def _scn(fr, key, h, sname, shocks, asof, L, cen, lo, hi, status, caution, regime, outside):
    simple = lambda x: (np.exp(np.asarray(x) / 100) - 1) * 100
    out = []
    for i in range(len(fr)):
        out.append({'scenario': sname, 'asset_id': fr['asset_id'].iloc[i], 'model': MODEL_NAME[key], 'horizon': h, 'target_coverage': L,
                    'as_of': asof, **shocks, 'center_pct': cen[i], 'lower_pct': lo[i], 'upper_pct': hi[i], 'width_pct': hi[i] - lo[i],
                    'center_simple_pct': simple(cen[i]), 'lower_simple_pct': simple(lo[i]), 'upper_simple_pct': simple(hi[i]),
                    'range_status': status, 'out_of_range_shocks': ','.join(outside), 'shock_regime': regime,
                    'reliability_note': caution, 'coverage_meaning': '과거 자료의 통계적 포함률이며 이 시나리오의 실현 확률이 아님'})
    return out


# ---------------------------------------------------------------- 실행
def run_all(gold=None, horizons=C.HORIZONS, n_boot=None):
    if gold is None:
        from load_gold import DEFAULT_SOURCE, load_gold
        gold = load_gold(DEFAULT_SOURCE)
    clean, fs, market = C.load_inputs(gold)
    ctxs, results, preds = {}, {}, {}
    for h in horizons:
        ctx = C.Context(clean, fs, market, h)
        ctxs[h] = ctx
        for key, mod in (('D', D), ('E', E)):
            r = mod.run(ctx)
            results[(key, h)] = r
            preds[(key, h)] = r['pred']
            print(f'{key} h={h}: 학습 {r["info"]["train_seconds"]:.1f}초, 추론 {r["info"]["inference_ms_per_row"]:.4f} ms/행')
    return ctxs, results, preds


def build_outputs(ctxs, results, preds, horizons=C.HORIZONS):
    comp, cov = [], []
    for h in horizons:
        for key in ('D', 'E'):
            c_, v_ = model_rows(key, h, preds[(key, h)], results[(key, h)]['info'], ctxs[h].train)
            comp += c_
            cov += v_
            cov += asymmetry_rows(key, h, preds[(key, h)])
        cov += before_after_rows(h, preds[('E', h)])
    comparison = pd.DataFrame(comp)
    coverage = add_coverage_ci(pd.DataFrame(cov), preds)
    paired = pd.DataFrame([r for h in horizons for r in paired_rows(h, preds[('D', h)], preds[('E', h)])])
    scenario = scenario_rows(results, ctxs, horizons)
    prim = comparison[comparison['is_primary']].copy()
    final = prim[['model', 'horizon', 'mae', 'rmse', 'r2', 'directional_accuracy', 'coverage_80', 'coverage_90', 'coverage_95',
                  'mean_width_80', 'mean_width_90', 'mean_width_95', 'train_seconds', 'inference_ms_per_row']].rename(
        columns={'mean_width_90': 'mean_width_90(평균 구간 너비)'}).sort_values(['horizon', 'model'])
    return comparison, final, coverage, paired, scenario


def save(ctxs, results, preds, comparison, final, coverage, paired, scenario, out=C.OUT):
    out.mkdir(parents=True, exist_ok=True)
    files = {}
    for key in ('D', 'E'):
        df = pd.concat([preds[(key, h)] for h in sorted({h for k, h in preds if k == key})], ignore_index=True)
        files[f'model_{key.lower()}_predictions'] = C.write_table(df, out / f'model_{key.lower()}_predictions.parquet')
    for name, df in (('model_comparison', comparison), ('final_table', final), ('coverage_analysis', coverage),
                     ('paired_differences', paired), ('scenario_comparison', scenario)):
        p = out / f'{name}.csv'
        df.to_csv(p, index=False, encoding='utf-8-sig')
        files[name] = str(p)
    info = {'version': C.VERSION, 'seed': C.SEED, 'regime_definition': C.REGIME_NOTE, 'scenario_note': SCENARIO_NOTE,
            'primary_variant': PRIMARY, 'bootstrap': {'n': N_BOOT, 'unit': 'overlap_block(달력 위치 // 기간)'},
            'splits': {h: ctxs[h].summary() for h in ctxs},
            'models': {f'{k}_h{h}': r['info'] for (k, h), r in results.items()},
            'scenarios': SCENARIOS,
            'test_split_note': '시험 구간(2023~)은 이전 실험에서 이미 확인한 적이 있어 완전한 blind가 아님'}
    (out / 'run_info.json').write_text(json.dumps(info, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
    files['run_info'] = str(out / 'run_info.json')
    return files


def main():
    ctxs, results, preds = run_all()
    tables = build_outputs(ctxs, results, preds)
    files = save(ctxs, results, preds, *tables)
    comparison, final = tables[0], tables[1]
    print('\n[최종 비교표: 주 변형(D=sym, E=cqr), 단위: 로그수익률 %]')
    print(final.round(4).to_string(index=False))
    print(json.dumps(files, ensure_ascii=False, indent=2))
    backend = {r['info'].get('backend_gbm', r['info'].get('backend')) for r in results.values()}
    if backend & {'sklearn_hist_gradient_boosting', 'sklearn_hist_gradient_boosting_quantile'}:
        print('\n주의: LightGBM/CatBoost가 없어 scikit-learn 대체 모델로 계산했습니다. 최종 수치가 아닙니다.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
