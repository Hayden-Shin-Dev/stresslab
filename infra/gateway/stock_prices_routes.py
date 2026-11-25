"""Connect only the stock-price operation to the existing Market State app."""

import argparse
from xml.etree import ElementTree

import requests

import dart_routes as routes
import deploy as d

OPERATION = "stock-prices-v1"
PATH = "/market-state/stock-prices"
MARKET_APP = d.ROOT + "/providers/Microsoft.App/containerApps/ca-marketstate-whatif-dev"


def stock_policy(backend):
    return f"""<policies>
  <inbound>
    <base />
    <set-header name="X-StressLab-Gateway-Key" exists-action="delete" />
    <set-backend-service base-url="{backend}" />
    <rewrite-uri template="{PATH}" copy-unmatched-params="true" />
  </inbound>
  <backend><base /></backend>
  <outbound><base /></outbound>
  <on-error><base /></on-error>
</policies>"""


def connect(apply):
    routes._check_target()
    api = d.call(routes.API, routes.VERSION)["properties"]
    if api["path"] != "api" or not api.get("subscriptionRequired"):
        raise RuntimeError("Expected the existing authenticated /api gateway")
    api_policy = routes._policy(routes.API + "/policies/policy")
    if api_policy and any(node.get("backend-id") for node in
                          ElementTree.fromstring(api_policy).iter("set-backend-service")):
        raise RuntimeError("The API's backend-id policy needs a compatible operation policy")

    market = d.call(MARKET_APP, "2024-03-01")["properties"]
    if market["latestReadyRevisionName"] != market["latestRevisionName"]:
        raise RuntimeError("Market State revision is not ready")
    backend = "https://" + market["configuration"]["ingress"]["fqdn"]
    response = requests.get(backend + PATH, params={"assets": "005930", "period": "day"}, timeout=20)
    response.raise_for_status()
    if not response.json().get("series", {}).get("005930"):
        raise RuntimeError("Market State did not return stored prices")

    items = routes._operations()
    matching = [
        item["name"] for item in items
        if item["properties"]["method"].upper() == "GET"
        and item["properties"]["urlTemplate"].split("?", 1)[0] == PATH
    ]
    operation_path = routes.API + "/operations/" + OPERATION
    policy_path = operation_path + "/policies/policy"
    policy = stock_policy(backend)
    if matching == [OPERATION]:
        existing = routes._policy(policy_path)
        if existing and ElementTree.canonicalize(existing, strip_text=True) == ElementTree.canonicalize(policy, strip_text=True):
            print("Stock prices already route to Market State")
            return
        if routes.policy_kind(existing, "") != "inherited":
            raise RuntimeError("Existing stock price operation has a different policy")
    elif matching or any(item["name"] == OPERATION for item in items):
        raise RuntimeError("Conflicting APIM operation ID or URL")

    if not apply:
        print("Ready to route GET /api/market-state/stock-prices to Market State")
        return
    if not matching:
        d.call(operation_path, routes.VERSION, "PUT", {"properties": {
            "displayName": "Eventhouse stock prices", "method": "GET", "urlTemplate": PATH,
            "templateParameters": [], "responses": [],
        }})
    d.call(policy_path, routes.VERSION, "PUT", {"properties": {"format": "rawxml", "value": policy}})
    print("GET /api/market-state/stock-prices now routes to Market State")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    connect(parser.parse_args().apply)
