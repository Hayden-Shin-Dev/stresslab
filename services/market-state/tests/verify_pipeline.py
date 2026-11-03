"""whatif 실시간 경로 점검 (Cloud Shell용, 읽기 전용).

Event Hubs → Eventstream → Eventhouse(원문) → market_state_v2 → market_state_history
→ 시장 상태 API → PostgreSQL 저장 / Web PubSub 발행 → 화면 수신
단계마다 지금 값이 들어오는지 확인하고, 화면에 도착한 스냅샷마다 시각을 이어 붙여 지연을 계산합니다.
데이터를 쓰거나 메시지를 보내지 않습니다.

실행:
  pip install --user -q azure-kusto-data azure-identity "psycopg[binary]" websockets requests
  python3 verify_pipeline.py --raw-table <Eventhouse 원문 테이블> [--minutes 3]
인증: Cloud Shell에 로그인한 계정(az login)을 그대로 사용합니다.
"""
import argparse
import asyncio
import json
import statistics
import subprocess
from datetime import datetime, timedelta, timezone

import psycopg
import requests
import websockets
from azure.identity import AzureCliCredential
from azure.kusto.data import KustoClient, KustoConnectionStringBuilder

KUSTO_URI = "https://trd-h7ab5z25kfkrka78he.z7.kusto.fabric.microsoft.com"
KUSTO_DB = "8737c880-d0ce-444f-a8b3-07a33f64ddc0"
FQDN = "ca-marketstate-whatif-dev.proudfield-489f3ad8.koreacentral.azurecontainerapps.io"
PG_HOST = "psql-whatif-dev.postgres.database.azure.com"
KST = timezone(timedelta(hours=9))

cred = AzureCliCredential()


def kq(client, q):
    return [r.to_dict() for r in client.execute(KUSTO_DB, q).primary_results[0]]


def utc(v):
    if v is None:
        return None
    if isinstance(v, str):
        v = datetime.fromisoformat(v.replace("Z", "+00:00"))
    return v if v.tzinfo else v.replace(tzinfo=timezone.utc)


def kdt(d):
    return d.strftime("datetime(%Y-%m-%dT%H:%M:%S.%fZ)")


def kst(d):
    return d.astimezone(KST).strftime("%H:%M:%S.%f")[:-3] if d else "-"


def ok(flag):
    return "정상" if flag else "확인 필요"


def pg_conn(user):
    token = cred.get_token("https://ossrdbms-aad.database.windows.net/.default").token
    return psycopg.connect(host=PG_HOST, dbname="postgres", user=user, password=token,
                           sslmode="require", connect_timeout=10)


def health(kc, raw, pg_user):
    now = datetime.now(timezone.utc)
    print(f"\n[1] 단계별 상태  (확인 시각 {kst(now)} KST)")
    r = kq(kc, f"""{raw}
| where ingestion_time() > ago(2m)
| extend et = todatetime(event_time)
| summarize rows = count(), assets = dcount(asset_id), last_ing = max(ingestion_time()),
            lag_p50 = percentile((ingestion_time() - et) / 1s, 50),
            lag_p95 = percentile((ingestion_time() - et) / 1s, 95)""")[0]
    age = (now - utc(r["last_ing"])).total_seconds() if r["last_ing"] else None
    print(f"  Event Hubs→Eventstream→Eventhouse  최근 2분 {r['rows']}건, {r['assets']}종목, "
          f"마지막 적재 {age and round(age)}초 전, 체결→적재 p50 {r['lag_p50'] and round(r['lag_p50'],1)}s "
          f"p95 {r['lag_p95'] and round(r['lag_p95'],1)}s  [{ok(r['rows'] and age is not None and age < 30)}]")
    h = kq(kc, """market_state_history | summarize as_of = max(as_of), n10 = countif(as_of > ago(11m)),
            ids10 = dcountif(tostring(snapshot.snapshot_id), as_of > ago(11m))""")[0]
    hage = (now - utc(h["as_of"])).total_seconds()
    print(f"  market_state_v2→history             최신 as_of {kst(utc(h['as_of']))}({round(hage)}초 전), "
          f"최근 10분 {h['n10']}행/{h['ids10']}개  [{ok(hage < 150 and h['n10'] == h['ids10'] >= 9)}]")
    st = requests.get(f"https://{FQDN}/market-state/status", timeout=10).json()
    print(f"  시장 상태 API 조회                  loop_alive={st['loop_alive']} last_poll_ok={st['last_poll_ok']}  "
          f"[{ok(st['loop_alive'] and st['last_poll_ok'])}]")
    with pg_conn(pg_user) as c:
        p = c.execute("select snapshot_id, as_of, stored_at from market_state_snapshot order by as_of desc limit 1").fetchone()
    print(f"  PostgreSQL 저장                     최신 {p[0]} 저장 {kst(p[2])}  last_db_ok={st['last_db_ok']}  "
          f"[{ok(st['last_db_ok'] and p[0] == st['snapshot_id'])}]" if p else "  PostgreSQL 저장  행 없음 [확인 필요]")
    print(f"  Web PubSub 발행                     published_id={st['published_id']} last_publish_ok={st['last_publish_ok']}  "
          f"[{ok(st['last_publish_ok'] and st['published_id'] == st['snapshot_id'])}]")


async def listen(minutes):
    url = requests.post(f"https://{FQDN}/market-state/negotiate", timeout=10).json()["url"]
    got = []
    async with websockets.connect(url, open_timeout=10) as ws:
        print(f"\n[2] Web PubSub 수신 {minutes}분 (스냅샷마다 시각을 이어 붙입니다)")
        loop = asyncio.get_running_loop()
        end = loop.time() + minutes * 60
        while (left := end - loop.time()) > 0:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=left)
            except asyncio.TimeoutError:
                break
            msg = json.loads(raw)
            got.append((datetime.now(timezone.utc), msg))
            print(f"  수신 {msg['snapshot_id']} {kst(got[-1][0])}")
    return got


def trace(kc, raw, pg_user, got):
    if not got:
        print("\n  수신한 스냅샷이 없습니다. [1]의 '확인 필요' 단계를 먼저 보세요.")
        return
    print("\n[3] 시각 추적 (KST, 괄호는 앞 단계로부터 걸린 시간)")
    rows = []
    with pg_conn(pg_user) as c:
        for recv, m in got:
            as_of = utc(m["as_of"])
            bar_start = as_of - timedelta(minutes=1)
            t = kq(kc, f"""{raw}
| extend et = todatetime(event_time), ra = todatetime(received_at), ing = ingestion_time()
| where et >= {kdt(bar_start)} and et < {kdt(as_of)}
| summarize arg_max(et, ra, ing), first_et = min(et), n = count()""")[0]
            hist = kq(kc, f"""market_state_history
| where tostring(snapshot.snapshot_id) == '{m['snapshot_id']}'
| extend ing = ingestion_time()
| summarize hist_ing = min(ing)""")
            hist_ing = utc(hist[0]["hist_ing"]) if hist and hist[0]["hist_ing"] else None
            stored = c.execute("select stored_at from market_state_snapshot where snapshot_id = %s",
                               (m["snapshot_id"],)).fetchone()
            stored = stored[0] if stored else None
            steps = [
                ("마지막 체결 (event_time)", utc(t["et"])),
                ("수집기 수신 (received_at)", utc(t["ra"])),
                ("Eventhouse 적재", utc(t["ing"])),
                ("분봉 마감 (as_of)", as_of),
                ("스냅샷 계산 (computed_at)", utc(m["computed_at"])),
                ("history 적재", hist_ing),
                ("PostgreSQL 저장", stored),
                ("화면 수신 (Web PubSub)", recv),
            ]
            print(f"\n  {m['snapshot_id']}  분봉 {kst(bar_start)[:5]}~{kst(as_of)[:5]}, 체결 {t['n']}건")
            prev = None
            for name, ts in steps:
                gap = f"(+{(ts - prev).total_seconds():.1f}s)" if ts and prev else ""
                print(f"    {name:<26} {kst(ts)}  {gap}")
                prev = ts or prev
            first = utc(t["first_et"])
            rows.append(((recv - utc(t["et"])).total_seconds(),
                         (recv - first).total_seconds() if first else None,
                         (recv - as_of).total_seconds()))
    last = [r[0] for r in rows]
    firsts = [r[1] for r in rows if r[1] is not None]
    bar = [r[2] for r in rows]
    print("\n[4] 요약")
    print(f"  분봉 마감 → 화면 수신          평균 {statistics.mean(bar):.1f}s")
    print(f"  분봉의 마지막 체결 → 화면 수신  평균 {statistics.mean(last):.1f}s  (가장 짧은 경우)")
    if firsts:
        print(f"  분봉의 첫 체결 → 화면 수신      평균 {statistics.mean(firsts):.1f}s  (가장 긴 경우)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw-table", required=True)
    ap.add_argument("--minutes", type=int, default=3)
    a = ap.parse_args()
    pg_user = subprocess.run(["az", "account", "show", "--query", "user.name", "-o", "tsv"],
                             capture_output=True, text=True, check=True).stdout.strip()
    kc = KustoClient(KustoConnectionStringBuilder.with_azure_token_credential(KUSTO_URI, cred))
    health(kc, a.raw_table, pg_user)
    got = asyncio.run(listen(a.minutes))
    trace(kc, a.raw_table, pg_user, got)


if __name__ == "__main__":
    main()
