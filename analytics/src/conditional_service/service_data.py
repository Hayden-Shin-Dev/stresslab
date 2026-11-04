"""Serving provenance gates. Missing publication times are never imputed."""
import pandas as pd


def available_asof(records, cutoff):
    """Select a verified vintage known at cutoff, or return None.

    records: observation_date, available_at, value, verified (optional vintage_id).
    A later download time cannot certify historical publication availability.
    """
    cutoff = pd.Timestamp(cutoff)
    if cutoff.tzinfo is None:
        raise ValueError('Timezone-aware cutoff required')
    eligible = []
    for r in records:
        if r.get('verified') is not True or not r.get('available_at'):
            continue
        stamp = pd.Timestamp(r['available_at'])
        if stamp.tzinfo is None or stamp > cutoff:
            continue
        if pd.Timestamp(r['observation_date']).date() > cutoff.date():
            continue
        eligible.append(r)
    return max(eligible, key=lambda r: (r['observation_date'], pd.Timestamp(r['available_at']))) if eligible else None


def state_metadata(bundle):
    snapshot = bundle['expanded']['snapshot']
    if snapshot.empty:
        raise ValueError('Frozen market snapshot missing')
    day = pd.Timestamp(snapshot.date.iloc[0]).date()
    mapping = {
        'market_trend20': ('kospi', 20), 'market_vol20': ('kospi', 20),
        'fx_trend20': ('usdkrw', 20), 'rate_level': ('us_treasury_10y', 0),
        'oil_level': ('wti', 0), 'vix_level': ('vix', 0),
        'kr3y_level': ('korea_3y', 0), 'kr3y_change20': ('korea_3y', 20),
        'asset_trend5': ('price', 5), 'asset_trend20': ('price', 20),
        'asset_vol20': ('price', 20), 'asset_vol60': ('price', 60),
        'volume_ratio20': ('volume', 20), 'drawdown60': ('price', 60)}
    fields = {}
    for feature, (source, window) in mapping.items():
        observation = str(day) if source in ('kospi', 'price', 'volume') else bundle.get('source_observation_dates', {}).get(source)
        fields[feature] = dict(source=source, observation_date=observation,
            model_basis_date=str(day), available_at=None, publication_verified=False,
            age_at_model_basis_calendar_days=(day-pd.Timestamp(observation).date()).days if observation else None,
            lookback_trading_days=window, constituent_publication_times_verified=False)
    return dict(model_basis_date=str(day), requested_at=pd.Timestamp.now(tz='UTC').isoformat(),
        latest_market_state=False, state_kind='frozen_research_snapshot', features=fields,
        verified_asof_state_available=False, certified_previous_observation_available=False,
        publication_status='missing_all_training_available_at',
        corporate_action_status='full_50_asset_history_not_certified',
        deployment_blockers=['Historical publication/vintage evidence is missing.',
                             'Full 50-stock corporate-action provenance is not certified.'],
        policy='No synthetic publication times or substituted zero values. Frozen estimates are exploratory only.')
