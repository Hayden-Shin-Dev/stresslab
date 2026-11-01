"""Coverage-aware cross-sectional diagnostics. Research v2; no ML promotion."""
import numpy as np
import pandas as pd

def aggregate_market(prices,minimum_coverage=.8):
    """61 completed minute rows, columns are the explicitly selected stock universe.

    Missing observations are never zero returns. Correlation uses the disclosed
    complete 60-return subset. Its O(T*N) computation avoids an N*N matrix.
    """
    if len(prices)!=61 or prices.shape[1]<2:raise ValueError('require_61_rows_and_multiple_stocks')
    if not .5<=minimum_coverage<=1:raise ValueError('invalid_coverage_threshold')
    if not prices.index.is_monotonic_increasing or prices.index.duplicated().any():raise ValueError('invalid_time_order')
    if not (prices.index.to_series().diff().dropna()==pd.Timedelta(minutes=1)).all():raise ValueError('minute_grid_required')
    if ((prices<=0)&prices.notna()).any().any():raise ValueError('nonpositive_price')
    n=prices.shape[1];valid5=prices.iloc[-6:].notna().all()
    r5=prices.iloc[-1]/prices.iloc[-6]-1
    returns=np.log(prices/prices.shift(1)).iloc[1:]
    complete=returns.loc[:,returns.notna().all()]
    nonconstant=complete.loc[:,complete.std(ddof=1)>0]
    n_corr=nonconstant.shape[1];correlation=None
    if n_corr>=2 and n_corr/n>=minimum_coverage:
        z=(nonconstant-nonconstant.mean())/nonconstant.std(ddof=1)
        correlation=float(((z.sum(axis=1)**2).sum()/59-n_corr)/(n_corr*(n_corr-1)))
    counts=returns.notna().sum(axis=1)
    good=counts/n>=minimum_coverage
    down=(returns<0).sum(axis=1)/counts.replace(0,np.nan)
    return {'definition_version':'coverage-aware-market-v2','expected_stocks':n,
        'return_5m_stocks':int(valid5.sum()),'return_5m_coverage':float(valid5.mean()),
        'declining_share':float((r5[valid5]<0).mean()) if valid5.mean()>=minimum_coverage else None,
        'correlation_stocks':n_corr,'mean_correlation_60m':correlation,
        'joint_down_valid_minutes':int(good.sum()),
        'joint_down_share_60m':float((down>=.8).mean()) if good.all() else None,
        'minimum_coverage':minimum_coverage,'whole_market':False,
        'note':'coverage is relative to supplied universe; exchange membership must be verified separately'}
