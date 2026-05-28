"""Zoho Books API — HTTP helper and data-fetching functions."""

import json
import urllib.error
import urllib.parse
import urllib.request

import time

from auth import get_access_token, load_tokens
from config import DEFAULT_API_BASE

_api_base_cache: str = ""


# ── HTTP ──────────────────────────────────────────────────────────────────────

def _http(method: str, url: str, headers: dict = None, data: dict = None):
    if data and isinstance(data, dict):
        data = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, r.read(), r.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        return e.code, e.read(), ""


def _api_base() -> str:
    global _api_base_cache
    if not _api_base_cache:
        domain = load_tokens().get("api_domain", "").rstrip("/")
        _api_base_cache = f"{domain}/books/v3" if domain else DEFAULT_API_BASE
    return _api_base_cache


def api_get(path: str, params: dict = None, *, raw: bool = False, _delay: float = 0.0):
    token = get_access_token()
    url   = f"{_api_base()}/{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    if _delay:
        time.sleep(_delay)
    status, body, ct = _http(
        "GET", url,
        headers={"Authorization": f"Zoho-oauthtoken {token}"},
    )
    if status != 200:
        raise RuntimeError(f"API error {status}: {body[:200]}")
    return (body, ct) if raw else json.loads(body)


# ── Organizations ─────────────────────────────────────────────────────────────

def select_organization(preselected_id: str = None) -> tuple[str, str]:
    """Fetch all orgs and prompt the user to pick one.

    If preselected_id is given (via --org flag or accounts.json), skip the prompt.
    """
    from auth import load_last_used, save_last_used
    from config import get_active_account
    account = get_active_account()

    # Account-level org_id takes priority (avoids needing org scope)
    org_id = preselected_id or account.get("org_id")
    if org_id:
        org_name = account.get("org_name", org_id)
        print(f"Organization : {org_name} ({org_id})")
        return org_id, org_name

    data = api_get("organizations")
    orgs = data.get("organizations", [])
    if not orgs:
        raise RuntimeError("No organizations found.")

    last_org_id = load_last_used().get(f"org_{account['name']}")
    default_idx = next((i + 1 for i, o in enumerate(orgs) if o["organization_id"] == last_org_id), None)
    last_org_name = next((o["name"] for o in orgs if o["organization_id"] == last_org_id), None)

    print("\n┌─ Select Organization " + "─" * 35)
    for i, o in enumerate(orgs):
        tag = "  ← last used" if o["organization_id"] == last_org_id else ""
        print(f"│  [{i + 1}] {o['name']:<30} (ID: {o['organization_id']}){tag}")
    print("└" + "─" * 57)

    prompt = f"Enter number [1–{len(orgs)}]"
    if default_idx:
        prompt += f", or Enter for [{last_org_name}]"

    while True:
        raw = input(f"{prompt}: ").strip()
        if not raw and default_idx:
            chosen = orgs[default_idx - 1]
            break
        if raw.isdigit() and 1 <= int(raw) <= len(orgs):
            chosen = orgs[int(raw) - 1]
            break
        print(f"  Please enter a number between 1 and {len(orgs)}.")

    save_last_used({f"org_{account['name']}": chosen["organization_id"]})
    return chosen["organization_id"], chosen["name"]


# ── Generic paginated list ────────────────────────────────────────────────────

def _list_documents(endpoint: str, result_key: str, org_id: str,
                    date_from: str = None, date_to: str = None) -> list:
    docs, page = [], 1
    while True:
        params = {"organization_id": org_id, "page": page, "per_page": 200}
        if date_from:
            params["date_start"] = date_from
        if date_to:
            params["date_end"] = date_to
        data  = api_get(endpoint, params)
        batch = data.get(result_key, [])
        docs.extend(batch)
        if not data.get("page_context", {}).get("has_more_page", False):
            break
        page += 1
    return docs


# ── Sales Orders ──────────────────────────────────────────────────────────────

def list_sales_orders(org_id: str, date_from: str = None, date_to: str = None) -> list:
    return _list_documents("salesorders", "salesorders", org_id, date_from, date_to)


# ── Delivery Challans ─────────────────────────────────────────────────────────

def list_delivery_challans(org_id: str, date_from: str = None, date_to: str = None) -> list:
    return _list_documents("deliverychallans", "deliverychallans", org_id, date_from, date_to)


# ── Transfer Orders ───────────────────────────────────────────────────────────

def list_transfer_orders(org_id: str, date_from: str = None, date_to: str = None) -> list:
    return _list_documents("transferorders", "transfer_orders", org_id, date_from, date_to)


# ── Inventory Adjustments ─────────────────────────────────────────────────────

def list_inventory_adjustments(org_id: str, date_from: str = None, date_to: str = None) -> list:
    return _list_documents("inventoryadjustments", "inventory_adjustments", org_id, date_from, date_to)
