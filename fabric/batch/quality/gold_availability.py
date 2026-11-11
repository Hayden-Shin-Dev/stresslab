"""Value-specific, as-of Gold selection. No fabricated exact publication clocks."""
# 2026-11-10 17:34 KST 민철 추가: 로컬 별도 근거 검증을 Gold 값 선택 전에 적용합니다.
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
from availability_policy import evidence_status, POLICY_VERSION

VERSION = 'gold-asof-evidence-v1-20261110'
SOURCES = ('usdkrw', 'us_treasury_10y', 'wti', 'vix', 'korea_3y')
ALLOWED = {
    'fred_vintage_date_conservative_upper_bound',
    'bok_registered_document_date_upper_bound',
    'bok_official_rss_publication_timestamp',
    'fed_h10_official_rss_publication_timestamp',
    'official_ddp_available_notice_timestamp',
    'official_fed_release_date_end_new_york',
    'official_bok_document_date_upper_bound',
}


def select_asof(days, ledger, source):
    """Select the most recent observation actually supported before 15:30 KST.

    Callers must obtain ledger from publication_evidence.load_ledger, which
    verifies normalized records, original documents, and their dependencies.
    A new revision never retroactively replaces its earlier vintage.
    """
    if source not in SOURCES:
        raise ValueError('unknown_source')
    events = ledger[ledger.source.eq(source)].copy()
    # A historical verification summary alone is not a primary document.
    # New BOK raw-document/RSS records supersede this legacy summary chain.
    events = events[~events.availability_basis.eq('previously_verified_bok_document_chain')].copy()
    events.observation_date = pd.to_datetime(events.observation_date).astype('datetime64[ns]')
    for col in ['known_by', 'valid_until', 'publication_at']:
        events[col] = pd.to_datetime(events[col], utc=True)
    if not events.availability_basis.isin(ALLOWED).all():
        raise ValueError('unrecognized_availability_basis')
    if events[['known_by', 'observation_date', 'value', 'evidence_sha256', 'source_ref']].isna().any().any():
        raise ValueError('incomplete_evidence')
    if not np.isfinite(events.value).all():
        raise ValueError('nonfinite_evidence')
    if not events.evidence_sha256.str.fullmatch('[a-f0-9]{64}').all():
        raise ValueError('invalid_evidence_digest')
    exact = events.publication_at.notna()
    if (events.loc[exact, 'publication_at'] > events.loc[exact, 'known_by']).any():
        raise ValueError('evidence_precedes_publication')
    rows = []
    obs_ns = events.observation_date.to_numpy(dtype='datetime64[ns]').astype('int64')
    known_ns = events.known_by.astype('datetime64[ns, UTC]').astype('int64').to_numpy()
    until_ns = events.valid_until.astype('datetime64[ns, UTC]').astype('int64').to_numpy()
    until_missing = events.valid_until.isna().to_numpy()
    for day in pd.DatetimeIndex(sorted(set(pd.to_datetime(days)))):
        cutoff = day.tz_localize('Asia/Seoul') + pd.Timedelta(hours=15, minutes=30)
        indexes = np.flatnonzero((obs_ns < day.value) & (known_ns <= cutoff.value) &
                                 (until_missing | (cutoff.value < until_ns)))
        record = dict(date=day, source=source, value=np.nan, observation_date=pd.NaT,
                      known_by=pd.NaT, valid_until=pd.NaT, publication_at=pd.NaT,
                      availability_basis='unverified', source_ref=None, evidence_sha256=None,
                      verified=False, timing_status='no_evidence_before_cutoff',
                      cutoff_at=cutoff, evidence_precision='unverified', observation_age_days=None,
                      policy_version=POLICY_VERSION)
        if len(indexes):
            indexes = indexes[obs_ns[indexes] == obs_ns[indexes].max()]
            # Prefer the latest vintage. A more recent publication of a different
            # value must not borrow an older version's earlier known_by.
            indexes = indexes[known_ns[indexes] == known_ns[indexes].max()]
            q = events.iloc[indexes]
            if q.value.nunique() != 1:
                record['timing_status'] = 'conflicting_vintage_values'
            else:
                r = q.sort_values(['publication_at', 'source_ref'], na_position='first').iloc[-1]
                status = evidence_status(source, r.observation_date, r.known_by, day)
                record.update(known_by=r.known_by, valid_until=r.valid_until,
                    availability_basis=r.availability_basis, source_ref=r.source_ref,
                    evidence_sha256=r.evidence_sha256,
                    observation_age_days=int((day-r.observation_date).days))
                if status == 'usable':
                    record.update(value=float(r.value), observation_date=r.observation_date,
                        publication_at=r.publication_at, verified=True,
                        timing_status='verified_official_notice' if pd.notna(r.publication_at) else 'verified_date_upper_bound',
                        evidence_precision='official_notice_timestamp' if pd.notna(r.publication_at) else 'conservative_date_bound')
                else:
                    record['timing_status'] = status
        rows.append(record)
    result = pd.DataFrame(rows)
    for col in ['known_by', 'valid_until', 'publication_at', 'cutoff_at']:
        result[col] = pd.to_datetime(result[col], utc=True)
    result.observation_date = pd.to_datetime(result.observation_date)
    return result


def validate_gold_provenance(gold, provenance):
    """Check actual value/date/bound match, not a blanket Boolean approval."""
    if provenance.duplicated(['date', 'source']).any():
        raise ValueError('duplicate_provenance')
    days = pd.to_datetime(gold.trading_date)
    checks = {}
    for source in SOURCES:
        p = provenance[provenance.source.eq(source)].copy()
        p['date'] = pd.to_datetime(p.date)
        p = p.set_index('date')
        values = days.map(p.value)
        if not np.allclose(gold[source], values, equal_nan=True):
            raise ValueError('gold_evidence_value_mismatch:' + source)
        obs = pd.to_datetime(gold[source+'_observation_date'])
        if not (obs.eq(days.map(p.observation_date)) | (obs.isna() & days.map(p.observation_date).isna())).all():
            raise ValueError('gold_evidence_observation_mismatch:' + source)
        exact = pd.to_datetime(gold[source+'_available_at'], utc=True)
        expected = pd.to_datetime(days.map(p.publication_at), utc=True)
        if not (exact.eq(expected) | (exact.isna() & expected.isna())).all():
            raise ValueError('exact_publication_field_mismatch:' + source)
        for r in p[p.value.notna()].itertuples():
            if not r.verified or evidence_status(source, r.observation_date, r.known_by, r.Index) != 'usable':
                raise ValueError('unverified_gold_value:' + source)
            cutoff = pd.Timestamp(r.Index).tz_localize('Asia/Seoul') + pd.Timedelta(hours=15, minutes=30)
            if pd.notna(r.valid_until) and cutoff >= r.valid_until:
                raise ValueError('expired_vintage:' + source)
        checks[source] = {'verified_dates': int(p.verified.sum()),
                          'excluded_dates': int((~p.verified).sum()),
                          'reasons': p.timing_status.value_counts().to_dict()}
    return checks


def write_evidence_certificate(folder, ledger, checks):
    folder = Path(folder)
    ledger.to_parquet(folder/'publication_ledger.parquet', index=False)
    certificate = {
        'version': VERSION, 'policy_version': POLICY_VERSION,
        'ledger_sha256': hashlib.sha256((folder/'publication_ledger.parquet').read_bytes()).hexdigest(),
        'macro_value_selection': 'observation_date_before_day_and_known_by_before_1530_KST',
        'actual_publication_timestamp_inferred': False,
        'conservative_bounds_are_exact_timestamps': False,
        'checks': checks,
        'scope': 'macro availability; not full price-vintage, sector-history or model approval',
    }
    (folder/'availability_certificate.json').write_text(json.dumps(certificate, ensure_ascii=False, indent=2), encoding='utf8')
    return certificate
