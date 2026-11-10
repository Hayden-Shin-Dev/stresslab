"""KRX dated industry references. Does not backfill today's industry into old dates."""
import hashlib
import json
import re
from pathlib import Path
import pandas as pd


def read_references(directory):
    records = []
    for path in sorted(Path(directory).glob('*.json')):
        raw = path.read_bytes()
        obj = json.loads(raw)
        if obj.get('source') != 'KRX' or obj.get('bld') != 'dbms/MDC/STAT/standard/MDCSTAT03901':
            raise ValueError('Unexpected sector source: ' + path.name)
        date = pd.Timestamp(obj['query_date']).normalize()
        received = pd.Timestamp(obj['retrieved_at'])
        if received.tzinfo is None or date.date() > received.tz_convert('Asia/Seoul').date():
            raise ValueError('Invalid sector reference date')
        seen = set()
        for row in obj['rows']:
            asset = str(row['ISU_SRT_CD'])
            name = str(row.get('IDX_IND_NM') or '').strip()
            if row.get('MKT_TP_NM') != 'KOSPI':
                raise ValueError('Unexpected market')
            if not re.fullmatch(r'[0-9A-Z]{6}', asset) or asset in seen:
                raise ValueError('Invalid or duplicate asset: ' + asset)
            seen.add(asset)
            if not name or name == '-':
                continue
            records.append({'asset_id': asset, 'sector_id': 'KRX_KOSPI:' + name,
                            'classification_date': date, 'retrieved_at': received,
                            'source_ref': path.name, 'source_sha256': hashlib.sha256(raw).hexdigest()})
    if not records:
        raise ValueError('No official sector references')
    result = pd.DataFrame(records)
    if result.duplicated(['asset_id', 'classification_date']).any():
        raise ValueError('Overlapping reference snapshots')
    return result


def assign_current_sectors(keys, references):
    """Attach current industry metadata to all dates, never historical PIT evidence."""
    left = keys[['trading_date', 'asset_id']].copy()
    left['trading_date'] = pd.to_datetime(left.trading_date).dt.normalize()
    if left.duplicated(['trading_date', 'asset_id']).any():
        raise ValueError('Duplicate stock keys')
    latest = references.sort_values(['classification_date', 'retrieved_at']).drop_duplicates('asset_id', keep='last')
    result = left.merge(latest, on='asset_id', how='left', validate='many_to_one')
    missing = result.loc[result.sector_id.isna(), 'asset_id'].unique().tolist()
    if missing:
        raise ValueError('Missing official industry reference: ' + ','.join(missing))
    result['classification_age_days'] = (result.trading_date-result.classification_date).dt.days
    result['classification_basis'] = 'current_reference_metadata'
    # 2026-11-10 민철 추가: 과거 행에도 현재 업종을 표시하되 과거 당시 알려진 분류로 취급하지 않습니다.
    result['point_in_time_known'] = False
    result['historical_backfill'] = result.trading_date < result.classification_date
    return result


def assign_sectors(keys, references, max_age_days=30):
    """As-of classification for descriptive use; retrieval time is NOT a past release time."""
    if max_age_days is not None and max_age_days < 0:
        raise ValueError('Negative maximum age')
    left = keys[['trading_date', 'asset_id']].copy()
    left['trading_date'] = pd.to_datetime(left.trading_date).dt.normalize()
    if left.duplicated(['trading_date', 'asset_id']).any():
        raise ValueError('Duplicate stock keys')
    result = pd.merge_asof(left.sort_values('trading_date'),
                          references.sort_values('classification_date'),
                          left_on='trading_date', right_on='classification_date', by='asset_id',
                          direction='backward', tolerance=None if max_age_days is None else pd.Timedelta(days=max_age_days))
    result['classification_age_days'] = (result.trading_date-result.classification_date).dt.days
    result['point_in_time_known'] = result.retrieved_at.notna() & (
        result.retrieved_at <= result.trading_date.dt.tz_localize('Asia/Seoul') + pd.Timedelta(hours=15, minutes=30))
    return result
