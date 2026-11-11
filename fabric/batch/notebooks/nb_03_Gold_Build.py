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


# 2026-11-10 17:42 KST 민철 수정: 관측일로 먼저 선택한 값을 사후 검사하던 방식에서,
# 공식 근거상 당시 사용 가능했던 관측을 먼저 고르는 로컬 방식으로 변경합니다.
# 정확한 공표 시각과 보수적 날짜 상한은 분리합니다. ML Notebook/Gold 34컬럼은 변경하지 않습니다.
from pathlib import Path
import pandas as pd
import numpy as np
import json,hashlib,sys
from pyspark.sql import types as T
sys.path.insert(0,'/lakehouse/default/Files/reference/gold_availability/v1')
sys.path.insert(0,'/lakehouse/default/Files/reference/publication_evidence/v3')
from gold_availability import select_asof,validate_gold_provenance,write_evidence_certificate,VERSION as AVAILABILITY_VERSION
from availability_policy import POLICY_VERSION,OBSERVATION_GAP_DAYS
from publication_evidence import load_ledger,fx_observed_at
# 정규화 원장만 신뢰하지 않고 Bronze 원문/공식 알림/정규화 파일의 해시를 매번 대조합니다.
_official_ledger=load_ledger('/lakehouse/default/Files/bronze')
_availability_p=pd.read_parquet('/lakehouse/default/Files/silver_evidence/observation_provenance.parquet')
_fxmeta=json.loads(Path('/lakehouse/default/Files/silver_evidence/fx_observation_definition.json').read_text(encoding='utf8'))
_dates=pd.DataFrame({'trading_date':sorted(r[0] for r in dates.collect())})
_dates.trading_date=pd.to_datetime(_dates.trading_date).astype('datetime64[ns]')
_selected_provenance=[]

def macro_asof(prefix,table):
    # Silver의 최신 수정값을 과거로 소급하지 않습니다. 원문에 보존된 당시 빈티지 값이 우선입니다.
    q=select_asof(_dates.trading_date,_official_ledger,prefix)
    q['observed_at']=fx_observed_at(q.observation_date,_fxmeta) if prefix=='usdkrw' else pd.NaT
    q['official_source_ref']=q.source_ref
    q['official_evidence_sha256']=q.evidence_sha256
    q['source_value_verified']=q.verified
    # 기존 소비자 호환 필드는 남기되 예정 시각/현재 수신시각으로 과거 공개시각을 채우지 않습니다.
    q['receipt_upper_bound']=pd.NaT
    q['research_policy_available_at']=pd.NaT
    _selected_provenance.append(q)
    def utc_naive(x):return None if pd.isna(x) else x.tz_convert('UTC').tz_localize(None).to_pydatetime()
    rows=[(r.date.date(),None if pd.isna(r.value) else float(r.value),None if pd.isna(r.observation_date) else r.observation_date.date(),utc_naive(r.publication_at),utc_naive(r.observed_at)) for r in q.itertuples()]
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
        eligible &= observed.notna() & age.between(1, OBSERVATION_GAP_DAYS[name])
    # 2026-11-10 17:42 KST 민철 수정: 숫자 존재 여부 대신 값별 공식 근거와 로컬 공표 정책을 함께 확인합니다.
    for name in ['usdkrw','us_treasury_10y','wti','vix']:
        proof=_p[_p.source.eq(name)].set_index('date')
        eligible &= g.trading_date.map(proof.verified).fillna(False)
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
_availability_checks=validate_gold_provenance(_gp,_p)
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
# 2026-11-10 17:42 KST 민철 추가: 로컬과 동일한 값별 근거 검증 결과 및 빈티지 원장을 Gold 버전에 고정합니다.
_availability_cert=write_evidence_certificate(_run,_official_ledger,_availability_checks)
# 민철 2026-11-09 추가 (제외 건수만 저장하던 방식에서 행별 사용 가능 여부와 이유 저장으로 바꾸어 ML이 결측 행을 구분하도록 함).
_eligibility.to_parquet(_run/'input_eligibility.parquet',index=False)
# 민철 2026-11-09 추가 (기존 공표 근거 대체에서 원본 근거도 함께 보존하는 방식으로 바꾸어 시점 가정 변경 이력을 유지함).
_availability_p.to_parquet(_run/'availability_provenance.parquet',index=False)
_cert={'gold_sha256':hashlib.sha256((_run/'gold.parquet').read_bytes()).hexdigest(),
       'provenance_sha256':hashlib.sha256((_run/'provenance.parquet').read_bytes()).hexdigest(),
       'exact_publication_clocks':False,'availability_policy':'Official value-specific as-of selection; existing local publication-cadence-v2 policy; exact clocks separate from conservative bounds',
       'latest_gold_date':str(_gp.trading_date.max().date()),'latest_eligible_date':str(_latest_eligible.date()),
       'eligible_rows':int(_eligible.sum()),'excluded_rows':int((~_eligible).sum()),'schema_changed':False,
       'input_mode':'asof_macro_state','strict_historical_point_in_time_verified':False,
       'macro_availability_verified_for_eligible_rows':bool(_eligible.any() and all(_gp.loc[_eligible,'trading_date'].map(_p[_p.source.eq(s)].set_index('date').verified).all() for s in ['usdkrw','us_treasury_10y','wti','vix'])),
       'policy_version':POLICY_VERSION,'availability_selector_version':AVAILABILITY_VERSION,
       'publication_ledger_sha256':_availability_cert['ledger_sha256'],
       'availability_certificate_sha256':hashlib.sha256((_run/'availability_certificate.json').read_bytes()).hexdigest(),
       'remaining_scope':'Exact price publication clocks and historical price revision vintages are not certified by macro verification; ML/model approval unchanged',
       'available_at_meaning':'official recorded availability notice time only; receipt and date upper bounds are in provenance', 'observed_at_meaning':'source-defined observation clock where verified; otherwise NULL',
       'input_eligibility_sha256':hashlib.sha256((_run/'input_eligibility.parquet').read_bytes()).hexdigest(),
       'source_batch_id':_source_health['batch_id'],'training_ready':True,
       'required_input_columns':['close','volume','kospi_close','usdkrw','us_treasury_10y','wti','vix'],
       'optional_numeric_columns':['korea_3y'],
       'required_consumer_order':'Compute lags and forward returns on the complete trading calendar, then apply input_eligibility and target-maturity filters',
       'changes':'민철 2026-11-10 수정: 값별 공식 근거가 기준시각 전에 존재하는 관측만 Gold에 선택. 근거 없는 값은 제외하며 ML 코드는 변경하지 않음.'}
(_run/'certificate.json').write_text(json.dumps(_cert,ensure_ascii=False,indent=2),encoding='utf8')
# 민철 2026-11-09 수정 (테이블 저장 후 파일 생성에서 전체 파일 검증 후 Delta 저장과 최신 포인터 교체로 바꾸어 실패 시 기존 정상 스냅샷을 보존함).
try:
    for _name,_hash in [('gold.parquet',_cert['gold_sha256']),('provenance.parquet',_cert['provenance_sha256']),('input_eligibility.parquet',_cert['input_eligibility_sha256'])]:
        if hashlib.sha256((_run/_name).read_bytes()).hexdigest()!=_hash:raise RuntimeError('STAGED_SNAPSHOT_HASH_MISMATCH')
    gold.write.format('delta').mode('overwrite').option('overwriteSchema','true').saveAsTable(TARGET)
    _saved=spark.table(TARGET).select(*gold.columns)
    if _saved.exceptAll(gold).limit(1).count() or gold.exceptAll(_saved).limit(1).count():raise RuntimeError('PUBLISHED_GOLD_MISMATCH')
    write_quality_json(_run/'publication_verification.json',{'published_gold_matches_delta':True,'macro_value_provenance_checks':_availability_checks,'ml_notebooks_modified':False})
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
