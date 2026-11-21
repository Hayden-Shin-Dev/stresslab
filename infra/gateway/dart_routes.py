"""Safely route the DART operations through the existing common API.

Read-only by default. --apply changes only DART operations and their
operation-level policies; the API, product, subscription, and SWA link remain
untouched. An unexpected operation or policy stops the entire plan before
the first write.
"""

from __future__ import annotations

import argparse
import shutil
from dataclasses import dataclass
from xml.etree import ElementTree

import requests

import deploy as d

VERSION = "2024-05-01"
API = d.APIM + "/apis/stresslab"
BASE_POLICY = (
    "<policies><inbound><base /></inbound><backend><base /></backend>"
    "<outbound><base /></outbound><on-error><base /></on-error></policies>"
)
ROUTES = (
    ("dart-companies", "DART Company Search", "/dart/companies"),
    ("dart-disclosures", "DART Disclosures", "/dart/disclosures"),
    ("dart-detail", "DART Major Disclosure Detail", "/dart/detail/{receipt_no}"),
    ("dart-financials", "DART Financials", "/dart/financials"),
    ("dart-original", "DART Original ZIP", "/dart/original/{receipt_no}"),
    ("dart-xbrl", "DART XBRL ZIP", "/dart/xbrl/{receipt_no}"),
    ("dart-original-preview", "DART Original Preview", "/dart/original/{receipt_no}/preview"),
)


@dataclass(frozen=True)
class Change:
    operation_id: str
    title: str
    path: str
    create: bool
    replace_policy: bool


def _xml(value: str) -> ElementTree.Element:
    try:
        return ElementTree.fromstring(value)
    except ElementTree.ParseError as exc:
        raise RuntimeError("An operation policy is not valid XML") from exc


def _base_only(element: ElementTree.Element) -> bool:
    return (
        not element.attrib
        and [child.tag for child in element] == ["base"]
        and not element[0].attrib
        and not list(element[0])
        and not (element[0].text or "").strip()
    )


def _sections(root: ElementTree.Element) -> dict[str, ElementTree.Element] | None:
    names = ["inbound", "backend", "outbound", "on-error"]
    if root.tag != "policies" or root.attrib or [child.tag for child in root] != names:
        return None
    return dict(zip(names, root))


def policy_kind(value: str | None, debate_base: str) -> str:
    """Accept inherited policy or the one known legacy DART-to-debate override."""
    if value is None:
        return "inherited"
    sections = _sections(_xml(value))
    if sections is None:
        return "unexpected"
    if not all(_base_only(sections[name]) for name in ("backend", "outbound", "on-error")):
        return "unexpected"
    inbound = sections["inbound"]
    if _base_only(inbound):
        return "inherited"
    children = list(inbound)
    if [child.tag for child in children] != [
        "set-variable", "base", "set-header", "set-backend-service"
    ]:
        return "unexpected"
    variable, base, header, backend = children
    if variable.attrib.get("name") != "swaAuthorization":
        return "unexpected"
    expression = variable.attrib.get("value", "")
    if "context.Request.Headers" not in expression or "Authorization" not in expression:
        return "unexpected"
    if base.attrib or list(base) or (base.text or "").strip():
        return "unexpected"
    if header.attrib != {"name": "Authorization", "exists-action": "override"}:
        return "unexpected"
    if len(header) != 1 or header[0].tag != "value":
        return "unexpected"
    if "swaAuthorization" not in (header[0].text or ""):
        return "unexpected"
    if backend.attrib != {"base-url": debate_base.rstrip("/")} or list(backend):
        return "unexpected"
    return "legacy-debate"


def _policy(path: str) -> str | None:
    """Read an operation policy while treating a missing policy as inherited."""
    response = requests.get(
        d.ARM + path,
        params={"api-version": VERSION},
        headers=d.headers(),
        timeout=30,
    )
    if response.status_code == 404:
        return None
    if not response.ok:
        raise RuntimeError(f"ARM GET operation policy returned HTTP {response.status_code}")
    if response.text.lstrip().startswith("<"):
        return response.text
    body = response.json()
    return body.get("properties", {}).get("value")


def _operations() -> list[dict]:
    url = d.ARM + API + "/operations"
    items = []
    for _ in range(20):
        response = requests.get(url, params={"api-version": VERSION} if "?" not in url else None,
                                headers=d.headers(), timeout=30)
        if not response.ok:
            raise RuntimeError(f"ARM GET operations returned HTTP {response.status_code}")
        page = response.json()
        items.extend(page.get("value", []))
        next_url = page.get("nextLink")
        if not next_url:
            return items
        if not next_url.startswith(d.ARM + API + "/operations?"):
            raise RuntimeError("Unexpected APIM operation pagination URL")
        url = next_url
    raise RuntimeError("APIM operation list exceeded 20 pages")


def _check_target() -> tuple[dict, str]:
    link = d.call(d.SWA + "/linkedBackends/backend1", "2023-12-01")
    if link.get("properties", {}).get("backendResourceId", "").lower() != d.APIM.lower():
        raise RuntimeError("The target SWA is not linked to this APIM service")
    common = d.call(d.COMMON, "2024-03-01")
    fqdn = common.get("properties", {}).get("configuration", {}).get("ingress", {}).get("fqdn")
    if not fqdn:
        raise RuntimeError("The common API has no ingress FQDN")
    api = d.call(API, VERSION).get("properties", {})
    if api.get("path") != "api" or api.get("serviceUrl", "").rstrip("/") != f"https://{fqdn}/api":
        raise RuntimeError("StressLab API path or backend differs from the expected common API")
    if api.get("subscriptionRequired") is not True:
        raise RuntimeError("StressLab API no longer requires an APIM subscription")
    api_policy = d.call(API + "/policies/policy", VERSION)
    policy = api_policy.get("properties", {}).get("value", api_policy.get("raw_xml", ""))
    if not all(token in policy for token in (
        "<base", "X-StressLab-Gateway-Key", "common-api-key",
        'name="Authorization" exists-action="delete"',
    )):
        raise RuntimeError("StressLab API gateway/auth policy differs from the expected policy")
    debate = d.call(d.DEBATE, "2024-03-01")
    debate_fqdn = debate.get("properties", {}).get("configuration", {}).get("ingress", {}).get("fqdn")
    if not debate_fqdn:
        raise RuntimeError("The legacy debate API has no ingress FQDN")
    return common, f"https://{debate_fqdn}/api"


def _check_common_ready(common: dict, expected_image: str) -> None:
    props = common.get("properties", {})
    if props.get("latestReadyRevisionName") != props.get("latestRevisionName"):
        raise RuntimeError("The common API's latest revision is not ready")
    containers = props.get("template", {}).get("containers", [])
    if len(containers) != 1 or containers[0].get("image") != expected_image:
        raise RuntimeError("The common API image does not match --expected-image")
    dart_env = [item for item in containers[0].get("env", []) if item.get("name") == "DART_API_KEY"]
    if len(dart_env) != 1 or not dart_env[0].get("secretRef"):
        raise RuntimeError("The common API DART_API_KEY secret reference is missing")
    secret_name = dart_env[0]["secretRef"]
    secrets = props.get("configuration", {}).get("secrets", [])
    if not any(item.get("name") == secret_name for item in secrets):
        raise RuntimeError("The referenced DART secret is not configured on the common API")


def _plan(debate_base: str) -> list[Change]:
    operations = _operations()
    by_id = {item["id"].rsplit("/", 1)[-1]: item for item in operations}
    if len(by_id) != len(operations):
        raise RuntimeError("Duplicate operation IDs in APIM response")
    changes = []
    for proposed_id, title, path in ROUTES:
        matches = [
            item for item in operations
            if item.get("properties", {}).get("method", "").upper() == "GET"
            and item.get("properties", {}).get("urlTemplate", "").split("?", 1)[0] == path
        ]
        if len(matches) > 1:
            raise RuntimeError(f"Multiple GET operations match {path}")
        if not matches:
            if proposed_id in by_id:
                raise RuntimeError(f"Operation ID {proposed_id} already belongs to another route")
            changes.append(Change(proposed_id, title, path, create=True, replace_policy=True))
            continue
        current = matches[0]
        operation_id = current["id"].rsplit("/", 1)[-1]
        current_policy = _policy(API + f"/operations/{operation_id}/policies/policy")
        kind = policy_kind(current_policy, debate_base)
        if kind == "unexpected":
            raise RuntimeError(f"Unexpected DART operation policy on GET {path}; no changes made")
        changes.append(Change(operation_id, title, path, create=False,
                              replace_policy=kind == "legacy-debate"))
    return changes


def _apply(changes: list[Change]) -> None:
    for change in changes:
        operation = API + f"/operations/{change.operation_id}"
        if change.create:
            parameters = (
                [{"name": "receipt_no", "type": "string", "required": True}]
                if "{receipt_no}" in change.path else []
            )
            d.call(operation, VERSION, "PUT", {"properties": {
                "displayName": change.title,
                "method": "GET",
                "urlTemplate": change.path,
                "templateParameters": parameters,
                "responses": [],
            }})
        if change.replace_policy:
            d.call(operation + "/policies/policy", VERSION, "PUT",
                   {"properties": {"format": "rawxml", "value": BASE_POLICY}})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Apply the inspected APIM operation changes")
    parser.add_argument("--expected-image", help="Required with --apply: exact ready common API image")
    args = parser.parse_args()
    if args.apply and not args.expected_image:
        parser.error("--apply requires --expected-image")
    if not shutil.which("az"):
        parser.error("Azure CLI is required for read-only inspection and --apply")
    common, debate_base = _check_target()
    if args.apply:
        _check_common_ready(common, args.expected_image)
    changes = _plan(debate_base)
    for change in changes:
        actions = []
        if change.create:
            actions.append("create")
        if change.replace_policy:
            actions.append("inherit API policy")
        print(f"GET {change.path}: {', '.join(actions) if actions else 'already correct'}")
    if not args.apply:
        print("Dry run only. Pass --apply --expected-image IMAGE after the common API is ready.")
        return
    _apply(changes)
    print("DART operation routing updated; verify authenticated SWA requests.")


if __name__ == "__main__":
    main()
