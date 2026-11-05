# Fabric 노트북: nb_realtime_close_handoff
# 기본 레이크하우스: lh_whatif (ws-whatif-dev)
# 리소스(Resources)에 close_handoff.py를 올리고 아래 셀 순서대로 붙여 넣습니다.
# 파이프라인 pl_realtime_close가 평일 16:10 KST에 실행합니다. 같은 날 다시 실행해도 새 batch_id로 게시됩니다.

# %% [parameters]  ← 이 셀을 '매개 변수 셀'로 지정
trade_date = ""          # "YYYY-MM-DD". 비우면 오늘(KST)
kusto_uri = ""           # Eventhouse Query URI (시장 상태 API의 KUSTO_QUERY_URI와 같은 값)
kusto_database = ""      # KQL 데이터베이스 이름
bronze = "/lakehouse/default/Files/bronze"

# %%
import sys
from datetime import date, datetime, timezone

sys.path.insert(0, "./builtin")          # 노트북 리소스 폴더
import close_handoff as ch

day = date.fromisoformat(trade_date) if trade_date else datetime.now(ch.KST).date()
if day.weekday() >= 5:
    mssparkutils.notebook.exit(f"skip: {day} 주말")  # noqa: F821

token = mssparkutils.credentials.getToken(kusto_uri)  # noqa: F821


def kql(query: str):
    return (spark.read.format("com.microsoft.kusto.spark.synapse.datasource")  # noqa: F821
            .option("accessToken", token)
            .option("kustoCluster", kusto_uri)
            .option("kustoDatabase", kusto_database)
            .option("kustoQuery", query)
            .load()
            .toPandas())


q = ch.kql_queries(day)
universe = kql(q["universe"])["asset_id"].astype(str).tolist()
events = kql(q["events"])
bars = kql(q["bars"])
snapshots = kql(q["snapshots"])
print(f"{day}: 종목 {len(universe)}, 체결 요약 {len(events)}행, 분봉 {len(bars)}행, 스냅샷 {len(snapshots)}행")

# %%
handoff = ch.build_handoff(day, universe, events, bars, snapshots, created_at=datetime.now(timezone.utc))
m = handoff["market"]
print(handoff["batch_id"], handoff["status"])
print(f"종목 완전 {m['assets_complete']} / 일부 {m['assets_partial']} / 없음 {m['assets_missing']}")
print(f"스냅샷 {m['snapshots_saved']}/{m['snapshots_expected']} 누락 {m['snapshots_missing_kst']}")
print(f"체결 {m['events_total']}건, 중복 {m['duplicate_events_total']}건, 분봉 정정 {m['bars_revised_total']}건")

# %%
if handoff["status"] == "no_market_observations" and not trade_date:
    mssparkutils.notebook.exit(f"skip: {day} 관측 없음(휴장일 가능)")  # noqa: F821
path = ch.publish(bronze, handoff)
print("게시:", path)

# 게시한 것을 batch와 같은 방법으로 다시 읽어 확인
manifest, assets, market = ch.read_realtime_close(bronze, handoff["batch_id"])
assert len(assets) == len(universe) and manifest["status"] == handoff["status"]
mssparkutils.notebook.exit(f"{handoff['batch_id']} {handoff['status']}")  # noqa: F821
