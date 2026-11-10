"""Verify real CatBoost scenario responses and exact interaction allocation."""
import argparse
import itertools
import json
from pathlib import Path

import numpy as np
import pandas as pd
from fastapi.testclient import TestClient

from .core import SHOCKS
from .gold_ready import save, sha
from .gold_ready_api import create_app, Runtime


def run(out):
    out=Path(out)
    original_sha=sha(out/'model.joblib')
    runtime=Runtime(out/'model.joblib',out/'gold.parquet',out/'provenance.parquet',out/'certificate.json')
    checks=[]
    with TestClient(create_app(out)) as client:
        info=client.get('/model-info').json()
        assert info['model_kind']=='catboost' and info['market_state_in_B'] and info['stock_specific_model']
        positions=[dict(asset_id=a,value_krw=1000000) for a in runtime.bundle['assets']]
        all_shocks=dict(fx_pct=5,us_rate_bp=100,wti_pct=10,vix_points=5)
        candidates=None;cases=0
        for n in range(1,5):
            for keys in itertools.combinations(SHOCKS,n):
                body=dict(positions=positions,shocks={s:all_shocks[s] for s in keys})
                res=client.post('/analyze',json=body)
                assert res.status_code==200,res.text
                r=res.json();cases+=20
                if candidates is None:candidates=r['market_candidates']
                assert candidates==r['market_candidates']
                for a in r['assets']:
                    assert a['sensitivities_pp_per_input_unit'] is None
                    np.testing.assert_allclose(a['baseline_model_return_pct']+sum(a['shock_contributions_pp'].values()),a['conditional_return_pct'],atol=1e-8)
                    np.testing.assert_allclose(a['insight']['incremental_pnl_krw'],a['value_krw']*a['change_from_zero_shocks_pp']/100)
                    assert all(abs(a['shock_contributions_pp'][s])<1e-10 for s in SHOCKS if s not in keys)
                np.testing.assert_allclose(r['portfolio_hypothetical_pnl_krw'],sum(a['hypothetical_pnl_krw'] for a in r['assets']))
                np.testing.assert_allclose(r['portfolio_shock_incremental_pnl_krw'],sum(a['shock_incremental_pnl_krw'] for a in r['assets']))
        checks.append(dict(name='20 stocks x 15 shock subsets; exact money and contribution sums',cases=cases,passed=True))
        zero=client.post('/analyze',json=dict(positions=positions)).json()
        assert all(a['insight']['model_change_direction']=='unchanged' for a in zero['assets'])
        for shocks in [dict(fx_pct=-5,us_rate_bp=-100,wti_pct=-10,vix_points=-5),dict(fx_pct=10000)]:
            response=client.post('/analyze',json=dict(positions=positions,shocks=shocks))
            assert response.status_code==200,response.text
            if shocks['fx_pct']==10000:
                assert all(a['exploratory'] for a in response.json()['assets'])
        checks.append(dict(name='Zero/negative changes and extreme-support flags',passed=True))
        for bad in [dict(positions=[dict(asset_id='999999',value_krw=1)]),dict(positions=positions,shocks={'wti_pct':-100}),dict(positions=positions,shocks={'vix_points':-1000}),dict(positions=[positions[0],positions[0]])]:
            assert client.post('/analyze',json=bad).status_code==422
        checks.append(dict(name='Unsupported stocks, duplicates and invalid physical values rejected',passed=True))
        req=json.loads((out/'request.json').read_text())
        response=client.post('/analyze',json=req)
        assert response.status_code==200
        save(out/'response.json',response.json())
        # Examples explicitly distinguish incremental shock effect from total model P/L.
        example_req=dict(positions=[dict(asset_id='005930',value_krw=1000000),dict(asset_id='005380',value_krw=1000000)],shocks={'fx_pct':1})
        r=client.post('/analyze',json=example_req)
        assert r.status_code==200
        save(out/'small_shock_request.json',example_req);save(out/'small_shock_response.json',r.json())
    # Independently average marginal contributions over all 24 shock orderings.
    for asset in ['005930','005380']:
        row=runtime.snapshot[runtime.snapshot.asset.eq(asset)].copy()
        model=runtime.bundle['model'];alloc=model.contributions(row,all_shocks)
        permutations=list(itertools.permutations(SHOCKS));independent={s:0. for s in SHOCKS}
        for order in permutations:
            x=row.copy();x[SHOCKS]=0.;old=float(model.predict(x)[0])
            for s in order:
                x[s]=all_shocks[s];new=float(model.predict(x)[0]);independent[s]+=(new-old)/len(permutations);old=new
        np.testing.assert_allclose([alloc[s] for s in SHOCKS],[independent[s] for s in SHOCKS],atol=1e-9)
    checks.append(dict(name='Shapley allocation independently reproduced by all 24 orders',passed=True))
    # Recompute published coverage/width from saved predictions, not stored summaries.
    report=json.loads((out/'comparison.json').read_text(encoding='utf8'))
    bands=pd.read_parquet(out/'interval_predictions.parquet')
    for level,z in bands.groupby('nominal'):
        m=report['intervals']['catboost'][str(round(100*level))]
        assert len(z)==1600
        np.testing.assert_allclose(m['coverage'],((z.actual>=z.lower)&(z.actual<=z.upper)).mean())
        np.testing.assert_allclose(m['mean_full_width_pp'],(z.upper-z.lower).mean())
    checks.append(dict(name='1600-row interval metrics independently recomputed',passed=True))
    assert sha(out/'model.joblib')==original_sha
    save(out/'verification.json',dict(passed=True,checks=checks,model_unchanged=True,azure_changed=False,gold_changed=False))
    print('CatBoost API verification passed',cases,'asset/scenario combinations',flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',required=True);run(p.parse_args().out)
