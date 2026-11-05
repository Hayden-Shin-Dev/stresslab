"""Mechanical leakage/unit checks plus explicit unverifiable source-time limitations."""
import argparse,json
from pathlib import Path
import pandas as pd,numpy as np
from .core import features,STATE,ASSET,SHOCKS

def run(root,out):
 root=Path(root);out=Path(out);g=pd.read_parquet(root/'reports/support_expansion_20261104/research_input.parquet');d=features(g);checks={};limitations=[]
 checks['duplicate_keys']=int(g.duplicated(['asset_id','trading_date']).sum());checks['mock_rows']=int(g.is_mock.ne(False).sum())
 cols=[c for c in g if c.endswith('_available_at')];checks['missing_available_times']={c:int(g[c].isna().sum()) for c in cols}
 checks['observation_dates_after_state']={c:int((pd.to_datetime(g[c])>pd.to_datetime(g.trading_date)).sum()) for c in g if c.endswith('_observation_date')}
 macro=g[g.asset_id.eq('005930')].copy();ages={}
 for variable in ['usdkrw','us_treasury_10y','wti','vix','korea_3y']:
  age=(pd.to_datetime(macro.trading_date)-pd.to_datetime(macro[variable+'_observation_date'])).dt.days
  ages[variable]=dict(max_age_calendar_days=int(age.max()),over7_days=int(age.gt(7).sum()),latest_age_days=int(age.iloc[-1]))
 checks['observation_age']=ages
 valid=d.dropna(subset=SHOCKS+['target','end_date']);samples=valid.sample(min(200,len(valid)),random_state=4)
 table=g.set_index(['asset_id','trading_date'])
 for r in samples.itertuples():
  a=table.loc[(r.asset,r.date)];z=table.loc[(r.asset,r.end_date)]
  expected=[100*(z.usdkrw/a.usdkrw-1),100*(z.us_treasury_10y-a.us_treasury_10y),100*(z.wti/a.wti-1),z.vix-a.vix]
  np.testing.assert_allclose([getattr(r,s) for s in SHOCKS],expected,atol=1e-10);np.testing.assert_allclose(r.target,100*(z.close/a.close-1))
 checks['manual_5day_target_and_shock_checks']=len(samples);checks['one_bp_level_increment']=.01;checks['rate_percentage_point_to_bp_factor']=100
 # Future state/return mutations must not change any origin-time state feature.
 one=g[g.asset_id.eq('005930')].copy();cut=pd.Timestamp('2024-06-03');before=features(one);changed=one.copy();mask=pd.to_datetime(changed.trading_date)>cut
 for c in ['close','volume','kospi_close','usdkrw','us_treasury_10y','wti','vix','korea_3y']:changed.loc[mask,c]*=1.2
 after=features(changed);l=before[before.date.le(cut)].set_index('date')[STATE+ASSET];r=after[after.date.le(cut)].set_index('date')[STATE+ASSET];pd.testing.assert_frame_equal(l,r)
 checks['future_perturbation_state_unchanged']=True
 outliers=valid[(valid.target.abs()>100)|(valid[SHOCKS].abs().max(axis=1)>1000)].copy();outliers.to_csv(out/'extreme_learning_rows.csv',index=False)
 checks['extreme_learning_rows']=len(outliers);checks['target_min_pct']=float(valid.target.min());checks['target_max_pct']=float(valid.target.max())
 checks['finite_features']=bool(np.isfinite(valid[STATE+ASSET+SHOCKS+['target']]).all().all())
 limitations=['All publication available_at columns missing: historical release-time/revision leakage cannot be conclusively certified.', 'Macro levels are as-of observations, not simultaneous US and Korean closing prices. Shock is change in available level over five Korean sessions.', 'Historical corporate-action certification remains incomplete. Flagged rows are quarantined, not repaired by this experiment.', '2023-2026 is reused development evaluation, not blind.', 'Daily training windows overlap; date-block evaluation is required.']
 (out/'data_audit.json').write_text(json.dumps(dict(checks=checks,limitations=limitations,production_approved=False),indent=2),encoding='utf8');print(json.dumps(checks),flush=True)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--root',required=True);p.add_argument('--out',required=True);a=p.parse_args();run(a.root,a.out)
