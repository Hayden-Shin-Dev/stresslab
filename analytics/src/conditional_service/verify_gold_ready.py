"""Real-data integration checks, including rejection of unfinished Fabric input."""
import argparse
import itertools
import tempfile
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from fastapi.testclient import TestClient

from .core import SHOCKS, STATE, ASSET, features
from .gold_ready import read_gold, save, sha
from .gold_ready_api import create_app, Runtime


def verify(root, out):
    root, out = Path(root), Path(out)
    hashes = {str(p):sha(p) for p in [out/'model.joblib',out/'gold.parquet',out/'provenance.parquet',
        root/'reports/web_model_selection_20261105/selected_service_bundle.joblib',
        root/'reports/fabric_gold_review_20261109/gold_stock_market_daily_v11.parquet']}
    runtime = Runtime(out/'model.joblib',out/'gold.parquet',out/'provenance.parquet',out/'certificate.json')
    app = create_app(out)
    checks = []
    def passed(name, **details): checks.append(dict(check=name,passed=True,**details))
    with TestClient(app) as client:
        supported = client.get('/support').json()['assets']
        assert len(supported)==20
        positions = [dict(asset_id=a['asset_id'],value_krw=1000000) for a in supported]
        default_shocks = dict(fx_pct=5,us_rate_bp=100,wti_pct=10,vix_points=5)
        candidate_dates = None
        calls = 0
        for n in range(1,5):
            for chosen in itertools.combinations(SHOCKS,n):
                response=client.post('/analyze',json=dict(positions=positions,shocks={s:default_shocks[s] for s in chosen}))
                assert response.status_code==200,response.text
                body=response.json();calls+=1
                assert len(body['assets'])==20
                dates=body['market_candidates']
                if candidate_dates is None:candidate_dates=dates
                assert dates==candidate_dates,'User shocks changed stage A'
                for item in body['assets']:
                    np.testing.assert_allclose(item['baseline_model_return_pct']+sum(item['shock_contributions_pp'].values()),item['conditional_return_pct'],atol=1e-8)
                    np.testing.assert_allclose(item['hypothetical_pnl_krw'],item['conditional_return_pct']*item['value_krw']/100)
                    assert all(pd.Timestamp(e['end_date'])<pd.Timestamp(body['market_basis_date']) for e in item['historical_examples'])
                    assert all(item['shock_contributions_pp'][s]==0 for s in SHOCKS if s not in chosen)
                np.testing.assert_allclose(body['portfolio_hypothetical_pnl_krw'],sum(x['hypothetical_pnl_krw'] for x in body['assets']))
        passed('20 stocks x all 15 nonempty shock subsets',requests=calls,asset_scenarios=calls*20)
        passed('Exact coefficient contributions, amounts and unchanged shock-free A')
        sample_request=dict(positions=[dict(asset_id='005930',value_krw=50000000),dict(asset_id='005380',value_krw=50000000)],shocks=dict(fx_pct=5,us_rate_bp=100))
        sample=client.post('/analyze',json=sample_request)
        assert sample.status_code==200
        save(out/'request.json',sample_request);save(out/'response.json',sample.json())
        zero=client.post('/analyze',json=dict(positions=positions)).json()
        assert all(abs(a['change_from_zero_shocks_pp'])<1e-9 for a in zero['assets'])
        passed('Omitted shocks are zero CHANGES, not zero absolute levels')
        for bad in [dict(positions=[dict(asset_id='999999',value_krw=1)]),
                    dict(positions=[positions[0],positions[0]]),
                    dict(positions=[dict(asset_id='005930',value_krw=-1)]),
                    dict(positions=positions,shocks={'wti_pct':-100}),
                    dict(positions=positions,shocks={'vix_points':-1000}),
                    dict(positions=positions,shocks={'unknown_shock':1}),
                    dict(positions=positions,shocks={'fx_pct':'NaN'})]:
            assert client.post('/analyze',json=bad).status_code==422
        passed('Unsupported assets, duplicates, invalid units/values and nonfinite shocks rejected')
        extreme=client.post('/analyze',json=dict(positions=positions,shocks={'fx_pct':10000})).json()
        assert 'fx_pct' in extreme['scenario_support']['outside_marginal']
        assert all(x['exploratory'] for x in extreme['assets'])
        passed('Extreme scenarios explicitly marked as extrapolation/exploration')
        assert zero['is_stale'] and zero['market_basis_date']=='2026-10-30'
        assert not zero['latest_market_state_verified']
        passed('Old certified snapshot not advertised as current market')
    for path in [root/'reports/fabric_gold_review_20261109/gold_stock_market_daily_v11.parquet',out/'nonexistent.parquet']:
        try:read_gold(path)
        except (ValueError,FileNotFoundError) as exc:passed('Invalid/missing input blocked',file=path.name,reason=str(exc))
        else:raise AssertionError('Invalid input accepted')
    g,f,p=read_gold(out/'gold.parquet',out/'provenance.parquet',out/'certificate.json')
    # A feature at an old date must not change when later rows are removed.
    day=pd.Timestamp('2025-06-30')
    truncated=features(g[g.trading_date<=day]).set_index(['date','asset'])
    complete=f.set_index(['date','asset'])
    left=truncated.loc[truncated.index.get_level_values('date')==day,STATE+ASSET+['scale']]
    assert len(left)==20
    np.testing.assert_allclose(left,complete.loc[left.index,left.columns],rtol=0,atol=1e-10)
    passed('State and asset features invariant to removal of future rows')
    # Hash-bound provenance prevents substitution after certification.
    with tempfile.TemporaryDirectory() as temp:
        path=Path(temp)/'altered.parquet'
        changed=g.copy();changed.loc[changed.index[-1],'usdkrw']+=1
        changed.to_parquet(path,index=False)
        try:read_gold(path,out/'provenance.parquet',out/'certificate.json')
        except ValueError as exc:assert 'hash mismatch' in str(exc)
        else:raise AssertionError('Uncertified changed data accepted')
    passed('Input mutation invalidates certificate')
    restored=joblib.load(out/'model.joblib')
    x=runtime.snapshot.copy();x[SHOCKS]=[5,100,0,0]
    np.testing.assert_allclose(restored['model'].predict(x),runtime.bundle['model'].predict(x),rtol=0,atol=0)
    passed('Model serialization produces identical outputs')
    for path,value in hashes.items():assert sha(path)==value
    passed('Original model, source Gold and runtime artifacts unchanged during verification')
    save(out/'verification.json',dict(passed=True,checks=checks,azure_changed=False,fabric_changed=False,
        scope='Local actual-data ASGI API integration; cloud connectivity not tested',
        live_gold_ready=False,live_gold_blockers=['Unverified price basis','Missing publication provenance','Incomplete recent macro data']))
    print('integration passed',len(checks),'checks',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--root',required=True);parser.add_argument('--out',required=True)
    args=parser.parse_args();verify(args.root,args.out)
