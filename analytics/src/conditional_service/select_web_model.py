"""Reproduce existing CatBoost settings; select on identical saved OOS keys.

No new algorithm, tuning, Gold mutation or Azure deployment.
"""
import hashlib
import json
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
from catboost import CatBoostRegressor
from threadpoolctl import threadpool_limits
from .core import STATE, ASSET, SHOCKS
from .rebuild_fixed_model import training
from .report_three_model_intervals import point, ci
from .finalize_model import BoundedFactor

OUT = Path('reports/web_model_selection_20261105')
FEATURES = STATE + ASSET + SHOCKS


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    root = Path('reports/service_scope_20261105')
    paths = [root/'corrected_features.parquet', root/'final_service_bundle.joblib',
             Path('reports/three_model_intervals_20261105/points.parquet')]
    hashes = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    data = pd.read_parquet(paths[0])
    saved = pd.read_parquet(paths[2])
    ref = saved[saved.model.eq('catboost')].copy()
    assets = sorted(ref.asset.unique())
    ridge = pd.read_parquet(root/'rebuilt_predictions.parquet')
    keys = ['date', 'asset']
    joined = ref.merge(ridge, on=keys, suffixes=('', '_ridge'), validate='one_to_one')
    assert len(joined) == len(ref) == 4150
    np.testing.assert_allclose(joined.actual, joined.actual_ridge)
    extras = []
    for name, field in [('ridge', 'center_ridge'), ('sector_ridge', 'sector_center'), ('zero', None)]:
        q = ref.copy(); q['model'] = name
        q['center'] = joined[field].to_numpy() if field else 0.
        extras.append(q)
    allp = pd.concat([saved, *extras], ignore_index=True)
    metrics = [dict(model=m, **point(z)) for m, z in allp.groupby('model')]
    pd.DataFrame(metrics).to_csv(OUT/'comparison.csv', index=False)
    for _, z in allp.groupby('model'):
        assert set(map(tuple, z[keys].to_numpy())) == set(map(tuple, ref[keys].to_numpy()))
    paired = joined.copy()
    uncertainty = {}
    for name, col in [('ridge', 'center_ridge'), ('zero', None), ('sector_ridge', 'sector_center')]:
        baseline = paired[col] if col else 0
        diff = abs(paired.actual-baseline)-abs(paired.actual-paired.center)
        uncertainty[name] = ci(diff.groupby(paired.date).mean().sort_index())
    models = {}; replay = []; audits = []
    for year in sorted(ref.year.unique()):
        tr = training(data, pd.Timestamp(int(year)-1, 1, 1))
        models[int(year)] = {}
        for a in assets:
            z = tr[tr.asset.eq(a)]
            q = ref[(ref.year == year) & ref.asset.eq(a)]
            te = q[keys].merge(data, on=keys, validate='one_to_one')
            m = CatBoostRegressor(iterations=150, depth=3, learning_rate=.04,
                loss_function='Quantile:alpha=0.5', random_seed=20261104,
                thread_count=2, verbose=False, allow_writing_files=False)
            m.fit(z[FEATURES].to_numpy(), z.target/z.scale)
            pred = m.predict(te[FEATURES].to_numpy())*te.scale.to_numpy()
            np.testing.assert_allclose(pred, q.center, atol=1e-8, rtol=1e-8)
            assert z.end_date.max() < te.date.min()
            models[int(year)][a] = m
            r = q.copy(); r['reproduced'] = pred; replay.append(r)
            audits.append(dict(year=int(year), asset=a, train_n=len(z),
                train_label_end=str(z.end_date.max()), evaluation_start=str(te.date.min())))
        print('Reproduced', year, '50 assets', flush=True)
    b = joblib.load(paths[1]); snapshots = []
    for a in assets:
        s = b['primary'] if a in b['primary']['support'] else b['expanded']
        snapshots.append(s['snapshot'][s['snapshot'].asset.eq(a)].copy())
    snapshot = pd.concat(snapshots, ignore_index=True)
    assert len(snapshot) == 50 and snapshot.date.nunique() == 1
    latest_year = max(models)
    history = training(data[data.asset.isin(assets)], snapshot.date.iloc[0])
    train_current = training(data[data.asset.isin(assets)], pd.Timestamp(latest_year-1, 1, 1))
    bundle = dict(version='catboost-corrected-oos-selected-20261105', features=FEATURES,
        models=models[latest_year], model_vintages=models, snapshot=snapshot,
        history=history, training_reference=train_current, names=b['names'],
        validation={a:point(z) for a,z in ref.groupby('asset')},
        model_year=int(latest_year), source_hashes=hashes)
    path = OUT/'selected_service_bundle.joblib'; joblib.dump(bundle, path)
    comparison = {m['model']: m for m in metrics}
    selection = dict(selected_model='catboost', display_name='CatBoost',
        artifact_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        model_file=path.name, feature_columns=FEATURES,
        comparison=comparison, uncertainty=uncertainty,
        rationale='Lowest MAE and highest nonzero-target direction among corrected-data shock models compared; exact four-input Shapley explains its own output. No claim of causal effect or baseline superiority.',
        zero_baseline_beaten=False, evaluation_reused=True, independent_blind=False,
        n=4150, dates=85, assets=50, reproduced_saved_predictions=True,
        data_policy='Corrected PIT features only. Legacy-publication-uncertified experiments excluded.',
        active_fit='2026 evaluation model, trained before 2025 with 20-day label embargo. No final refit that lacks OOS reproduction.',
        interpretation='Selected service calculation model; statistical scenario, not validated future-loss prediction',
        contribution_method='Exact Shapley over four shocks, averaging all 24 orders; zero-change reference',
        existing_ridge_preserved=True, azure_changed=False, gold_changed=False)
    (OUT/'selection.json').write_text(json.dumps(selection, ensure_ascii=False, indent=2), encoding='utf8')
    (OUT/'fit_audit.json').write_text(json.dumps(audits, indent=2), encoding='utf8')
    pd.concat(replay).to_parquet(OUT/'reproduced_predictions.parquet', index=False)
    for p, h in hashes.items(): assert hashlib.sha256(Path(p).read_bytes()).hexdigest() == h
    print('SELECTED', json.dumps(comparison['catboost']), flush=True)


def select_sector():
    """Include the actual shock-aware sector benchmark in service selection."""
    import shutil
    catpath=OUT/'catboost_reproduced_bundle.joblib'
    if not catpath.exists():
        shutil.copy2(OUT/'selected_service_bundle.joblib', catpath)
        shutil.copy2(OUT/'selection.json', OUT/'catboost_comparison.json')
    b=joblib.load(catpath)
    old=joblib.load('reports/service_scope_20261105/final_service_bundle.joblib')
    data=pd.read_parquet('reports/service_scope_20261105/corrected_features.parquet')
    cfg=json.loads(Path('reports/service_scope_20261105/locked_protocol.json').read_text())
    p=pd.read_parquet('reports/service_scope_20261105/rebuilt_predictions.parquet')
    models={};audit=[];refits=[]
    for year in sorted(p.year.unique()):
        models[int(year)]={}
        for group in ['primary','expanded']:
            tr=training(data[data.asset.isin(cfg['cohorts'][group]['assets'])],pd.Timestamp(int(year)-1,1,1))
            m=BoundedFactor(dict(alpha=300,dev=10,years=None,sector=True),old['sectors']).fit(tr)
            ref=p[(p.year==year)&p.group.eq(group)]
            te=ref[['date','asset']].merge(data,on=['date','asset'],validate='one_to_one')
            pred=m.predict(te)
            np.testing.assert_allclose(pred,ref.sector_center,atol=1e-9,rtol=1e-9)
            for a in ref.asset.unique():models[int(year)][a]=m
            v=ref.copy();v['reproduced_sector']=pred;refits.append(v)
            audit.append(dict(year=int(year),group=group,train_rows=len(tr),train_label_end=str(tr.end_date.max()),test_rows=len(te)))
    info=json.loads((OUT/'catboost_comparison.json').read_text(encoding='utf8'))
    b.update(version='sector-shock-ridge-selected-20261105',model_kind='sector_ridge',
        models=models[max(models)],model_vintages=models,sectors=old['sectors'],
        validation={a:point(z.assign(center=z.sector_center)) for a,z in p.groupby('asset')})
    b['routing']={a:str(z.group.iloc[0]) for a,z in p.groupby('asset')}
    b['training_reference']=training(data,pd.Timestamp(max(models)-1,1,1))
    path=OUT/'selected_service_bundle.joblib';joblib.dump(b,path)
    uncertainty={}
    for name,col in [('zero',None),('old_ridge','center')]:
        baseline=p[col] if col else 0
        gain=abs(p.actual-baseline)-abs(p.actual-p.sector_center)
        uncertainty[name]=ci(gain.groupby(p.date).mean().sort_index())
    info.update(selected_model='sector_ridge',display_name='충격 반영 업종 Ridge',
        artifact_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        rationale='Lowest MAE/RMSE and highest nonzero-target direction in the exact corrected-data comparison; explicit linear shock coefficients. Worse crash error than CatBoost/Huber. Sector estimates are not stock-specific sensitivities.',
        zero_baseline_beaten=True,zero_improvement_statistically_established=False,
        selection_uses_repeated_development_evaluation=True,uncertainty=uncertainty,
        contribution_method='Exact learned sector coefficient multiplied by shock; zero reference',
        stock_specific_coefficients=False,market_state_in_B=False,
        market_state_role='A searches historical evidence; B uses four shocks and sector only, without state reweighting',
        active_fit='Reproduced 2026 evaluation fit: trained through 2024 with 20-day embargo; frozen rather than unvalidated final refit',
        tradeoffs=['Sector proxy, not individual stock sensitivity','No state-conditioned B coefficient','Crash loss underestimation remains','Linear extrapolation is not validated by output continuity'])
    (OUT/'selection.json').write_text(json.dumps(info,ensure_ascii=False,indent=2),encoding='utf8')
    (OUT/'sector_fit_audit.json').write_text(json.dumps(audit,indent=2),encoding='utf8')
    pd.concat(refits).to_parquet(OUT/'reproduced_sector_predictions.parquet',index=False)
    rows=[]
    for period,z in [('all',p),('2025_2026',p[p.year>=2025])]:
        for name,col in [('sector_ridge','sector_center'),('old_ridge','center'),('zero',None)]:
            rows.append(dict(period=period,model=name,**point(z.assign(center=z[col] if col else 0))))
    pd.DataFrame(rows).to_csv(OUT/'sector_periods.csv',index=False)
    print('Selected shock-aware sector Ridge; all 4150 historical predictions reproduced')


if __name__ == '__main__':
    import sys
    with threadpool_limits(limits=2):
        if '--select-sector' in sys.argv:select_sector()
        else:main()
