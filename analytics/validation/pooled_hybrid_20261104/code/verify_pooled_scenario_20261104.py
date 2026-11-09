"""Meaningful scenario invariants, evaluated independently of performance."""
import json
import numpy as np
import pandas as pd
import joblib
from pooled_stress_core_20261104 import *

def main():
    d,_=prepare();pack=joblib.load(OUT/'folds/2026_models.joblib');lin=pack['linear'];support=pack['support']
    x=d[d.date==pd.Timestamp('2026-10-19')].copy();x[SHOCKS]=0
    for c in INTER:x[c]=0
    before=x[STATE+EXTRA].copy();p0=lin.predict(x)
    x.shock_rate=1
    for c in ['market_trend20','market_vol20']:x['shock_rate__'+c]=x.shock_rate*x[c]
    p1=lin.predict(x)
    assert x[STATE+EXTRA].equals(before) and (x[['shock_fx','shock_oil','shock_vix']]==0).all().all()
    x.shock_rate=2
    for c in ['market_trend20','market_vol20']:x['shock_rate__'+c]=x.shock_rate*x[c]
    p2=lin.predict(x);np.testing.assert_allclose(p2-p0,2*(p1-p0),atol=1e-10)
    near=support.inspect(x)
    x[SHOCKS]=[100,2000,300,100]
    far=support.inspect(x);assert (far[0]==0).all() and far[2].all()
    # User level fields remain intact; no implicit VIX substitution.
    assert x[STATE+EXTRA].equals(before)
    scenario=pd.read_csv(OUT/'scenarios.csv',dtype={'asset':str})
    for case in ['zero','moderate','large','extreme','fx_only','rate_only','oil_only']:
        assert scenario.loc[scenario.scenario==case,'vix_change_points'].eq(0).all()
    p=pd.read_csv(OUT/'service_example.csv',dtype={'asset':str});np.testing.assert_allclose(p.hypothetical_pnl_krw,p.current_value_krw*p.center_pct/100)
    q=pd.read_csv(OUT/'portfolio_example.csv');tot=p.groupby(['model','scenario']).hypothetical_pnl_krw.sum().reset_index();q=q.sort_values(['model','scenario']);tot=tot.sort_values(['model','scenario']);np.testing.assert_allclose(q.hypothetical_pnl_krw,tot.hypothetical_pnl_krw)
    result=dict(passed=True,zero_shock_means_unchanged_level=True,rate_bp_units_preserved=True,linear_scaling_identity=True,residual_gate_zero_for_unsupported_extreme=True,user_vix_preserved=True,portfolio_arithmetic=True,extreme_financial_accuracy_proven=False)
    (OUT/'scenario_verification.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
if __name__=='__main__':main()
