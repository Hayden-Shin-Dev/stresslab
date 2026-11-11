"""Push successfully processed quotes using a receive-only public test hub."""
import json
import os
import time
import threading
from datetime import datetime, timezone
from functools import lru_cache

import azure.functions as func
from azure.identity import DefaultAzureCredential
from azure.messaging.webpubsubservice import WebPubSubServiceClient

bp = func.Blueprint()


@lru_cache(maxsize=1)
def client():
    return WebPubSubServiceClient(
        endpoint="https://wps-whatif-dev.webpubsub.azure.com",
        hub="quote_monitor",
        credential=DefaultAzureCredential(
            managed_identity_client_id=os.environ.get("AZURE_CLIENT_ID")
        ),
        # 2026-11-11 민철 수정: 최신가 전송이 300초 동안 막히지 않도록 제한.
        # SDK 재시도 대신 다음 타이머가 DB의 가장 최신값을 다시 조회합니다.
        connection_timeout=2,
        read_timeout=3,
        retry_total=0,
        retry_connect=0,
        retry_read=0,
        retry_status=0,
    )


_sent = {}
_last_send = -float('inf')
_lock = threading.Lock()

def publish_latest(quotes):
    """One batch at most per second; failed sends remain pending next tick."""
    global _last_send
    with _lock:
        now = int(time.monotonic())
        if now - _last_send < 1:
            return 0
        changed = []
        signatures = {}
        for q in quotes:
            if q.get('is_mock') is not False:
                continue
            key = q['asset_id']
            sig = json.dumps(q, sort_keys=True)
            signatures[key] = sig
            if _sent.get(key) != sig:
                changed.append(q)
        if not changed:
            return 0
        client().send_to_all(message={'type':'quote_batch','delivery':'latest_1s',
            'published_at':datetime.now(timezone.utc).isoformat(), 'quotes':changed}, content_type='application/json')
        _sent.update(signatures)
        _last_send = now
        return len(changed)


@bp.route(route="quotes/negotiate", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def negotiate(req: func.HttpRequest) -> func.HttpResponse:
    # No send/join permissions: browser is a receive-only diagnostic client.
    token = client().get_client_access_token(minutes_to_expire=10)
    return func.HttpResponse(
        json.dumps({"url": token["url"]}),
        mimetype="application/json",
        headers={"Cache-Control": "no-store"},
    )
