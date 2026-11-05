"""Serving provenance gates. Missing publication times are never imputed."""
import pandas as pd
import json
from pathlib import Path


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
        if r.get('verified') is not True:
            continue
        boundary=r.get('available_at')
        if not boundary and r.get('availability_basis') in ('official_vintage_date_upper_bound','official_dated_document_upper_bound'):
            boundary=r.get('known_by')
        if not boundary:
            continue
        stamp = pd.Timestamp(boundary)
        if stamp.tzinfo is None or stamp > cutoff:
            continue
        if pd.Timestamp(r['observation_date']).date() > cutoff.date():
            continue
        eligible.append(r)
    return max(eligible, key=lambda r: (r['observation_date'], pd.Timestamp(r.get('available_at') or r['known_by']))) if eligible else None


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
    result=dict(model_basis_date=str(day), requested_at=pd.Timestamp.now(tz='UTC').isoformat(),
        latest_market_state=False, state_kind='frozen_research_snapshot', features=fields,
        verified_asof_state_available=False, certified_previous_observation_available=False,
        publication_status='missing_all_training_available_at',
        corporate_action_status='full_50_asset_history_not_certified',
        deployment_blockers=['Historical publication/vintage evidence is missing.',
                             'Full 50-stock corporate-action provenance is not certified.'],
        policy='No synthetic publication times or substituted zero values. Frozen estimates are exploratory only.')
    certificate=Path(__file__).with_name('service_evidence')/'source_certification.json'
    if certificate.is_file():
        proof=json.loads(certificate.read_text(encoding='utf8'))
        frozen=json.loads(Path(__file__).with_name('final_service_manifest.json').read_text(encoding='utf8'))
        if proof.get('model_sha256')==frozen['sha256'] and proof.get('model_basis_date')==str(day):
            result['source_certification']=proof
            result['publication_status']='official_vintages_partly_recovered_historical_inputs_require_correction'
            for field in fields.values():
                evidence=proof.get('latest_macro_evidence',{}).get(field['source'])
                if evidence:
                    field['publication_evidence']=evidence
                    field['observation_known_before_basis']=evidence['status']=='known_before_cutoff'
            if proof.get('price_adjustment_validation_passed'):
                result['corporate_action_status']='official_reference_price_return_continuity_verified_50_stocks'
                result['deployment_blockers']=['Historical macro inputs require point-in-time correction and frozen-model compatibility review.',
                    'ECOS historical publication/vintage evidence is not complete.']
    return result
