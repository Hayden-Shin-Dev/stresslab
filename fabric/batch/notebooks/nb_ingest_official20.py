# Fabric notebook source

# METADATA ********************

# META {
# META   "kernel_info": {
# META     "name": "synapse_pyspark"
# META   },
# META   "dependencies": {
# META     "lakehouse": {
# META       "default_lakehouse": "93432592-8620-411e-808f-b91678bf78d2",
# META       "default_lakehouse_name": "lh_whatif",
# META       "default_lakehouse_workspace_id": "2c303c0d-6c10-4988-91cb-856fe5f56071"
# META     }
# META   }
# META }

# PARAMETERS CELL ********************

# 민철 2026-11-09 수정 (고정 과거 날짜에서 빈 기본값으로 바꾸어 직접 실행도 전일 기준 자동 수집되도록 함).
start_date = ""
end_date = ""


# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************

"""Official API Bronze ingestion. Never joins raw prices to adjusted history."""
import json,hashlib,time
from pathlib import Path
from datetime import datetime,timezone
import pandas as pd
import requests
# 민철 2026-11-09 추가 (과거 정상 행 존재 검사에서 거래일별 종목 완전성과 최신 입력 검사로 바꾸어 불완전한 자료의 정상 게시를 차단함).
import json
import math
import os
from pathlib import Path
import numpy as np
import pandas as pd

def write_quality_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.pending-' + __import__('uuid').uuid4().hex)
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str, allow_nan=False), encoding='utf8')
    os.replace(temp, path)

def validate_source_batch(stock_rows, index_rows, macro_rows, assets, sessions, end):
    expected = set(assets)
    if len(expected) != 20 or not sessions:
        raise ValueError('EXPECTED_SESSIONS_OR_ASSETS_EMPTY')
    daily = {}
    for row in stock_rows:
        asset = row.get('ISU_SRT_CD') or row.get('ISU_CD')
        if asset not in expected:
            continue
        day = row['BAS_DD']
        daily.setdefault(day, {})
        if asset in daily[day]:
            raise ValueError('DUPLICATE_STOCK_KEY:' + day + ':' + asset)
        close = float(str(row['TDD_CLSPRC']).replace(',', ''))
        volume = float(str(row['ACC_TRDVOL']).replace(',', ''))
        if not math.isfinite(close) or close <= 0 or not math.isfinite(volume) or volume < 0:
            raise ValueError('INVALID_STOCK_VALUE:' + day + ':' + asset)
        daily[day][asset] = True
    index_days = {r['BAS_DD'] for r in index_rows}
    for day in sessions:
        if set(daily.get(day, {})) != expected:
            raise ValueError('MISSING_STOCKS:' + day + ':' + ','.join(sorted(expected-set(daily.get(day, {})))))
        if day not in index_days:
            raise ValueError('MISSING_INDEX:' + day)
    latest = {}
    for name, rows in macro_rows.items():
        values = []
        seen = set()
        for row in rows:
            raw = row.get('value', row.get('DATA_VALUE'))
            if raw in (None, '', '.'):
                continue
            value = float(raw)
            if not math.isfinite(value):
                raise ValueError('NONFINITE_MACRO:' + name)
            day = pd.Timestamp(row.get('date', row.get('TIME')))
            if day > pd.Timestamp(end) or day in seen:
                raise ValueError('FUTURE_OR_DUPLICATE_MACRO:' + name)
            seen.add(day)
            values.append(day)
        if not values:
            raise ValueError('EMPTY_MACRO:' + name)
        latest[name] = max(values).strftime('%Y-%m-%d')
        # 공표 지연을 0건 응답과 구분합니다. Gold는 기존 모델의 7일 선택 기준을 추가 검사합니다.
        limit = 14 if name == 'usdkrw' else 10
        if (pd.Timestamp(end)-max(values)).days > limit:
            raise ValueError('STALE_SOURCE:' + name + ':' + latest[name])
    if set(latest) != {'usdkrw','us_treasury_10y','wti','vix','korea_3y'}:
        raise ValueError('MISSING_MACRO_SOURCE')
    return {'status':'ready', 'expected_latest':pd.Timestamp(sessions[-1]).strftime('%Y-%m-%d'),
            'expected_assets':sorted(expected), 'expected_sessions':sessions,
            'latest_macro_observation':latest, 'end':pd.Timestamp(end).strftime('%Y-%m-%d'),
            'source_asset_counts':{d:len(daily[d]) for d in sessions}}

def validate_gold_ready(frame, source_health, now=None):
    now = pd.Timestamp.now(tz='UTC') if now is None else pd.Timestamp(now)
    if now.tzinfo is None:
        raise ValueError('QUALITY_CLOCK_MUST_BE_TIMEZONE_AWARE')
    if source_health.get('status') != 'ready':
        raise ValueError('BRONZE_NOT_READY')
    received = pd.Timestamp(source_health['checked_at_utc'])
    if received.tzinfo is None or received > now or now-received > pd.Timedelta(hours=18):
        raise ValueError('STALE_OR_FUTURE_COLLECTION_RECEIPT')
    if source_health['end'] != (now.tz_convert('Asia/Seoul').normalize()-pd.Timedelta(days=1)).strftime('%Y-%m-%d'):
        raise ValueError('COLLECTION_END_NOT_PREVIOUS_DAY')
    g = frame.copy()
    g['trading_date'] = pd.to_datetime(g.trading_date)
    keys = ['trading_date','asset_id']
    if g[keys].isna().any().any() or g.duplicated(keys).any() or g.empty:
        raise ValueError('INVALID_GOLD_KEYS')
    expected = set(source_health['expected_assets'])
    if len(expected) != 20 or not set(g.asset_id).issubset(expected):
        raise ValueError('GOLD_ASSET_UNIVERSE_MISMATCH')
    target = pd.Timestamp(source_health['expected_latest'])
    if g.trading_date.max() != target:
        raise ValueError('GOLD_LATEST_DATE_MISMATCH')
    required = ['close','volume','kospi_close','usdkrw','us_treasury_10y','wti','vix']
    numeric = g[required].apply(pd.to_numeric, errors='coerce')
    finite = pd.Series(np.isfinite(numeric.to_numpy(dtype=float)).all(axis=1), index=g.index)
    positive = numeric[['close','volume','kospi_close','usdkrw']].gt(0).all(axis=1) & numeric.vix.ge(0)
    eligible = (finite & positive & g.quality_status.eq('valid') & g.price_basis.eq('adjusted')
                & g.adjustment_version.notna() & g.is_mock.eq(False))
    for name in ['usdkrw','us_treasury_10y','wti','vix']:
        observed = pd.to_datetime(g[name+'_observation_date'])
        age = (g.trading_date-observed).dt.days
        eligible &= observed.notna() & age.between(1,7)
    # 전체 거래일을 보존하며, 후속 피처 계산에서 거래일 이동 후 이 마스크를 적용합니다.
    eligibility = g[keys].copy()
    eligibility['input_eligible'] = eligible
    eligibility['reason'] = np.where(eligible, 'ready', np.where(~finite, 'required_value_missing_or_nonfinite',
                              np.where(~positive,'invalid_price_volume_or_factor','quality_or_observation_date')))
    for day in source_health['expected_sessions']:
        rows = g[g.trading_date.eq(pd.Timestamp(day))]
        if set(rows.asset_id) != expected or len(rows) != 20:
            raise ValueError('GOLD_INCOMPLETE_SESSION:' + day)
    latest = g.trading_date.eq(target)
    if not eligible[latest].all():
        bad = eligibility[latest & ~eligible][['asset_id','reason']].to_dict('records')
        raise ValueError('LATEST_GOLD_NOT_READY:' + json.dumps(bad))
    return eligibility

# 민철 2026-11-09 추가 (수집 모듈을 읽을 때 달력을 로드하던 방식에서 실제 수집 시점에 로드하는 방식으로 바꾸어 로컬 검증과 Fabric 실행에 같은 코드를 사용함).
def expected_krx_sessions(start,end):
    # 민철 2026-11-09 추가 (요일만 추정하는 방식에서 버전과 해시가 고정된 KRX 거래일 달력 검사로 바꾸어 휴장과 수집 누락을 구분함).
    import sys, zipfile, tempfile
    _calendar_zip=Path(os.environ.get('STRESS_KRX_CALENDAR_ARCHIVE','/lakehouse/default/Files/reference/ingestion_calendar/4.13.2/calendar_4_13_2.zip'))
    if hashlib.sha256(_calendar_zip.read_bytes()).hexdigest() != '77022bb05b2b5332f773a4ab319c08824d5e0a44ac9f9bcf622df53d295d4e07':
        raise RuntimeError('CALENDAR_ARCHIVE_HASH_MISMATCH')
    _calendar_dir=Path(tempfile.gettempdir())/'stress_calendar_77022bb05b2b'
    if not (_calendar_dir/'exchange_calendars/__init__.py').exists():
        with zipfile.ZipFile(_calendar_zip) as _z:_z.extractall(_calendar_dir)
    sys.path.insert(0,str(_calendar_dir))
    import exchange_calendars as _xc
    if _xc.__version__ != '4.13.2':raise RuntimeError('CALENDAR_VERSION_MISMATCH')
    return _xc.get_calendar('XKRX',start=pd.Timestamp(start)-pd.Timedelta(days=10),end=pd.Timestamp(end)+pd.Timedelta(days=10)).sessions_in_range(start,end).strftime('%Y%m%d').tolist()

SERIES={'usdkrw':'DEXKOUS','us_treasury_10y':'DGS10','wti':'DCOILWTICO','vix':'VIXCLS'}

def save(path,obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf8')

def run_api_batch(root,assets,secrets,start='',end=''):
    for key in ['KRX_API_KEY','ECOS_API_KEY','FRED_API_KEY']:
        if not secrets.get(key):raise RuntimeError('Missing '+key)
    if len(set(assets))!=20:raise ValueError('Expected 20 securities')
    end=end or (pd.Timestamp.now(tz='Asia/Seoul')-pd.Timedelta(days=1)).strftime('%Y%m%d')
    # 민철 2026-11-09 수정 (고정 7일 조회에서 최근 성공 수집일과 7일 중복 조회로 바꾸어 중단 기간의 누락을 자동 재수집함).
    root=Path(root)
    if not start:
        start=(pd.Timestamp(end)-pd.Timedelta(days=7)).strftime('%Y%m%d')
        previous=root/'_quality/latest.json'
        if previous.exists():
            prior=json.loads(previous.read_text(encoding='utf8'))
            watermark=prior.get('last_successful_end')
            if watermark:start=min(start,(pd.Timestamp(watermark)-pd.Timedelta(days=7)).strftime('%Y%m%d'))
    macro_start=min(start,(pd.Timestamp(end)-pd.Timedelta(days=35)).strftime('%Y%m%d'))
    sessions=expected_krx_sessions(start,end)
    if not sessions:raise ValueError('NO_SESSIONS_IN_COLLECTION_WINDOW')
    if start<'20100101' or start>end:raise ValueError('API range must start in 2010 or later; import older archive separately')
    # 민철 2026-11-09 수정 (같은 기간의 SUCCESS 캐시 재사용에서 실행별 원본 보존으로 바꾸어 빈 응답과 발표 지연 자료를 다시 받도록 함).
    nonce=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')
    version=hashlib.sha256(json.dumps([sorted(assets),start,end,nonce,'bronze-v3']).encode()).hexdigest()[:12]
    batch_id=f'{start}_{end}_{version}';folder=root/'_runs'/batch_id;files=[]
    done=folder/'SUCCESS.json';macro_rows={}
    health_path=root/'_quality/latest.json'
    last_successful_end=None
    if health_path.exists():last_successful_end=json.loads(health_path.read_text(encoding='utf8')).get('last_successful_end')
    gold_health=root.parent/'gold_evidence/gold_stock_market_daily_v11/health.json'
    operational=end==(pd.Timestamp.now(tz='Asia/Seoul')-pd.Timedelta(days=1)).strftime('%Y%m%d')
    if operational:write_quality_json(gold_health,{'status':'building','training_ready':False,'batch_id':batch_id,'checked_at_utc':datetime.now(timezone.utc).isoformat()})
    session=requests.Session()
    def get(url,**kwargs):
        for attempt in range(3):
            try:
                time.sleep(1.05);r=session.get(url,timeout=40,**kwargs);r.raise_for_status();return r.json()
            except Exception:
                if attempt==2:raise RuntimeError('Provider request failed') from None
                time.sleep(2)
    def part(source,name,fetch):
        provider='krx' if source.startswith('krx_') else source
        dataset=source.removeprefix('krx_') if provider=='krx' else 'observations'
        path=root/provider/'api'/batch_id/dataset/(name+'.json')
        if path.exists():envelope=json.loads(path.read_text(encoding='utf8'))
        else:
            rows=fetch()
            if not isinstance(rows,list):raise ValueError('Unexpected response')
            envelope={'source':source,'rows':rows,'retrieved_at':datetime.now(timezone.utc).isoformat(),
                'available_at':None,'price_basis':'unadjusted' if source=='krx_stocks' else None,'is_mock':False}
            save(path,envelope)
        files.append({'file':str(path.relative_to(root)),'rows':len(envelope['rows']),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
        save(folder/'progress.json',{'status':'collecting','completed':len(files),'last':str(path.relative_to(root))})
        return envelope['rows']
    try:
        stock_rows=[];index_rows=[]
        for date in pd.date_range(start,end):
            day=date.strftime('%Y%m%d')
            for name,endpoint in [('krx_stocks','sto/stk_bydd_trd'),('krx_index','idx/kospi_dd_trd')]:
                def pull(endpoint=endpoint,day=day):
                    rows=get('https://data-dbg.krx.co.kr/svc/apis/'+endpoint,headers={'AUTH_KEY':secrets['KRX_API_KEY']},params={'basDd':day})['OutBlock_1']
                    if any(r['BAS_DD']!=day for r in rows):raise ValueError('Incorrect KRX date')
                    return rows
                rows=part(name,day,pull)
                if name=='krx_stocks':stock_rows.extend(rows)
                else:index_rows.extend(rows)
        selected=[r for r in stock_rows if r.get('ISU_CD') in assets or r.get('ISU_SRT_CD') in assets]
        # KRX stock API uses six-character ISU_CD; do not infer missing mappings.
        if stock_rows and not selected:raise ValueError('No requested stock codes matched API')
        def ecos():
            rows=[];offset=1
            while True:
                j=get(f"https://ecos.bok.or.kr/api/StatisticSearch/{secrets['ECOS_API_KEY']}/json/kr/{offset}/{offset+999}/817Y002/D/{macro_start}/{end}/010200000")
                if 'StatisticSearch' not in j:
                    if j.get('RESULT',{}).get('CODE')=='INFO-200':return rows
                    raise ValueError('ECOS rejected request')
                obj=j['StatisticSearch'];rows+=obj['row']
                if len(rows)>=int(obj['list_total_count']):return rows
                if not obj['row']:raise ValueError('Incomplete ECOS pagination')
                offset+=1000
        macro_rows['korea_3y']=part('ecos','kr3y',ecos)
        for key,series in SERIES.items():
            def fred(series=series):
                rows=[];offset=0
                while True:
                    j=get('https://api.stlouisfed.org/fred/series/observations',params={'api_key':secrets['FRED_API_KEY'],
                        'file_type':'json','series_id':series,'observation_start':str(pd.Timestamp(macro_start).date()),
                        'observation_end':str(pd.Timestamp(end).date()),'limit':10000,'offset':offset})
                    page=j['observations'];rows+=page
                    if len(rows)>=int(j['count']):return rows
                    if not page:raise ValueError('Incomplete FRED pagination')
                    offset+=len(page)
            macro_rows[key]=part('fred',key,fred)
        health=validate_source_batch(stock_rows,index_rows,macro_rows,assets,sessions,end)
        observed=sorted({r.get('ISU_CD',r.get('ISU_SRT_CD')) for r in selected})
        result={'status':'complete' if selected and index_rows else 'no_market_observations','start':start,'end':end,'files':files,
            'batch_id':batch_id,'requested_assets':assets,'observed_assets':observed,'selected_rows':len(selected),
            'missing_assets':sorted(set(assets)-set(observed)),'price_basis':'unadjusted',
            'gold_published':False,'merge_with_adjusted_history_allowed':False,'is_mock':False}
        # 민철 2026-11-09 추가 (전체 기간 합계만 검사하던 방식에서 거래일별 20종목과 다섯 거시 원본 검사로 바꾸어 완전한 수집만 승인함).
        result['quality']=health
        save(done,result)
        health.update(batch_id=batch_id,checked_at_utc=datetime.now(timezone.utc).isoformat(),
                      last_successful_end=pd.Timestamp(end).strftime('%Y-%m-%d'),
                      manifest=str(done.relative_to(root)),manifest_sha256=hashlib.sha256(done.read_bytes()).hexdigest())
        write_quality_json(folder/'quality.json',health)
        if operational:write_quality_json(health_path,health)
        return result
    except Exception as exc:
        save(folder/'progress.json',{'status':'failed','completed':len(files),'error_type':type(exc).__name__})
        failure={'status':'blocked','training_ready':False,'batch_id':batch_id,'checked_at_utc':datetime.now(timezone.utc).isoformat(),
                 'last_successful_end':last_successful_end,'error_type':type(exc).__name__,
                 'reason':str(exc) if isinstance(exc,ValueError) else 'PROVIDER_OR_STORAGE_FAILURE'}
        write_quality_json(folder/'quality.json',failure)
        if operational:
            write_quality_json(health_path,failure);write_quality_json(gold_health,failure)
        raise RuntimeError('API batch failed; inspect sanitized quality.json') from None


# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************

import notebookutils
assert Path("/lakehouse/default/Files").is_dir(), "기본 Lakehouse lh_whatif를 연결하세요."
vault = "https://kv-whatif-dev-5dt.vault.azure.net/"
secrets = {k: notebookutils.credentials.getSecret(vault, name) for k, name in {'KRX_API_KEY': 'krx-api-key', 'ECOS_API_KEY': 'ecos-api-key', 'FRED_API_KEY': 'fred-api-key'}.items()}
assets = ['005930', '000660', '005935', '402340', '009150', '373220', '207940', '005380', '105560', '032830', '028260', '068270', '006400', '055550', '000270', '034730', '012450', '034020', '086790', '012330']
summary = run_api_batch("/lakehouse/default/Files/bronze", assets, secrets, start_date, end_date)
print(json.dumps({k: summary[k] for k in ["status", "start", "end", "selected_rows", "missing_assets", "is_mock"]}, ensure_ascii=False))
# 2026-11-10 16:55 KST 민철 추가: 한국은행 공식 RSS의 실제 공표 시각을 원문 번호·날짜·금리값과 대조해 자동 연결합니다. 예정 시각으로 채우지 않습니다.
# 2026-11-10 17:03 KST 민철 수정: Fabric에 없는 HTML 라이브러리 의존성을 제거한 v3 수집 코드를 사용합니다.
import sys as _publication_sys
_publication_sys.path.insert(0, '/lakehouse/default/Files/reference/publication_evidence/v3')
from publication_evidence import collect as collect_publication_evidence
publication_summary=collect_publication_evidence('/lakehouse/default/Files/bronze',secrets['FRED_API_KEY'])
print(json.dumps(publication_summary,ensure_ascii=False))
# 날짜만 있는 근거는 별도 known_by로 기록합니다. Gold 공표 시각에 넣지 않습니다.



# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }
