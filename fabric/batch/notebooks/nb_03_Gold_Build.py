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
MAX_GAP_DAYS = 7

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

    # 가격 조정 기준: 후속 검토 예정
    F.lit(None).cast("string").alias("price_basis"),

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

# 4. 거시지표 — 거래일 이전 7일 이내 최신 관측값
def macro_asof(prefix, table):

    src = spark.table(table)

    if "quality_status" in src.columns:
        src = src.filter(
            F.col("quality_status") == "valid"
        )

    macro = (
        src
        .select(
            F.col("observation_date")
                .cast("date").alias("obs_date"),

            F.col("value")
                .cast("double").alias("macro_value"),

            F.col("observed_at")
                .cast("timestamp").alias("observed_at"),

            F.col("available_at")
                .cast("timestamp").alias("available_at")
        )
        .filter(
            F.col("obs_date").isNotNull()
            & F.col("macro_value").isNotNull()
        )
    )

    # 같은 거래일 관측값은 제외:
    # 반드시 거래일보다 이전 관측값만 연결
    joined = (
        dates.alias("d")
        .join(
            macro.alias("m"),
            (
                (F.col("m.obs_date")
                 < F.col("d.trading_date"))
                &
                (
                    F.col("m.obs_date")
                    >= F.date_sub(
                        F.col("d.trading_date"),
                        MAX_GAP_DAYS
                    )
                )
            ),
            "left"
        )
    )

    w = (
        Window
        .partitionBy(F.col("d.trading_date"))
        .orderBy(
            F.col("m.obs_date").desc_nulls_last()
        )
    )

    return (
        joined
        .withColumn("_rank", F.row_number().over(w))
        .filter(F.col("_rank") == 1)
        .select(
            F.col("d.trading_date").alias("trading_date"),

            F.col("m.macro_value").alias(prefix),

            F.col("m.obs_date")
                .alias(f"{prefix}_observation_date"),

            F.col("m.observed_at")
                .alias(f"{prefix}_observed_at"),

            F.col("m.available_at")
                .alias(f"{prefix}_available_at")
        )
    )

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
