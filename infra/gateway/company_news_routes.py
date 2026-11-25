"""Add GET /news/company to the existing authenticated APIM API."""

from __future__ import annotations

import argparse
import shutil

import dart_routes as routes
import deploy as d

OPERATION_ID = "news-company"
PATH = "/news/company"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--expected-image", help="Exact current ready common API image")
    args = parser.parse_args()
    if args.apply and not args.expected_image:
        parser.error("--apply requires --expected-image")
    if not shutil.which("az"):
        parser.error("Azure CLI is required")
    common, debate_base = routes._check_target()
    if args.apply:
        routes._check_common_ready(common, args.expected_image)
    operations = routes._operations()
    by_id = {item["id"].rsplit("/", 1)[-1]: item for item in operations}
    matches = [item for item in operations if item.get("properties", {}).get("method", "").upper() == "GET"
               and item.get("properties", {}).get("urlTemplate", "").split("?", 1)[0] == PATH]
    if len(matches) > 1:
        raise RuntimeError("Multiple GET company-news operations found")
    if matches:
        operation_id = matches[0]["id"].rsplit("/", 1)[-1]
        policy = routes._policy(routes.API + f"/operations/{operation_id}/policies/policy")
        if routes.policy_kind(policy, debate_base) != "inherited":
            raise RuntimeError("Existing company-news operation has unexpected policy")
        print("GET /news/company: already correct")
        return
    if OPERATION_ID in by_id:
        raise RuntimeError("Company-news operation ID belongs to another route")
    print("GET /news/company: create operation with inherited API policy")
    if not args.apply:
        print("Dry run only")
        return
    d.call(routes.API + "/operations/" + OPERATION_ID, routes.VERSION, "PUT", {"properties": {
        "displayName": "Company News Last Three Months", "method": "GET", "urlTemplate": PATH,
        "templateParameters": [], "responses": [],
    }})
    print("GET /news/company created")


if __name__ == "__main__":
    main()
