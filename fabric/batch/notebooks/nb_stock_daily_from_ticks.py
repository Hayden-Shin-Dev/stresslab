# Build OHLC from observed ticks. These values describe the archived feed.
from datetime import date, timedelta

from delta.tables import DeltaTable
from pyspark.sql import functions as F

LAKEHOUSE_ROOT = (
    "abfss://2c303c0d-6c10-4988-91cb-856fe5f56071@onelake.dfs.fabric.microsoft.com/"
    "93432592-8620-411e-808f-b91678bf78d2"
)
TICKS = f"{LAKEHOUSE_ROOT}/Tables/stock_price_tick_3y"
DAILY = f"{LAKEHOUSE_ROOT}/Tables/stock_price_daily_from_ticks"
FIRST_TRADE_DATE = date(2026, 11, 2)
spark.conf.set("spark.sql.session.timeZone", "UTC")


def refresh_daily_bars():
    ticks = spark.read.format("delta").load(TICKS)
    exists = DeltaTable.isDeltaTable(spark, DAILY)
    if exists:
        last_bar_day = (
            spark.read.format("delta").load(DAILY)
            .agg(F.max("trade_date")).first()[0]
        )
        start = max(FIRST_TRADE_DATE, last_bar_day - timedelta(days=2)) if last_bar_day else FIRST_TRADE_DATE
    else:
        start = FIRST_TRADE_DATE

    # Resolve same-second ties using receipt time and the recorded event ID.
    tick_order = F.struct("event_time", "received_at", "event_id")
    tick_volume = F.abs(F.col("trade_volume"))
    bars = (
        ticks.filter(
            (F.col("trade_date") >= F.lit(start))
            & F.col("event_time").isNotNull()
            & (F.col("price") > 0)
        )
        .groupBy("trade_quarter", "trade_date", "asset_id")
        .agg(
            F.min_by("price", tick_order).alias("open"),
            F.max("price").alias("high"),
            F.min("price").alias("low"),
            F.max_by("price", tick_order).alias("close"),
            F.sum(tick_volume).alias("known_trade_volume"),
            F.count(F.when(tick_volume.isNull(), 1)).alias("missing_volume_ticks"),
            F.count("*").alias("tick_count"),
            F.min("event_time").alias("first_event_at_utc"),
            F.max("event_time").alias("last_event_at_utc"),
        )
        .withColumn("volume", F.when(F.col("missing_volume_ticks") == 0, F.col("known_trade_volume")))
        .withColumn("source", F.lit("stock_price_tick_3y"))
        .withColumn("resolution", F.lit("1d"))
    )
    if not exists:
        if bars.isEmpty():
            raise ValueError("No valid archived ticks found for daily aggregation")
        (bars.write.format("delta").partitionBy("trade_quarter")
         .mode("errorifexists").save(DAILY))
    else:
        (DeltaTable.forPath(spark, DAILY).alias("t").merge(
            bars.alias("s"),
            "t.trade_quarter = s.trade_quarter AND t.trade_date = s.trade_date "
            "AND t.asset_id = s.asset_id",
        ).whenMatchedUpdateAll().whenNotMatchedInsertAll().execute())

    for path, label in ((TICKS, "TICKS"), (DAILY, "DAILY")):
        stored = spark.read.format("delta").load(path)
        (stored.filter(F.col("trade_date") >= F.lit(start))
         .agg(
             F.count("*").alias("rows"),
             F.countDistinct("asset_id").alias("assets"),
             F.countDistinct("trade_date").alias("trade_days"),
             F.min("trade_date").alias("from_kst"),
             F.max("trade_date").alias("to_kst"),
         ).withColumn("table", F.lit(label)).show(truncate=False))


refresh_daily_bars()
