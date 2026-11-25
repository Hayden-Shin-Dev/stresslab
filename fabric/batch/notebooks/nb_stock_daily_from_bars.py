# Roll up the latest revision of each Eventhouse minute bar by Seoul trading date.
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from delta.tables import DeltaTable
from pyspark.sql import functions as F

DAILY_PATH = (
    "abfss://2c303c0d-6c10-4988-91cb-856fe5f56071@onelake.dfs.fabric.microsoft.com/"
    "93432592-8620-411e-808f-b91678bf78d2/Tables/stock_price_daily_from_bars_1m"
)
BAR_CLUSTER = "https://trd-h7ab5z25kfkrka78he.z7.kusto.fabric.microsoft.com"
BAR_DATABASE = "eventhouse_whatif"
FIRST_BAR_DATE = date(2026, 11, 2)
BAR_CODES = "000270 000660 005380 005930 005935 006400 009150 012330 012450 028260 032830 034020 034730 055550 068270 086790 105560 207940 373220 402340".split()
BAR_TIMEZONE = ZoneInfo("Asia/Seoul")
spark.conf.set("spark.sql.session.timeZone", "UTC")


def refresh_daily_from_minutes():
    exists = DeltaTable.isDeltaTable(spark, DAILY_PATH)
    start = FIRST_BAR_DATE
    if exists:
        last_day = spark.read.format("delta").load(DAILY_PATH).agg(F.max("trade_date")).first()[0]
        if last_day:
            start = max(FIRST_BAR_DATE, last_day - timedelta(days=2))

    since = datetime.combine(start, time.min, BAR_TIMEZONE).astimezone(timezone.utc)
    codes = ", ".join(repr(code) for code in BAR_CODES)
    query = f"""bars_1m
    | where bar_at >= datetime({since.isoformat()}) and asset_id in ({codes})
    | summarize arg_max(ingested_at, *) by asset_id, bar_at
    | where open > 0 and high > 0 and low > 0 and close > 0
    | project asset_id, bar_at, open, high, low, close, volume, ticks"""
    minute_bars = (spark.read.format("com.microsoft.kusto.spark.synapse.datasource")
        .option("accessToken", notebookutils.credentials.getToken("kusto"))
        .option("kustoCluster", BAR_CLUSTER)
        .option("kustoDatabase", BAR_DATABASE)
        .option("kustoQuery", query).load()
        .withColumn("trade_date", F.to_date(F.from_utc_timestamp("bar_at", "Asia/Seoul"))))
    daily_bars = (
        minute_bars.groupBy("trade_date", "asset_id")
        .agg(
            F.min_by("open", "bar_at").alias("open"),
            F.max("high").alias("high"),
            F.min("low").alias("low"),
            F.max_by("close", "bar_at").alias("close"),
            F.sum("volume").alias("known_volume"),
            F.count(F.when(F.col("volume").isNull(), 1)).alias("missing_volume_bars"),
            F.sum("ticks").alias("reported_ticks"),
            F.count("*").alias("bar_count"),
            F.min("bar_at").alias("first_bar_at_utc"),
            F.max("bar_at").alias("last_bar_at_utc"),
        )
        .withColumn("volume", F.when(F.col("missing_volume_bars") == 0, F.col("known_volume")))
        .withColumn("trade_quarter", F.concat(F.year("trade_date"), F.lit("Q"), F.quarter("trade_date")))
        .withColumn("source", F.lit("bars_1m"))
        .withColumn("resolution", F.lit("1d"))
    )
    if not exists:
        if daily_bars.isEmpty():
            raise ValueError("No valid Eventhouse minute bars found")
        (daily_bars.write.format("delta").partitionBy("trade_quarter")
         .mode("errorifexists").save(DAILY_PATH))
    else:
        (DeltaTable.forPath(spark, DAILY_PATH).alias("t").merge(
            daily_bars.alias("s"),
            "t.trade_quarter = s.trade_quarter AND t.trade_date = s.trade_date "
            "AND t.asset_id = s.asset_id",
        ).whenMatchedUpdateAll().whenNotMatchedInsertAll().execute())

    (spark.read.format("delta").load(DAILY_PATH)
     .agg(F.count("*").alias("daily_rows"), F.countDistinct("asset_id").alias("assets"),
          F.countDistinct("trade_date").alias("trade_days"), F.sum("bar_count").alias("minute_rows"),
          F.min("trade_date").alias("from_kst"), F.max("trade_date").alias("to_kst"))
     .show(truncate=False))


refresh_daily_from_minutes()
