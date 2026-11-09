"""whatif 현재가 갱신 Function (배치 수신 + 종목별 최신값 upsert).

Event Hubs에서 quote_event를 배치로 받아, 배치 안에서 종목별 가장 최근 값만 골라
PostgreSQL의 quote_latest 테이블에 upsert한다. 원문 틱은 Eventhouse에 있으므로 여기에는 쌓지 않는다.
인증은 관리 ID(DefaultAzureCredential)를 쓰고, DB 비밀번호만 Key Vault에서 읽는다.
비밀 값과 연결 문자열은 로그에 남기지 않는다.
"""
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import List
from pathlib import Path
from functools import lru_cache

import azure.functions as func
import psycopg
from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient

from live_push import bp, publish_latest

app = func.FunctionApp()
app.register_functions(bp)
_credential = DefaultAzureCredential()  # AZURE_CLIENT_ID 설정이 사용자 할당 관리 ID를 가리킨다.
_password = None
_conn = None  # 호출 사이에 재사용하는 DB 연결

UPSERT_SQL = """
INSERT INTO quote_latest
    (asset_id, price, cumulative_volume, event_time, received_at,
     source, venue, session, is_mock, event_id)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (asset_id) DO UPDATE SET
    price = EXCLUDED.price,
    cumulative_volume = EXCLUDED.cumulative_volume,
    event_time = EXCLUDED.event_time,
    received_at = EXCLUDED.received_at,
    source = EXCLUDED.source,
    venue = EXCLUDED.venue,
    session = EXCLUDED.session,
    is_mock = EXCLUDED.is_mock,
    event_id = EXCLUDED.event_id,
    updated_at = now()
WHERE COALESCE(EXCLUDED.event_time, EXCLUDED.received_at)
   >= COALESCE(quote_latest.event_time, quote_latest.received_at)
"""


def _get_password() -> str:
    global _password
    if _password is None:
        client = SecretClient(vault_url=os.environ["KEY_VAULT_URL"], credential=_credential)
        _password = client.get_secret("pg-password").value
    return _password


def _get_conn():
    global _conn
    if _conn is None or _conn.closed:
        _conn = psycopg.connect(
            host=os.environ["PG_HOST"],
            port=5432,
            dbname=os.getenv("PG_DB", "postgres"),
            user=os.environ["PG_USER"],
            password=_get_password(),
            sslmode="require",
            connect_timeout=10,
        )
    return _conn


def _parse_time(value):
    """ISO 8601(Z 포함) 문자열을 UTC datetime으로. 값이 없거나 형식이 틀리면 None."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def latest_per_asset(bodies):
    """본문 문자열 목록에서 종목별 가장 최근 quote_event 한 건만 고른다.

    반환: (종목별 행 목록, 건너뛴 건수). 형식이 틀린 메시지는 건너뛰고 세어 둔다.
    """
    latest = {}
    skipped = 0
    for body in bodies:
        try:
            q = json.loads(body)
            if q.get("record_type") != "quote_event":
                skipped += 1
                continue
            asset_id = q["asset_id"]
            price = float(q["price"])
            received_at = _parse_time(q.get("received_at"))
            if price <= 0 or received_at is None:
                skipped += 1
                continue
        except (ValueError, KeyError, TypeError):
            skipped += 1
            continue
        event_time = _parse_time(q.get("event_time"))
        sort_key = event_time or received_at
        current = latest.get(asset_id)
        if current is None or sort_key >= current[0]:
            latest[asset_id] = (
                sort_key,
                (
                    asset_id,
                    price,
                    q.get("cumulative_volume"),
                    event_time,
                    received_at,
                    q.get("source"),
                    q.get("venue"),
                    q.get("session"),
                    q.get("is_mock"),
                    q.get("event_id"),
                ),
            )
    return [row for _, row in latest.values()], skipped


@app.event_hub_message_trigger(
    arg_name="events",
    event_hub_name="%EVENTHUB_NAME%",
    connection="EventHubConnection",
    cardinality="many",
)
def eh_to_pg(events: List[func.EventHubEvent]):
    global _conn
    started = time.perf_counter()
    bodies = [e.get_body().decode("utf-8") for e in events]
    rows, skipped = latest_per_asset(bodies)
    if rows:
        conn = _get_conn()
        try:
            with conn.cursor() as cur:
                cur.executemany(UPSERT_SQL, rows)
            conn.commit()
        except Exception:
            # 연결 상태를 알 수 없으니 버리고 다음 호출에서 새로 연결한다. 예외는 그대로 올린다.
            try:
                conn.close()
            finally:
                _conn = None
            raise
    logging.info(
        "eh_to_pg: 수신 %d건, 갱신 종목 %d개, 건너뜀 %d건, %.0fms",
        len(events), len(rows), skipped, (time.perf_counter() - started) * 1000,
    )


@lru_cache(maxsize=1)
def active_assets():
    manifest = json.loads((Path(__file__).parent/'quote_universe.json').read_text(encoding='utf8'))
    return [a['asset_id'] for a in manifest['assets']]


def read_latest():
    # Separate connection from the Event Hubs writer; no schema/settings changes.
    with psycopg.connect(host=os.environ['PG_HOST'], port=5432,
            dbname=os.getenv('PG_DB', 'postgres'), user=os.environ['PG_USER'],
            password=_get_password(), sslmode='require', connect_timeout=5) as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT row_to_json(q) FROM quote_latest q WHERE is_mock = false AND asset_id = ANY(%s) ORDER BY asset_id', (active_assets(),))
            rows = [r[0] for r in cur.fetchall()]
    quotes = []
    for row in rows:
        # This is a latest-price projection, not a raw trade event.
        quotes.append({**{k: row.get(k) for k in (
            'asset_id','price','cumulative_volume','event_time','received_at',
            'source','venue','session','is_mock','event_id')},
            'record_type':'quote_latest', 'trade_volume':None, 'date_inferred':None})
    return quotes


@app.timer_trigger(schedule='* * * * * *', arg_name='tick',
                   run_on_startup=False, use_monitor=False)
def push_latest_each_second(tick: func.TimerRequest):
    # Azure timer listener has one storage lease across scale-out instances.
    publish_latest(read_latest())


@app.route(route='quotes/latest', methods=['GET'], auth_level=func.AuthLevel.ANONYMOUS)
def latest_snapshot(req: func.HttpRequest) -> func.HttpResponse:
    return func.HttpResponse(json.dumps({'type':'quote_snapshot', 'quotes':read_latest()}),
        mimetype='application/json', headers={'Cache-Control':'no-store'})
