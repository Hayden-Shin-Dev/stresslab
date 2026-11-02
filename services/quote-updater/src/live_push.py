"""Push successfully processed quotes using a receive-only public test hub."""
import json
import os
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
    )


def publish_quote(body):
    if body.get("record_type") != "quote_event" or body.get("is_mock") is not False:
        return
    # Preserve the contracted message, including provider timestamps and venue.
    client().send_to_all(message=body, content_type="application/json")


def publish_batch(bodies):
    quotes = []
    for body in bodies:
        try:
            q = json.loads(body)
            if q.get('record_type') == 'quote_event' and q.get('is_mock') is False:
                quotes.append(q)
        except (ValueError, AttributeError):
            continue
    # Preserve each tick, while reducing outbound calls. No new timer or polling.
    for i in range(0, len(quotes), 50):
        client().send_to_all(message={'type': 'quote_batch', 'quotes': quotes[i:i+50]}, content_type='application/json')


@bp.route(route="quotes/negotiate", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def negotiate(req: func.HttpRequest) -> func.HttpResponse:
    # No send/join permissions: browser is a receive-only diagnostic client.
    token = client().get_client_access_token(minutes_to_expire=10)
    return func.HttpResponse(
        json.dumps({"url": token["url"]}),
        mimetype="application/json",
        headers={"Cache-Control": "no-store"},
    )
