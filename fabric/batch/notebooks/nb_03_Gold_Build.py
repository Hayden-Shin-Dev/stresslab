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
# META       "default_lakehouse_workspace_id": "2c303c0d-6c10-4988-91cb-856fe5f56071",
# META       "known_lakehouses": [
# META         {
# META           "id": "93432592-8620-411e-808f-b91678bf78d2"
# META         }
# META       ]
# META     }
# META   }
# META }

# MARKDOWN ********************

# 2026-11-09 12:50 KST 민철 수정: 가격 검증/결측 복구/시점 근거 연결. 변경 위치에 설명을 남겼습니다.
# 기존 Gold 34컬럼과 ML 계산 로직은 유지하며, 입력 테이블명만 변경합니다.
# 민철 2026-11-09 수정 (출력 테이블명 gold_stock_market_daily_v11에서 gold_stress_daily로 바꾸어 실시간과 ML 입력 이름을 통일함).
# 민철 2026-11-09 삭제 (구 Gold 테이블 두 개를 독립 백업 및 전체 값 대조 후 삭제하는 방식으로 바꾸어 운영 Gold를 하나로 정리함).
# 민철 2026-11-09 삭제 (이름 통합용 임시 백업 및 삭제 셀에서 실행 완료 후 제거하는 방식으로 바꾸어 정기 실행 시 삭제 코드가 재실행되지 않도록 함).
# 복구 근거: Files/_archive/gold_name_20261109_v161/receipt.json


# CELL ********************

# ==================================================
# MS_P3 | GOLD v1.1
# Silver 7개 → Gold 34개 컬럼
# 외부 API 호출 없음
# ==================================================

from pyspark.sql import functions as F
from pyspark.sql.window import Window

spark.conf.set("spark.sql.session.timeZone", "UTC")

# 민철 2026-11-09 수정 (Gold 출력 테이블을 gold_stock_market_daily_v11에서 gold_stress_daily로 바꾸어 실시간 및 ML 전달 계약의 이름을 통일함).
TARGET = "gold_stress_daily"
VERSION = "ms_p3_gold_v1.1"
# 민철 2026-11-09 수정 (공표 주기 선택 설명에서 Silver 관측일 기준 7일 선택 설명으로 바꾸어 아래 macro_asof의 처리와 일치시킴).
# 민철 2026-11-09 삭제 (공표시점 선택의 전역 10일 제한에서 macro_asof의 관측일 7일 제한으로 바꾸어 중복 기준을 제거함).

# 1. 필요한 Silver 테이블
MACROS = [
    ("usdkrw", "silver_usdkrw_daily"),
    ("us_treasury_10y", "silver_us_treasury_10y_daily"),
    ("wti", "silver_wti_daily"),
    ("vix", "silver_vix_daily"),
    ("korea_3y", "silver_korea_3y_daily"),
]

required_tables = [
    "silver_stock_daily",
    "silver_kospi_daily"
] + [table for _, table in MACROS]

missing = [
    t for t in required_tables
    if not spark.catalog.tableExists(t)
]

if missing:
    raise RuntimeError(f"Silver 테이블 누락: {missing}")

print("Silver 7개 테이블 확인 완료")

# 2. 주식 데이터를 Gold의 기준 행으로 사용
s = spark.table("silver_stock_daily")

stocks = s.select(
    F.col("trading_date").cast("date").alias("trading_date"),
    F.col("asset_id").cast("string").alias("asset_id"),
    F.col("sector_id").cast("string").alias("sector_id"),

    F.coalesce(
        F.col("instrument_kind"),
        F.lit("stock")
    ).alias("instrument_kind"),

    F.col("close").cast("double").alias("close"),
    F.col("volume").cast("long").alias("volume"),

    # 가격 조정 기준: 아래 Silver 검증 결과를 사용합니다.
    # 2026-11-09 12:50 KST 민철 수정 — Silver에서 검증한 수정주가 기준을 그대로 전달합니다.
    F.col("price_basis").cast("string").alias("price_basis"),

    F.col("adjustment_version")
        .cast("string")
        .alias("adjustment_version"),

    F.col("price_available_at")
        .cast("timestamp")
        .alias("price_available_at"),

    F.col("source_ref").cast("string").alias("source_ref"),
    F.lit(VERSION).alias("dataset_version"),

    F.col("quality_status")
        .cast("string")
        .alias("quality_status"),

    F.coalesce(
        F.col("is_mock").cast("boolean"),
        F.lit(False)
    ).alias("is_mock")
)

# 거시지표 결합은 종목별이 아니라 날짜별로 수행
dates = stocks.select("trading_date").distinct()

# 3. KOSPI — 동일 거래일 기준
kospi = (
    spark.table("silver_kospi_daily")
    .select(
        F.col("observation_date")
            .cast("date")
            .alias("trading_date"),

        F.col("kospi_close")
            .cast("double")
            .alias("kospi_close")
    )
)


# 민철 2026-11-09 수정 (별도 시점 파일의 값을 Gold로 복사하던 방식에서 기존 Silver 관측값을 직접 날짜 정렬하는 방식으로 바꾸어 검증한 ML의 입력 의미를 유지함).
from pathlib import Path
import pandas as pd
import numpy as np
import json,hashlib
from pyspark.sql import types as T
_provenance_path=Path('/lakehouse/default/Files/silver_evidence/observation_provenance.parquet')
_availability_p=pd.read_parquet(_provenance_path)
_availability_p['observation_date']=pd.to_datetime(_availability_p.observation_date).astype('datetime64[ns]')
_availability_p['known_by']=pd.to_datetime(_availability_p.known_by,utc=True)
_evidence=_availability_p[_availability_p.verified & _availability_p.value.notna()].sort_values('known_by').drop_duplicates(['source','observation_date','value'])
# 민철 2026-11-09 추가 (공표시각 가정과 실제 수신 근거를 혼용하던 방식에서 별도 필드로 연결하는 방식으로 바꾸어 관측일을 이용 가능 시각으로 오인하지 않도록 함).
_clock_root=Path('/lakehouse/default/Files/gold/gold_stress_daily_reconciled_v142_20261105')
_clock_manifest=json.loads((_clock_root/'canonical_manifest.json').read_text(encoding='utf8'))
_clock_bytes=(_clock_root/'factor_observations.parquet').read_bytes()
if hashlib.sha256(_clock_bytes).hexdigest()!=_clock_manifest['files']['factor_observations.parquet']:raise RuntimeError('원본 시점 자료 해시 불일치')
_clock=pd.read_parquet(_clock_root/'factor_observations.parquet')
_clock['observation_date']=pd.to_datetime(_clock.observation_date).astype('datetime64[ns]')
_dates=pd.DataFrame({'trading_date':sorted(r[0] for r in dates.collect())})
_dates.trading_date=pd.to_datetime(_dates.trading_date).astype('datetime64[ns]')
_selected_provenance=[]
# 2026-11-10 16:55 KST 민철 추가: 한국은행 공식 RSS의 실제 공표 시각을 원문 번호·날짜·금리값과 대조해 자동 연결합니다. 예정 시각으로 채우지 않습니다.
# 2026-11-10 17:03 KST 민철 수정: Fabric에 없는 HTML 라이브러리 의존성을 제거한 v3 수집 코드를 사용합니다.
import sys as _publication_sys
_publication_sys.path.insert(0, '/lakehouse/default/Files/reference/publication_evidence/v3')
from publication_evidence import select_evidence,exact_publication_for_values,fx_observed_at
_official_ledger=pd.read_parquet('/lakehouse/default/Files/silver_evidence/official_publication_events.parquet')
_official_ledger.observation_date=pd.to_datetime(_official_ledger.observation_date).astype('datetime64[ns]')
for _col in ['known_by','valid_until','publication_at']:_official_ledger[_col]=pd.to_datetime(_official_ledger[_col],utc=True)
_fxmeta=json.loads(Path('/lakehouse/default/Files/silver_evidence/fx_observation_definition.json').read_text(encoding='utf8'))

# 민철 2026-11-09 추가 (최근 관측의 수신시각 누락에서 Silver가 기록한 실제 수신/저장 근거 연결로 바꾸어 새 자료도 이용 가능 시점을 보존함).
_receipts=pd.read_parquet('/lakehouse/default/Files/silver_evidence/actual_receipt_events.parquet')
_receipts['observation_date']=pd.to_datetime(_receipts.observation_date).astype('datetime64[ns]')
_receipts['known_by']=pd.to_datetime(_receipts.known_by,utc=True)
_receipts=_receipts.sort_values('known_by').drop_duplicates(['source','observation_date','value'])
from pandas.tseries.holiday import USFederalHolidayCalendar
_holidays=set(USFederalHolidayCalendar().holidays('1980-01-01',str(_dates.trading_date.max().year+2)+'-12-31'))
def _research_clock(name,day):
    if pd.isna(day) or name=='korea_3y':return pd.NaT
    if name=='usdkrw':rd=day+pd.Timedelta(days=7-day.weekday());hour=18
    elif name=='wti':rd=day+pd.Timedelta(days=(2-day.weekday())%7 or 7);hour=18
    else:rd=day+pd.Timedelta(days=1);hour=18 if name=='us_treasury_10y' else 14
    while rd.weekday()>=5 or rd in _holidays:rd+=pd.Timedelta(days=1)
    return (rd+pd.Timedelta(hours=hour)).tz_localize('America/New_York').tz_convert('UTC')

def macro_asof(prefix, table):
    # 민철 2026-11-09 수정 (table 인자를 사용하지 않던 방식에서 Silver 정상 관측을 거래일 이전 최대 7일로 연결하는 방식으로 바꾸어 휴일 결측과 발표 지연을 분리함).
    raw=spark.table(table).select('observation_date','value','quality_status','source_ref').toPandas()
    raw.observation_date=pd.to_datetime(raw.observation_date).astype('datetime64[ns]')
    if raw.observation_date.duplicated().any():raise RuntimeError('Silver 관측키 중복: '+prefix)
    raw=raw[raw.quality_status.eq('valid') & raw.value.notna() & np.isfinite(raw.value)].sort_values('observation_date')
    q=pd.merge_asof(_dates,raw,left_on='trading_date',right_on='observation_date',allow_exact_matches=False)
    stale=(q.trading_date-q.observation_date).dt.days.gt(7)
    q.loc[stale,['value','observation_date']]=[np.nan,pd.NaT]
    clocks=_clock[_clock.field.eq(prefix)][['observation_date','value','verified_usable_by','policy_available_at']].rename(columns={'verified_usable_by':'receipt_upper_bound','policy_available_at':'research_policy_available_at'})
    q=q.merge(clocks,on=['observation_date','value'],how='left',validate='many_to_one')
    recent=_receipts[_receipts.source.eq(prefix)][['observation_date','value','known_by']].rename(columns={'known_by':'actual_receipt_upper_bound'})
    q=q.merge(recent,on=['observation_date','value'],how='left',validate='many_to_one')
    q['receipt_upper_bound']=pd.to_datetime(q.receipt_upper_bound,utc=True).fillna(pd.to_datetime(q.actual_receipt_upper_bound,utc=True))
    q['research_policy_available_at']=pd.to_datetime(q.research_policy_available_at,utc=True)
    missing_policy=q.value.notna() & q.research_policy_available_at.isna()
    if prefix!='korea_3y':q.loc[missing_policy,'research_policy_available_at']=pd.to_datetime(q.loc[missing_policy,'observation_date'].map(lambda d:_research_clock(prefix,d)),utc=True)
    evidence=_evidence[_evidence.source.eq(prefix)][['observation_date','value','known_by','availability_basis']]
    q=q.merge(evidence,on=['observation_date','value'],how='left',validate='many_to_one')
    q['receipt_upper_bound']=pd.to_datetime(q.receipt_upper_bound,utc=True)
    q['known_by']=pd.to_datetime(q.known_by,utc=True)
    # 2026-11-10 16:40 KST 민철 수정: 날짜/값/빈티지 유효기간이 맞는 공식 근거만 연결합니다.
    _matched=select_evidence(q,_official_ledger,prefix)
    _covered=pd.MultiIndex.from_frame(q[['observation_date','value']]).isin(pd.MultiIndex.from_frame(_official_ledger[_official_ledger.source.eq(prefix)][['observation_date','value']]))
    q.loc[_covered,'known_by']=pd.NaT
    q.loc[_covered,'availability_basis']='unverified_for_cutoff'
    for _col in ['known_by','availability_basis']:
        _ok=_matched.known_by.notna()
        q.loc[_ok,_col]=_matched.loc[_ok,_col].values
    q['known_by']=pd.to_datetime(q.known_by,utc=True)
    q['publication_at']=exact_publication_for_values(q,_official_ledger,prefix)
    q['observed_at']=fx_observed_at(q.observation_date,_fxmeta) if prefix=='usdkrw' else pd.NaT
    q['official_source_ref']=_matched.source_ref
    q['official_evidence_sha256']=_matched.evidence_sha256
    q['known_by']=q.known_by.fillna(q.receipt_upper_bound)
    q['availability_basis']=q.availability_basis.fillna('recorded_retrieval_upper_bound')
    q.loc[q.known_by.isna(),'availability_basis']='unverified'
    # 원본 값이 있어도 당시 이용 가능 근거가 없으면 verified=False. 가상 충격용 값 자체를 NULL로 바꾸지는 않습니다.
    cutoff=pd.to_datetime(q.trading_date,utc=True)+pd.Timedelta(hours=6,minutes=30)
    q['verified']=q.value.notna() & q.known_by.notna() & q.known_by.le(cutoff)
    # 2026-11-10 16:40 KST 민철 추가: 미확인 시각과 실제 공개 지연을 구분합니다.
    _first=_official_ledger[_official_ledger.source.eq(prefix)].groupby(['observation_date','value'],as_index=False).known_by.min().rename(columns={'known_by':'first_official_known_by'})
    _clockcheck=q[['observation_date','value']].merge(_first,on=['observation_date','value'],how='left',validate='many_to_one')
    q['timing_status']='no_publication_evidence'
    q.loc[_covered,'timing_status']='no_valid_vintage_at_cutoff'
    q.loc[_clockcheck.first_official_known_by.gt(cutoff),'timing_status']='official_availability_after_cutoff'
    q.loc[q.verified,'timing_status']='verified_upper_bound_not_exact_publication'
    q.loc[q.publication_at.notna() & q.publication_at.le(cutoff),'timing_status']='verified_official_notice'
    q.loc[q.value.isna(),'timing_status']='missing_value'
    q['source_value_verified']=q.value.notna()
    q['source']=prefix;q['date']=q.trading_date
    _selected_provenance.append(q[['date','source','value','observation_date','known_by','availability_basis','verified','source_value_verified','receipt_upper_bound','research_policy_available_at','source_ref','publication_at','observed_at','official_source_ref','official_evidence_sha256','timing_status']])
    # 정확한 시각 칸에는 확인한 공개 알림/공식 관측 정의만 사용합니다. known_by는 별도 근거 파일에 보존합니다.
    def _utc_naive(x):return None if pd.isna(x) else x.tz_convert('UTC').tz_localize(None).to_pydatetime()
    rows=[(r.trading_date.date(),None if pd.isna(r.value) else float(r.value),None if pd.isna(r.observation_date) else r.observation_date.date(),_utc_naive(r.publication_at),_utc_naive(r.observed_at)) for r in q.itertuples()]
    schema=T.StructType([T.StructField('trading_date',T.DateType()),T.StructField(prefix,T.DoubleType()),T.StructField(prefix+'_observation_date',T.DateType()),T.StructField(prefix+'_available_at',T.TimestampType()),T.StructField(prefix+'_observed_at',T.TimestampType())])
    return spark.createDataFrame(rows,schema)


# 5. 다섯 거시지표를 날짜 기준으로 결합
macro_dates = dates

for prefix, table in MACROS:
    macro_dates = macro_dates.join(
        macro_asof(prefix, table),
        on="trading_date",
        how="left"
    )

# 민철 2026-11-09 추가 (다른 관측값의 시점 파일에서 실제 Gold 선택 관측의 근거로 바꾸어 값과 시점의 대응을 유지함).
_p=pd.concat(_selected_provenance,ignore_index=True)

# 6. 종목별 관측값 + KOSPI + 거시지표 결합
gold = (
    stocks
    .join(kospi, on="trading_date", how="left")
    .join(macro_dates, on="trading_date", how="left")
)

# 7. Gold 34개 컬럼 및 자료형 확정
SCHEMA = [
    ("trading_date", "date"),
    ("asset_id", "string"),
    ("sector_id", "string"),
    ("instrument_kind", "string"),
    ("close", "double"),
    ("volume", "long"),
    ("price_basis", "string"),
    ("adjustment_version", "string"),

    ("kospi_close", "double"),
    ("usdkrw", "double"),
    ("us_treasury_10y", "double"),
    ("wti", "double"),
    ("vix", "double"),

    ("price_available_at", "timestamp"),
    ("source_ref", "string"),
    ("dataset_version", "string"),
    ("quality_status", "string"),
    ("is_mock", "boolean"),

    ("usdkrw_observation_date", "date"),
    ("usdkrw_observed_at", "timestamp"),
    ("usdkrw_available_at", "timestamp"),

    ("us_treasury_10y_observation_date", "date"),
    ("us_treasury_10y_observed_at", "timestamp"),
    ("us_treasury_10y_available_at", "timestamp"),

    ("wti_observation_date", "date"),
    ("wti_observed_at", "timestamp"),
    ("wti_available_at", "timestamp"),

    ("vix_observation_date", "date"),
    ("vix_observed_at", "timestamp"),
    ("vix_available_at", "timestamp"),

    ("korea_3y", "double"),
    ("korea_3y_observation_date", "date"),
    ("korea_3y_observed_at", "timestamp"),
    ("korea_3y_available_at", "timestamp"),
]

assert len(SCHEMA) == 34

gold = gold.select(*[
    F.col(name).cast(dtype).alias(name)
    for name, dtype in SCHEMA
])

# 8. 저장 전 핵심 검증
gold = gold.cache()

source_count = stocks.count()

stats = gold.agg(
    F.count("*").alias("rows"),
    F.countDistinct(
        F.struct(
            "dataset_version",
            "trading_date",
            "asset_id"
        )
    ).alias("unique_keys"),

    F.sum(
        F.when(
            F.col("trading_date").isNull()
            | F.col("asset_id").isNull(),
            1
        ).otherwise(0)
    ).alias("null_keys"),

    F.max("trading_date").alias("latest_date")
).first()

if (
    stats["rows"] != source_count
    or stats["rows"] != stats["unique_keys"]
    or stats["null_keys"] != 0
):
    gold.unpersist()
    raise RuntimeError(
        "Gold 행 수 또는 기본키 검증 실패. 저장 중단."
    )

print("Silver 주식 행:", source_count)
print("Gold 생성 행:", stats["rows"])
print("Gold 최신 거래일:", stats["latest_date"])
print("Gold 컬럼 수:", len(gold.columns))

# 2026-11-09 12:50 KST 민철 추가 — Gold의 값과 공표 근거 일치 및 학습 가능 날짜를 저장 전에 확인합니다.

# 2026-11-09 13:08 KST 민철 추가 — ML 어댑터와 같은 가격 검사를 저장 전에 실행합니다. 실패하면 기존 Gold를 유지합니다.
def require_verified_price_basis(frame):
    verified=frame.price_basis.eq('adjusted') & frame.adjustment_version.notna()
    if not verified.all():
        raise RuntimeError('수정주가 연결 미확인 행이 있습니다. Silver의 price_validation.json을 확인하세요. 기존 Gold는 유지합니다.')

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

_gp=gold.toPandas();_gp['trading_date']=pd.to_datetime(_gp.trading_date)
require_verified_price_basis(_gp)
_eligible=_gp.quality_status.eq('valid') & _gp.price_basis.eq('adjusted') & _gp.adjustment_version.notna() & _gp.close.gt(0) & _gp.volume.gt(0)
for _name,_table in MACROS:
    _q=_p[_p.source.eq(_name)].set_index('date')
    _expected=_gp.trading_date.map(_q.value)
    if not __import__('numpy').allclose(_gp[_name],_expected,equal_nan=True):raise RuntimeError('Gold 거시 근거 불일치: '+_name)
    # 민철 2026-11-09 수정 (다섯 지표의 과거 이용 가능 여부 일괄 필터에서 모델의 네 충격 입력 결측 검사로 바꾸어 가상 충격 계산 가능 여부를 구분함).
    if _name in ['usdkrw','us_treasury_10y','wti','vix']:_eligible &= _gp[_name].notna()
if not _eligible.any():raise RuntimeError('가상 충격 계산에 사용 가능한 Gold 행이 없습니다')
_latest_eligible=_gp.loc[_eligible,'trading_date'].max()
print('Gold 최신일:',_gp.trading_date.max(),'ML 입력 가능 최신일:',_latest_eligible,'제외 행:',int((~_eligible).sum()))

# 민철 2026-11-09 추가 (과거 정상 행이 하나면 저장하던 방식에서 최신 거래일 20종목 전체 및 필수값 검사로 바꾸어 결측과 누락 게시를 차단함).
_health_path=Path('/lakehouse/default/Files/gold_evidence/gold_stock_market_daily_v11/health.json')
try:
    _source_health=json.loads(Path('/lakehouse/default/Files/bronze/_quality/latest.json').read_text(encoding='utf8'))
    _manifest_path=Path('/lakehouse/default/Files/bronze')/_source_health['manifest']
    if hashlib.sha256(_manifest_path.read_bytes()).hexdigest()!=_source_health['manifest_sha256']:raise ValueError('BRONZE_MANIFEST_HASH_MISMATCH')
    _eligibility=validate_gold_ready(_gp,_source_health)
    _eligible=_eligibility.input_eligible
    _latest_eligible=_gp.loc[_eligible,'trading_date'].max()
    # 전체 거래일을 남겨 1일/5일 수익률 계산 간격을 보존하고, 부적합 행만 표시합니다.
    _gp.loc[~_eligible,'quality_status']='quarantined'
    _flags=spark.createDataFrame([(r.trading_date.date(),r.asset_id,bool(r.input_eligible)) for r in _eligibility.itertuples()],
        'trading_date date, asset_id string, _input_ready boolean')
    _columns=gold.columns
    gold=gold.join(_flags,['trading_date','asset_id'],'left').withColumn('quality_status',F.when(F.col('_input_ready'),F.col('quality_status')).otherwise(F.lit('quarantined'))).select(*_columns)
    write_quality_json(_health_path,{'status':'publishing','training_ready':False,'checked_at_utc':pd.Timestamp.now(tz='UTC').isoformat(),'source_batch_id':_source_health['batch_id']})
except Exception as _exc:
    write_quality_json(_health_path,{'status':'blocked','training_ready':False,'checked_at_utc':pd.Timestamp.now(tz='UTC').isoformat(),'reason':str(_exc)})
    raise
# Gold 테이블 저장은 아래 스냅샷 준비와 검증을 마친 후 실행합니다.
gold.unpersist()

print(f"Gold 게시 전 검사 완료: {TARGET}")

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************

# 민철 2026-11-09 수정 (게시 전 이전 테이블 조회에서 검증된 현재 gold DataFrame 조회로 바꾸어 최초 생성 시 테이블 미존재 오류와 이전 배치 표시를 방지함).
df = gold.limit(10)
display(df)

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************

# 2026-11-09 12:50 KST 민철 추가 — ML이 기존 로컬 어댑터로 읽을 수 있는 Gold 스냅샷과 근거 해시를 함께 게시합니다.

import json,hashlib
from datetime import datetime,timezone
_version=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
# 민철 2026-11-09 추가 (테이블명과 근거 경로를 함께 변경하는 방식에서 기존 근거 경로를 유지하는 방식으로 바꾸어 수집 health와 ML 스냅샷 연결을 보존함).
_base=Path('/lakehouse/default/Files/gold_evidence/gold_stock_market_daily_v11')
_run=_base/_version;_run.mkdir(parents=True,exist_ok=False)
_gp.to_parquet(_run/'gold.parquet',index=False);_p.to_parquet(_run/'provenance.parquet',index=False)
# 민철 2026-11-09 추가 (제외 건수만 저장하던 방식에서 행별 사용 가능 여부와 이유 저장으로 바꾸어 ML이 결측 행을 구분하도록 함).
_eligibility.to_parquet(_run/'input_eligibility.parquet',index=False)
# 민철 2026-11-09 추가 (기존 공표 근거 대체에서 원본 근거도 함께 보존하는 방식으로 바꾸어 시점 가정 변경 이력을 유지함).
_availability_p.to_parquet(_run/'availability_provenance.parquet',index=False)
_cert={'gold_sha256':hashlib.sha256((_run/'gold.parquet').read_bytes()).hexdigest(),
       'provenance_sha256':hashlib.sha256((_run/'provenance.parquet').read_bytes()).hexdigest(),
       'exact_publication_clocks':False,'availability_policy':'Previous non-null Silver observation strictly before trading date; maximum 7 calendar days; receipt upper bounds and research policy stored separately',
       'latest_gold_date':str(_gp.trading_date.max().date()),'latest_eligible_date':str(_latest_eligible.date()),
       'eligible_rows':int(_eligible.sum()),'excluded_rows':int((~_eligible).sum()),'schema_changed':False,
       'input_mode':'hypothetical_scenario','strict_historical_point_in_time_verified':False,
       'available_at_meaning':'official recorded availability notice time only; receipt and date upper bounds are in provenance', 'observed_at_meaning':'source-defined observation clock where verified; otherwise NULL',
       'input_eligibility_sha256':hashlib.sha256((_run/'input_eligibility.parquet').read_bytes()).hexdigest(),
       'source_batch_id':_source_health['batch_id'],'training_ready':True,
       'required_input_columns':['close','volume','kospi_close','usdkrw','us_treasury_10y','wti','vix'],
       'optional_numeric_columns':['korea_3y'],
       'required_consumer_order':'Compute lags and forward returns on the complete trading calendar, then apply input_eligibility and target-maturity filters',
       'changes':'민철 2026-11-09 수정 (시점 파일 값 복사에서 Silver 관측값 정렬로 바꾸어 기존 ML 입력과 연결함).'}
(_run/'certificate.json').write_text(json.dumps(_cert,ensure_ascii=False,indent=2),encoding='utf8')
# 민철 2026-11-09 수정 (테이블 저장 후 파일 생성에서 전체 파일 검증 후 Delta 저장과 최신 포인터 교체로 바꾸어 실패 시 기존 정상 스냅샷을 보존함).
try:
    for _name,_hash in [('gold.parquet',_cert['gold_sha256']),('provenance.parquet',_cert['provenance_sha256']),('input_eligibility.parquet',_cert['input_eligibility_sha256'])]:
        if hashlib.sha256((_run/_name).read_bytes()).hexdigest()!=_hash:raise RuntimeError('STAGED_SNAPSHOT_HASH_MISMATCH')
    gold.write.format('delta').mode('overwrite').option('overwriteSchema','true').saveAsTable(TARGET)
    write_quality_json(_base/'latest.json',{'version':_version,'path':str(_run).split('/Files/',1)[1]})
    write_quality_json(_health_path,{'status':'ready','training_ready':True,'version':_version,'checked_at_utc':datetime.now(timezone.utc).isoformat(),
        'as_of':_cert['latest_gold_date'],'source_batch_id':_source_health['batch_id'],'eligible_rows':_cert['eligible_rows'],'excluded_rows':_cert['excluded_rows']})
except Exception as _exc:
    write_quality_json(_health_path,{'status':'blocked','training_ready':False,'checked_at_utc':datetime.now(timezone.utc).isoformat(),'reason':type(_exc).__name__})
    raise
print(json.dumps(_cert,ensure_ascii=False))


# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }
