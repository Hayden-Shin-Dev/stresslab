"""Silver/Gold 증거 연결. 원천 숫자와 정확한 공표 시각을 만들어내지 않습니다."""
# 2026-11-09 12:50 KST 민철 추가 — 로컬 검증 근거와 일별 수집 근거를 같은 규칙으로 연결.
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

MACROS = ['usdkrw', 'us_treasury_10y', 'wti', 'vix', 'korea_3y']


def certified_files(bronze):
    """완료 manifest에 등록되고 해시가 같은 원천만 사용합니다."""
    root = Path(bronze).resolve()
    found = {}
    for path in sorted((root/'_runs').glob('*/SUCCESS.json')):
        m = json.loads(path.read_text(encoding='utf8'))
        if m.get('status') not in ('complete', 'no_market_observations'):
            continue
        for f in m.get('files', []):
            rel = f['file'].replace('\\', '/')
            if not any(rel.startswith(s+'/api/') for s in ('krx', 'fred', 'ecos')):
                continue
            full = (root/rel).resolve()
            if not full.is_relative_to(root):
                raise ValueError('원천 경로 이탈')
            if rel in found:
                if found[rel][0] != f['sha256']:
                    raise ValueError('같은 원천 경로의 manifest 해시 충돌')
                continue
            content = full.read_bytes()
            if hashlib.sha256(content).hexdigest() != f['sha256']:
                raise ValueError('원천 해시 불일치: '+rel)
            doc = json.loads(content)
            if doc.get('is_mock') is not False:
                raise ValueError('실데이터 확인 불가: '+rel)
            found[rel] = (f['sha256'], doc)
    return found


def receipt_events(files):
    """수신시각은 해당 버전을 확보한 상한시각입니다. 발표시각이 아닙니다."""
    events = []
    for rel, (digest, doc) in files.items():
        source = Path(rel).stem if rel.startswith('fred/') else 'korea_3y'
        if not rel.startswith(('fred/', 'ecos/')) or source not in MACROS:
            continue
        received = pd.to_datetime(doc.get('retrieved_at'), utc=True, errors='coerce')
        if pd.isna(received):
            continue
        for r in doc.get('rows', []):
            if isinstance(r, str):
                r = json.loads(r)
            if source == 'korea_3y':
                if r.get('STAT_CODE') != '817Y002' or r.get('ITEM_CODE1') != '010200000':
                    raise ValueError('ECOS 지표 코드 불일치')
                day, value = r.get('TIME'), r.get('DATA_VALUE')
            else:
                day, value = r.get('date'), r.get('value')
            obs = pd.to_datetime(day, errors='coerce')
            value = pd.to_numeric(value, errors='coerce')
            if pd.isna(obs) or pd.isna(value) or not np.isfinite(value):
                continue
            if source == 'usdkrw' and value <= 0 or source == 'vix' and value < 0:
                continue
            if obs.date() > received.tz_convert('Asia/Seoul').date():
                raise ValueError('수신일보다 미래의 관측일')
            events.append(dict(source=source, observation_date=obs, value=float(value),
                known_by=received, source_ref='Files/bronze/'+rel,
                availability_basis='recorded_retrieval_upper_bound', evidence_sha256=digest))
    return pd.DataFrame(events)


def macro_curve(days, reference, files):
    """로컬의 날짜별 PIT 선택을 보존하고 새 날짜는 수신 근거로 연장합니다."""
    ref = reference.copy()
    ref['date'] = pd.to_datetime(ref.date)
    ref['observation_date'] = pd.to_datetime(ref.observation_date)
    ref['known_by'] = pd.to_datetime(ref.known_by, utc=True)
    if ref.duplicated(['date', 'source']).any():
        raise ValueError('공표 근거 중복')
    good = ref[ref.verified].copy()
    cutoff = pd.to_datetime(good.date, utc=True)+pd.Timedelta(hours=6, minutes=30)
    if (good.known_by.isna() | good.known_by.gt(cutoff)).any():
        raise ValueError('과거 이용 가능 시각 오류')
    good['availability_basis'] = 'official_conservative_date_upper_bound'
    good['evidence_sha256'] = None
    events = pd.concat([good.drop(columns=['date', 'verified']), receipt_events(files)], ignore_index=True)
    events = events.drop_duplicates(['source', 'observation_date', 'known_by', 'value'])
    conflict = events.groupby(['source', 'observation_date', 'known_by']).value.nunique()
    if (conflict > 1).any():
        raise ValueError('동일 시점 거시 값 충돌')
    rows = []
    for name in MACROS:
        q = events[events.source.eq(name)].sort_values(['known_by', 'observation_date'])
        recs = list(q.to_dict('records')); cursor = 0; latest = {}
        original = ref[ref.source.eq(name)].set_index('date')
        for day in pd.DatetimeIndex(sorted(set(pd.to_datetime(days)))):
            asof = day.tz_localize('Asia/Seoul')+pd.Timedelta(hours=15, minutes=30)
            while cursor < len(recs) and recs[cursor]['known_by'] <= asof:
                r = recs[cursor]; latest[r['observation_date']] = r; cursor += 1
            # 과거 검증 결과를 새로 수신한 수정 버전으로 덮어쓰지 않습니다.
            if day in original.index:
                r = original.loc[day].to_dict()
                r['availability_basis'] = 'official_conservative_date_upper_bound'
                r['evidence_sha256'] = None
            else:
                eligible = [latest[day-pd.Timedelta(days=lag)] for lag in range(11)
                            if day-pd.Timedelta(days=lag) in latest]
                r = dict(max(eligible, key=lambda r:r['observation_date'])) if eligible else {}
            valid = bool(r.get('verified', bool(r))) and pd.notna(r.get('value'))
            if valid:
                valid = (pd.notna(r.get('known_by')) and r['known_by'] <= asof
                         and 0 <= (day-r['observation_date']).days <= 10)
            rows.append(dict(date=day, source=name, value=r.get('value') if valid else np.nan,
                observation_date=r.get('observation_date') if valid else pd.NaT,
                known_by=r.get('known_by') if valid else pd.NaT, source_ref=r.get('source_ref') if valid else None,
                availability_basis=r.get('availability_basis') if valid else 'unverified',
                evidence_sha256=r.get('evidence_sha256') if valid else None, verified=valid))
    return pd.DataFrame(rows)


def price_metadata(stocks, reference, files):
    """검증된 가격과 공식 전일 대비 등락을 확인하며 가격 자체는 변경하지 않습니다."""
    s, ref = stocks.copy(), reference.copy()
    for d in (s, ref):
        d['trading_date'] = pd.to_datetime(d.trading_date)
        if d.duplicated(['asset_id', 'trading_date']).any():
            raise ValueError('価格キー重複')
    api = {}; assets = set(s.asset_id)
    for rel, (_, doc) in files.items():
        if not rel.startswith('krx/') or '/stocks/' not in rel:
            continue
        for raw in doc.get('rows', []):
            asset = raw.get('ISU_SRT_CD') or raw.get('ISU_CD')
            if asset not in assets:
                continue
            day = pd.to_datetime(raw['BAS_DD'])
            def num(k): return float(str(raw[k]).replace(',', ''))
            data = (num('TDD_CLSPRC'), num('ACC_TRDVOL'), num('CMPPREVDD_PRC'), num('FLUC_RT'))
            if (asset, day) in api and api[asset, day] != data:
                raise ValueError('KRX 재수집 값 충돌: '+asset+' '+str(day.date()))
            api[asset, day] = data
    out = []; issues = []
    for asset, group in s.groupby('asset_id'):
        r = ref[ref.asset_id.eq(asset)].set_index('trading_date')
        previous = None; broken = False
        for x in group.sort_values('trading_date').itertuples():
            day = x.trading_date; basis = 'unknown'; version = None; status = x.quality_status
            reason = None
            if day in r.index:
                y = r.loc[day]
                if not np.isclose(x.close, y.close, rtol=0, atol=1e-8) or x.volume != y.volume:
                    reason = 'verified_history_mismatch'; broken = True
                else:
                    basis, version = y.price_basis, y.adjustment_version
                    if y.quality_status == 'quarantined': status = 'quarantined'
                    previous = float(x.close); broken = False
            elif previous is None or broken:
                reason = 'no_verified_price_boundary'
            elif (asset, day) not in api:
                reason = 'missing_official_daily_evidence'; broken = True
            else:
                close, volume, change, pct = api[asset, day]
                if (close <= 0 or volume < 0 or abs(close-x.close)>1e-8 or volume!=x.volume
                    or abs((close-change)-previous)>.51 or abs((close/previous-1)*100-pct)>.011):
                    reason = 'corporate_action_or_price_mismatch'; broken = True
                else:
                    basis='adjusted'; version='krx-20261016-bridge-'+day.strftime('%Y%m%d')
                    previous=close
            if reason:
                status='quarantined'; issues.append(dict(asset_id=asset,date=str(day.date()),reason=reason))
            out.append(dict(asset_id=asset,trading_date=day,price_basis=basis,
                adjustment_version=version,quality_status=status))
    return pd.DataFrame(out), issues
