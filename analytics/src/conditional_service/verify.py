"""End-to-end checks on a real, locally trained bundle; no cloud writes."""
import argparse
import copy
import json
import os
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
from fastapi.testclient import TestClient
from .core import analyze, validate, features, SHOCKS


def run(path, gold):
    os.environ['STRESSLAB_BUNDLE']=str(Path(path).resolve())
    from .api import app
    b=joblib.load(path);g=pd.read_parquet(gold);client=TestClient(app)
    pos=[{'asset_id':'005930','value_krw':50000000},{'asset_id':'005380','value_krw':50000000}]
    zero=client.post('/analyze',json={'positions':pos,'shocks':{}});assert zero.status_code==200
    a=client.post('/analyze',json={'positions':pos,'shocks':{'fx_pct':5,'us_rate_bp':100}});assert a.status_code==200
    z,r=zero.json(),a.json()
    assert z['market_candidates']==r['market_candidates']
    assert all(x['change_from_zero_shocks_pp']==0 for x in z['assets'])
    for x in r['assets']:
        np.testing.assert_allclose(sum(x['statistical_contributions_pp'].values()),x['change_from_zero_shocks_pp'])
        np.testing.assert_allclose(x['hypothetical_pnl_krw'],x['value_krw']*x['center_pct']/100)
    np.testing.assert_allclose(sum(x['hypothetical_pnl_krw'] for x in r['assets']),r['total_hypothetical_pnl_krw'])
    assert client.post('/analyze',json={'positions':pos*2}).status_code==422
    assert client.post('/analyze',json={'positions':pos,'shocks':{'wti_pct':-100}}).status_code==422
    assert client.post('/analyze',json={'positions':[{'asset_id':'NO_ASSET','value_krw':1}]}).status_code==422
    # An actual older daily snapshot, not fabricated market data.
    f=features(g);complete=f.groupby('date').asset.nunique();old_date=complete[complete==len(b['snapshot'])].index[-21]
    old=copy.copy(b);old['snapshot']=f[f.date==old_date].copy()
    old['history']=b['history'][b['history'].end_date<old_date-pd.Timedelta(days=20)]
    previous=analyze(old,pos,{'fx_pct':5,'us_rate_bp':100})
    assert previous['state_date']!=r['state_date']
    assert previous['market_state']!=r['market_state']
    # This is a current-model sensitivity replay, not a past-time out-of-sample claim.
    blocked=False
    try:validate(g,research=False)
    except ValueError:blocked=True
    assert blocked, 'Current source publication times must not be silently approved'
    # Future row edits cannot alter an earlier state feature vector.
    t=pd.Timestamp(old_date);changed=g.copy();mask=pd.to_datetime(changed.trading_date)>t
    changed.loc[mask,'close']*=1.3
    before=f[f.date==t].sort_values('asset');after=features(changed);after=after[after.date==t].sort_values('asset')
    np.testing.assert_allclose(before.market_trend20,after.market_trend20)
    np.testing.assert_allclose(before.asset_trend20,after.asset_trend20)
    output={'api_flow_passed':True,'shock_excluded_from_stage_A':True,'zero_means_unchanged_levels':True,
        'contributions_sum_to_model_delta':True,'portfolio_amounts_verified':True,
        'invalid_requests_rejected':True,'future_prices_do_not_change_current_features':True,
        'production_gate_rejects_unverified_publication_times':True,
        'state_change_check':{'old_date':str(t.date()),'new_date':r['state_date'],
            'old_portfolio':previous['total_hypothetical_pnl_krw'],'new_portfolio':r['total_hypothetical_pnl_krw'],
            'old_candidates':[x['date'] for x in previous['market_candidates']],
            'new_candidates':[x['date'] for x in r['market_candidates']],
            'interpretation':'Fixed current model and position values; historical state substitution only, not a backtest'},
        'real_scenario':r}
    dest=Path(path).parent/'integration_verification.json';dest.write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf8')
    print('Integration verified:',dest)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--bundle',required=True);p.add_argument('--gold',required=True);a=p.parse_args();run(a.bundle,a.gold)
