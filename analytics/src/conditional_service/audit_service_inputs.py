"""Deterministic data/feature checks before the same-setting service rebuild."""
import os,json,hashlib
from pathlib import Path
import pandas as pd,numpy as np
from .core import features,STATE,ASSET,SHOCKS

def main():
    root=Path(os.environ['STRESSLAB_REBUILD_OUT'])
    g=pd.read_parquet(root/'corrected_daily_input.parquet')
    f=pd.read_parquet(root/'corrected_features.parquet')
    assert not g.duplicated(['trading_date','asset_id']).any()
    assert not f.duplicated(['date','asset']).any()
    assert g.is_mock.eq(False).all() and g.price_basis.eq('adjusted').all()
    regenerated=features(g).set_index(['date','asset']).sort_index()
    stored=f.set_index(['date','asset']).sort_index()
    assert regenerated.index.equals(stored.index)
    for col in STATE+ASSET+SHOCKS+['target','scale']:
        np.testing.assert_allclose(regenerated[col],stored[col],equal_nan=True,rtol=1e-12,atol=1e-12)
    prov=pd.read_parquet(root/'observation_provenance.parquet');known=prov[prov.verified]
    boundary=pd.to_datetime(known.known_by,utc=True)
    assert (boundary<=pd.to_datetime(known.date,utc=True)+pd.Timedelta(hours=6,minutes=30)).all()
    age=(known.date-known.observation_date).dt.days
    assert age.between(0,10).all()
    complete=f.dropna(subset=SHOCKS+['target','end_date','label_known_by'])
    assert np.isfinite(complete[STATE+ASSET+SHOCKS+['target','scale']]).all().all()
    assert (pd.to_datetime(complete.label_known_by,utc=True)<=pd.to_datetime(complete.end_date,utc=True)+pd.Timedelta(hours=6,minutes=30)).all()
    # Perturb only future data. Earlier state features and matured labels must not change.
    cut=pd.Timestamp('2024-01-02');stock=g.asset_id.iloc[0];one=g[g.asset_id.eq(stock)].copy()
    first=features(one);changed=one.copy();later=changed.trading_date>cut
    for col in ['close','kospi_close','usdkrw','us_treasury_10y','wti','vix','korea_3y']:
        changed.loc[later,col]=changed.loc[later,col]*1.2
    second=features(changed)
    a=first[first.date<=cut].set_index('date');b=second[second.date<=cut].set_index('date')
    np.testing.assert_allclose(a[STATE+ASSET],b[STATE+ASSET],equal_nan=True)
    eligible=a.end_date<=cut
    np.testing.assert_allclose(a.loc[eligible,SHOCKS+['target']],b.loc[eligible,SHOCKS+['target']],equal_nan=True)
    report=dict(passed=True,complete_rows=len(complete),assets=complete.asset.nunique(),
        features_and_targets_reproduced=True,duplicate_keys_absent=True,finite_complete_inputs=True,
        availability_and_age_checks=True,future_data_perturbation_does_not_change_earlier_inputs=True,
        units={'fx_pct':'percent change','us_rate_bp':'percentage-point change multiplied by 100','wti_pct':'percent change','vix_points':'index point change'},
        feature_file_sha256=hashlib.sha256((root/'corrected_features.parquet').read_bytes()).hexdigest())
    (root/'input_audit.json').write_text(json.dumps(report,indent=2),encoding='utf8')
    print(json.dumps(report))

if __name__=='__main__':main()
