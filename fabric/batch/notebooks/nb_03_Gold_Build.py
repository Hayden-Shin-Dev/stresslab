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
# 기존 Gold 34컬럼과 ML Notebook은 변경하지 않습니다.

# CELL ********************

# ==================================================
# MS_P3 | GOLD v1.1
# Silver 7개 → Gold 34개 컬럼
# 외부 API 호출 없음
# ==================================================

from pyspark.sql import functions as F
from pyspark.sql.window import Window

spark.conf.set("spark.sql.session.timeZone", "UTC")

TARGET = "gold_stock_market_daily_v11"
VERSION = "ms_p3_gold_v1.1"
# 2026-11-09 12:50 KST 민철 수정 — 로컬 검증과 같은 최대 관측 경과 10일 및 이용 가능 시점 근거를 사용합니다.
MAX_GAP_DAYS = 10

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

# 4. 거시지표 — 기준 시점까지 사용 가능하고 관측일이 10일 이내인 검증값
# 2026-11-09 12:50 KST 민철 수정 — 관측일 단순 비교 대신 Silver에서 생성한 날짜별 PIT 근거를 연결합니다.

from pathlib import Path
import pandas as pd
from pyspark.sql import types as T
_provenance_path=Path('/lakehouse/default/Files/silver_evidence/observation_provenance.parquet')
_p=pd.read_parquet(_provenance_path)
_p['date']=pd.to_datetime(_p.date);_p['observation_date']=pd.to_datetime(_p.observation_date)
_p['known_by']=pd.to_datetime(_p.known_by,utc=True)
if _p.duplicated(['date','source']).any():raise RuntimeError('거시 근거 중복')
_good=_p[_p.verified]
_cutoff=pd.to_datetime(_good.date,utc=True)+pd.Timedelta(hours=6,minutes=30)
if (_good.known_by.isna() | _good.known_by.gt(_cutoff) | ~(_good.date-_good.observation_date).dt.days.between(0,MAX_GAP_DAYS)).any():
    raise RuntimeError('거시 이용 가능 시점 검증 실패')
def macro_asof(prefix, table):
    q=_p[_p.source.eq(prefix)]
    rows=[(r.date.date(),float(r.value) if r.verified else None,r.observation_date.date() if r.verified else None) for r in q.itertuples()]
    schema=T.StructType([T.StructField('trading_date',T.DateType()),T.StructField(prefix,T.DoubleType()),T.StructField(prefix+'_observation_date',T.DateType())])
    result=spark.createDataFrame(rows,schema)
    # 실제 관측/공표 시각을 추정하여 채우지 않습니다. known_by는 별도 근거 파일로 제공합니다.
    return result.withColumn(prefix+'_observed_at',F.lit(None).cast('timestamp')).withColumn(prefix+'_available_at',F.lit(None).cast('timestamp'))

# 5. 다섯 거시지표를 날짜 기준으로 결합
macro_dates = dates

for prefix, table in MACROS:
    macro_dates = macro_dates.join(
        macro_asof(prefix, table),
        on="trading_date",
        how="left"
    )

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

_gp=gold.toPandas();_gp['trading_date']=pd.to_datetime(_gp.trading_date)
require_verified_price_basis(_gp)
_eligible=_gp.quality_status.eq('valid') & _gp.price_basis.eq('adjusted') & _gp.adjustment_version.notna() & _gp.close.gt(0) & _gp.volume.gt(0)
for _name,_table in MACROS:
    _q=_p[_p.source.eq(_name)].set_index('date')
    _expected=_gp.trading_date.map(_q.value)
    if not __import__('numpy').allclose(_gp[_name],_expected,equal_nan=True):raise RuntimeError('Gold 거시 근거 불일치: '+_name)
    _eligible &= _gp[_name].notna() & _gp.trading_date.map(_q.verified).fillna(False)
if not _eligible.any():raise RuntimeError('ML에 사용 가능한 Gold 행이 없습니다')
_latest_eligible=_gp.loc[_eligible,'trading_date'].max()
print('Gold 최신일:',_gp.trading_date.max(),'ML 입력 가능 최신일:',_latest_eligible,'제외 행:',int((~_eligible).sum()))

# 9. 별도 Gold 테이블 저장
# 기존 gold_stock_market_daily는 변경하지 않음
(
    gold.write
    .format("delta")
    .mode("overwrite")
    .option("overwriteSchema", "true")
    .saveAsTable(TARGET)
)

gold.unpersist()

print(f"Gold 테이블 생성 완료: {TARGET}")

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************

df = spark.sql("SELECT * FROM lh_whatif.gold_stock_market_daily_v11 LIMIT 10")
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
_base=Path('/lakehouse/default/Files/gold_evidence/gold_stock_market_daily_v11')
_run=_base/_version;_run.mkdir(parents=True,exist_ok=False)
_gp.to_parquet(_run/'gold.parquet',index=False);_p.to_parquet(_run/'provenance.parquet',index=False)
_cert={'gold_sha256':hashlib.sha256((_run/'gold.parquet').read_bytes()).hexdigest(),
       'provenance_sha256':hashlib.sha256((_run/'provenance.parquet').read_bytes()).hexdigest(),
       'exact_publication_clocks':False,'availability_policy':'Official conservative bounds or recorded retrieval upper bounds; maximum 10 calendar days',
       'latest_gold_date':str(_gp.trading_date.max().date()),'latest_eligible_date':str(_latest_eligible.date()),
       'eligible_rows':int(_eligible.sum()),'excluded_rows':int((~_eligible).sum()),'schema_changed':False}
(_run/'certificate.json').write_text(json.dumps(_cert,ensure_ascii=False,indent=2),encoding='utf8')
(_base/'latest.json').write_text(json.dumps({'version':_version,'path':str(_run).split('/Files/',1)[1]},ensure_ascii=False),encoding='utf8')
print(json.dumps(_cert,ensure_ascii=False))

# METADATA ********************
# META {"language":"python","language_group":"synapse_pyspark"}
