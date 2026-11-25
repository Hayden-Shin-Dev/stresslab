"""Merge Eventhouse stock trade events into a quarterly OneLake Delta table.

Supply archive_from and archive_to as ISO dates for recovery. By default,
the job reprocesses the current and previous Seoul date to pick up late events.
"""
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from delta.tables import DeltaTable
from pyspark.sql import functions as F

WORKSPACE = "2c303c0d-6c10-4988-91cb-856fe5f56071"
LAKEHOUSE = "93432592-8620-411e-808f-b91678bf78d2"
TARGET = f"abfss://{WORKSPACE}@onelake.dfs.fabric.microsoft.com/{LAKEHOUSE}/Tables/stock_price_tick_3y"
CLUSTER = "https://trd-h7ab5z25kfkrka78he.z7.kusto.fabric.microsoft.com"
DATABASE = "eventhouse_whatif"
CODES = "000270 000660 005380 005930 005935 006400 009150 012330 012450 028260 032830 034020 034730 055550 068270 086790 105560 207940 373220 402340".split()
SEOUL = ZoneInfo("Asia/Seoul")


def archive_day(day):
    start = datetime.combine(day, time.min, SEOUL).astimezone(timezone.utc)
    end = start + timedelta(days=1)
    assets = ", ".join(repr(code) for code in CODES)
    query = f"""quote_events
    | where event_time >= datetime({start.isoformat()}) and event_time < datetime({end.isoformat()})
    | where instrument_kind == 'stock' and is_mock == false and asset_id in ({assets})
    | where isnotempty(event_id) and price > 0
    | summarize arg_max(received_at, *) by asset_id, event_id
    | project asset_id, event_id, event_time, received_at, price, trade_volume, source, venue"""
    events = (
        spark.read.format("com.microsoft.kusto.spark.synapse.datasource")
        .option("accessToken", notebookutils.credentials.getToken("kusto"))
        .option("kustoCluster", CLUSTER)
        .option("kustoDatabase", DATABASE)
        .option("kustoQuery", query)
        .load()
        .withColumn("trade_date", F.lit(day))
        .withColumn("trade_quarter", F.lit(f"{day.year}Q{(day.month - 1) // 3 + 1}"))
    )
    if events.isEmpty():
        print(f"No source events for {day}", flush=True)
        return
    if not DeltaTable.isDeltaTable(spark, TARGET):
        (events.limit(0).write.format("delta").partitionBy("trade_quarter")
         .mode("errorifexists").save(TARGET))
    (DeltaTable.forPath(spark, TARGET).alias("t").merge(
        events.alias("s"),
        "t.trade_quarter = s.trade_quarter AND t.trade_date = s.trade_date "
        "AND t.asset_id = s.asset_id AND t.event_id = s.event_id",
    )
     .whenMatchedUpdateAll(condition="s.received_at > t.received_at")
     .whenNotMatchedInsertAll()
     .execute())
    print(f"Committed {day}", flush=True)


spark.conf.set("spark.sql.session.timeZone", "UTC")
today = datetime.now(SEOUL).date()
first_day = date.fromisoformat(archive_from) if "archive_from" in globals() else today - timedelta(days=1)
last_day = date.fromisoformat(archive_to) if "archive_to" in globals() else today
if not first_day <= last_day <= today:
    raise ValueError("Expected archive_from <= archive_to <= today in Seoul")
while first_day <= last_day:
    archive_day(first_day)
    first_day += timedelta(days=1)
