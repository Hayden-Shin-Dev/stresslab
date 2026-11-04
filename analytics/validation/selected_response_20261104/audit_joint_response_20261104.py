"""Audit existing four-shock joint residual learner and explicit shock-delta semantics.

This is a decomposition of the archived 2026 model, not a new performance claim.
"""
import json,joblib
import numpy as np
import pandas as pd
from train_selected_response_20261104 import ROOT,OUT,SHOCKS

def complete_shocks(shocks):
    if set(shocks)!=set(SHOCKS):raise ValueError('All four change inputs are required; omitted is not unchanged.')
    if not all(np.isfinite(v) for v in shocks.values()):raise ValueError('Nonfinite shock')
    return np.array([shocks[s] for s in SHOCKS],dtype=float)

def levels_after(before,shocks):
    complete_shocks(shocks)
    return {'usdkrw':before['usdkrw']*(1+shocks['shock_fx']/100),
            'us_treasury_10y':before['us_treasury_10y']+shocks['shock_rate']/100,
            'wti':before['wti']*(1+shocks['shock_oil']/100),'vix':before['vix']+shocks['shock_vix']}

def main():
    zero=dict.fromkeys(SHOCKS,0.);one={**zero,'shock_rate':1.}
    before=dict(usdkrw=1400.,us_treasury_10y=4.2,wti=70.,vix=20.)
    after=levels_after(before,one)
    assert np.isclose(after['us_treasury_10y'],4.21)
    assert all(after[k]==before[k] for k in ['usdkrw','wti','vix'])
    try:complete_shocks({'shock_rate':1.})
    except ValueError:missing_rejected=True
    else:raise AssertionError('Missing shocks silently accepted')
    d=pd.read_parquet(ROOT/'reports/rich_context_20261103/learning_table.parquet')
    pairs=pd.read_csv(OUT/'frozen_pairs.csv',dtype={'asset':str});rows=[];errors=[]
    old=pd.read_parquet(ROOT/'reports/variable_analysis_20261104/response_predictions.parquet')
    for asset in sorted(pairs.asset.unique()):
        path=ROOT/'reports/variable_analysis_20261104/response_models'/asset/'orthogonal_constant.joblib'
        pack=joblib.load(path);assert not pack['interaction'];cols=pack['state_features']
        ref=old[old.asset.eq(asset)&old.method.eq('orthogonal_constant')&old.date.dt.year.eq(2026)].sort_values('date')
        te=d[d.asset.eq(asset)].set_index('date').loc[ref.date]
        g=pack['state_model'].predict(te[cols]);expected=np.column_stack([m.predict(te[cols]) for m in pack['shock_models']])
        beta=pack['response_model'].coef_/pack['shock_scale'];intercept=float(pack['response_model'].intercept_)
        baseline=g-expected@beta+intercept
        recomposed=baseline+te[SHOCKS].to_numpy()@beta
        errors.append(dict(asset=asset,n=len(te),max_recomposition_error=float(np.max(abs(recomposed-ref.center.to_numpy())))))
        assert np.allclose(recomposed,ref.center.to_numpy(),atol=1e-8)
        # The final held-out row is an archived state snapshot, not today's live market.
        i=len(te)-1
        scenarios={'all_unchanged':zero,'rate_plus_1bp':one,
          'fx_plus_1pct':{**zero,'shock_fx':1.},'oil_plus_1pct':{**zero,'shock_oil':1.},
          'vix_plus_1point':{**zero,'shock_vix':1.},'observed_5day_shocks':te.iloc[i][SHOCKS].to_dict()}
        for label,shocks in scenarios.items():
            values=complete_shocks(shocks);contribution=beta*values
            row=dict(asset=asset,state_date=str(te.index[i]),scenario=label,model='archived_orthogonal_constant_2026',
                state_average_return=float(g[i]),zero_shock_center=float(baseline[i]),center=float(baseline[i]+contribution.sum()),
                observed_target=float(te.iloc[i].target) if label=='observed_5day_shocks' else None,production_approved=False)
            for j,s in enumerate(SHOCKS):row.update({s:values[j],s+'_coefficient':float(beta[j]),s+'_contribution_pp':float(contribution[j]),s+'_state_expected':float(expected[i,j])})
            rows.append(row)
    pd.DataFrame(rows).to_csv(OUT/'four_shock_decomposition.csv',index=False)
    pd.DataFrame(errors).to_csv(OUT/'recomposition_check.csv',index=False)
    (OUT/'shock_semantics_check.json').write_text(json.dumps(dict(before=before,input_shocks=one,after=after,
        missing_rejected=missing_rejected,zero_means_unchanged_level=True,
        legacy_web_omission='engine.py marginalizes omitted factors over historical joint observations; not zero-change',
        research_contract='Four explicit change inputs. State levels stay separate.',
        existing_joint_model='Chronological out-of-sample state residuals for Y and all four shocks, followed by joint ridge response; not four independent marginal regressions.',
        interpretation='Conditional statistical decomposition, not pure causal effects; state average already includes expected shocks, hence subtract expected shocks before adding user shocks.',
        archived_model_comparison='Different training cutoff than this study. Recomposition audit only; do not mix its performance into same-fold ablation.'),indent=2))
if __name__=='__main__':main()
