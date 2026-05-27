"""
Zoho Books - Sales Order PDF Downloader
Downloads SO PDFs and/or file attachments from Zoho Books.

SETUP:
  1. Run with --auth to generate a new authorization URL, open it in browser,
     then run --token <code> to exchange the code for tokens.
  2. After first auth, tokens are cached in zoho_tokens.json and auto-refreshed.

USAGE:
  python so-downloader.py --auth              # Step 1: get auth URL
  python so-downloader.py --token <code>      # Step 2: exchange code for tokens
  python so-downloader.py                     # Download all SO PDFs
  python so-downloader.py --attachments       # Download file attachments instead
  python so-downloader.py --from 2025-01-01 --to 2025-12-31  # Filter by date range
"""

import os
import sys
import json
import time
import argparse
import urllib.parse
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime

# ── Config ────────────────────────────────────────────────────────────────────
CLIENT_ID     = "1000.2XADEAGGLIMJI9GGYSL9OBZBLJOTZB"
CLIENT_SECRET = "e0c04ac689e29f21a17e568d0e223acac03fe0ad3a"
REDIRECT_URI  = "https://www.zoho.com"
SCOPE         = "ZohoBooks.salesorders.READ"
TOKEN_FILE    = Path("zoho_tokens.json")
DOWNLOAD_DIR  = Path("OCTFIS SO")

# Zoho US endpoints
AUTH_BASE  = "https://accounts.zoho.com/oauth/v2"
API_BASE   = "https://www.zohoapis.com/books/v3"
# ──────────────────────────────────────────────────────────────────────────────


def _http(method, url, headers=None, data=None):
    """Minimal HTTP helper (no external deps required)."""
    if data and isinstance(data, dict):
        data = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req) as r:
            body = r.read()
            ct   = r.headers.get("Content-Type", "")
            return r.status, body, ct
    except urllib.error.HTTPError as e:
        return e.code, e.read(), ""


def load_tokens():
    if TOKEN_FILE.exists():
        return json.loads(TOKEN_FILE.read_text())
    return {}


def save_tokens(tokens):
    TOKEN_FILE.write_text(json.dumps(tokens, indent=2))


def get_auth_url():
    params = urllib.parse.urlencode({
        "scope":         SCOPE,
        "client_id":     CLIENT_ID,
        "response_type": "code",
        "redirect_uri":  REDIRECT_URI,
        "access_type":   "offline",
    })
    return f"{AUTH_BASE}/auth?{params}"


def exchange_code(code):
    """Exchange authorization code → access + refresh tokens."""
    status, body, _ = _http("POST", f"{AUTH_BASE}/token", data={
        "grant_type":    "authorization_code",
        "client_id":     CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "redirect_uri":  REDIRECT_URI,
        "code":          code.strip(),
    })
    data = json.loads(body)
    if "error" in data:
        raise RuntimeError(f"Token exchange failed: {data}")
    data["expires_at"] = time.time() + data.get("expires_in", 3600) - 60
    save_tokens(data)
    print("✓ Tokens saved to", TOKEN_FILE)
    return data


def refresh_access_token(tokens):
    status, body, _ = _http("POST", f"{AUTH_BASE}/token", data={
        "grant_type":    "refresh_token",
        "client_id":     CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "refresh_token": tokens["refresh_token"],
    })
    data = json.loads(body)
    if "error" in data:
        raise RuntimeError(f"Token refresh failed: {data}")
    tokens["access_token"] = data["access_token"]
    tokens["expires_at"]   = time.time() + data.get("expires_in", 3600) - 60
    save_tokens(tokens)
    return tokens


def get_access_token():
    tokens = load_tokens()
    if not tokens:
        sys.exit("No tokens found. Run:  python so-downloader.py --auth  to start.")
    if time.time() >= tokens.get("expires_at", 0):
        print("Access token expired — refreshing...")
        tokens = refresh_access_token(tokens)
    return tokens["access_token"]


def api_get(path, params=None, *, raw=False):
    token = get_access_token()
    url   = f"{API_BASE}/{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    status, body, ct = _http("GET", url, headers={"Authorization": f"Zoho-oauthtoken {token}"})
    if status != 200:
        raise RuntimeError(f"API error {status}: {body[:200]}")
    if raw:
        return body, ct
    return json.loads(body)


def get_organization_id():
    data = api_get("organizations")
    orgs = data.get("organizations", [])
    if not orgs:
        raise RuntimeError("No organizations found.")
    if len(orgs) == 1:
        return orgs[0]["organization_id"], orgs[0]["name"]
    # Multiple orgs — list and let user pick
    print("\nMultiple organizations found:")
    for i, o in enumerate(orgs):
        print(f"  [{i}] {o['name']}  ({o['organization_id']})")
    idx = int(input("Select [0]: ").strip() or "0")
    return orgs[idx]["organization_id"], orgs[idx]["name"]


def list_sales_orders(org_id, date_from=None, date_to=None):
    """Return all SOs, handling pagination."""
    orders = []
    page   = 1
    while True:
        params = {"organization_id": org_id, "page": page, "per_page": 200}
        if date_from:
            params["date_start"] = date_from
        if date_to:
            params["date_end"] = date_to
        data = api_get("salesorders", params)
        batch = data.get("salesorders", [])
        orders.extend(batch)
        info = data.get("page_context", {})
        if not info.get("has_more_page", False):
            break
        page += 1
    return orders


def _safe_name(name):
    """Replace path-unsafe characters so SO numbers can be used as dir/file names."""
    return name.replace("/", "_").replace("\\", "_").replace(":", "_")


def download_so_pdf(org_id, so_id, so_number, dest_dir):
    """Download the generated PDF for a Sales Order into dest_dir/<so_number>/."""
    safe     = _safe_name(so_number)
    so_dir   = dest_dir / safe
    so_dir.mkdir(parents=True, exist_ok=True)
    out_path = so_dir / f"{safe}.pdf"
    if out_path.exists():
        print(f"  skip  {safe}/{safe}.pdf (already exists)")
        return
    body, ct = api_get(f"salesorders/{so_id}", {"organization_id": org_id, "accept": "pdf"}, raw=True)
    if "pdf" not in ct.lower() and not body.startswith(b"%PDF"):
        try:
            info = json.loads(body)
            print(f"  warn  {so_number}: unexpected response — {info}")
            return
        except Exception:
            pass
    out_path.write_bytes(body)
    print(f"  saved {safe}/{safe}.pdf  ({len(body)//1024} KB)")


def download_so_attachments(org_id, so_id, so_number, dest_dir):
    """Download uploaded file attachments on a Sales Order into dest_dir/<so_number>/."""
    safe   = _safe_name(so_number)
    so_dir = dest_dir / safe
    try:
        body, ct = api_get(
            f"salesorders/{so_id}/attachment",
            {"organization_id": org_id},
            raw=True,
        )
    except RuntimeError as e:
        if "404" in str(e):
            return  # no attachment
        raise
    # Zoho returns the raw file bytes
    # Try to infer extension from Content-Type
    ext = ".bin"
    if "pdf" in ct:
        ext = ".pdf"
    elif "png" in ct:
        ext = ".png"
    elif "jpeg" in ct or "jpg" in ct:
        ext = ".jpg"
    elif "zip" in ct:
        ext = ".zip"

    so_dir.mkdir(parents=True, exist_ok=True)
    out_path = so_dir / f"attachment{ext}"
    if out_path.exists():
        print(f"  skip  {so_number}/attachment{ext}")
        return
    out_path.write_bytes(body)
    print(f"  saved {out_path}  ({len(body)//1024} KB)")


# ── CLI ────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Download Zoho Books SO PDFs")
    parser.add_argument("--auth",        action="store_true",  help="Print authorization URL")
    parser.add_argument("--token",       metavar="CODE",       help="Exchange auth code for tokens")
    parser.add_argument("--attachments", action="store_true",  help="Download file attachments instead of generated PDFs")
    parser.add_argument("--from",        dest="date_from",     metavar="YYYY-MM-DD", help="Filter SOs from this date")
    parser.add_argument("--to",          dest="date_to",       metavar="YYYY-MM-DD", help="Filter SOs up to this date")
    parser.add_argument("--org",         metavar="ORG_ID",     help="Skip org selection, use this ID directly")
    parser.add_argument("--out",         default="OCTFIS SO", metavar="DIR", help="Output directory (default: OCTFIS SO)")
    args = parser.parse_args()

    # ── Auth steps ──
    if args.auth:
        url = get_auth_url()
        print("\nOpen this URL in your browser, approve access, then copy the 'code' param from the redirect URL:\n")
        print(url)
        print("\nThen run:  python so-downloader.py --token <code>\n")
        return

    if args.token:
        exchange_code(args.token)
        return

    # ── Download ──
    dest = Path(args.out)
    dest.mkdir(parents=True, exist_ok=True)

    if args.org:
        org_id   = args.org
        org_name = org_id
    else:
        org_id, org_name = get_organization_id()

    print(f"\nOrganization : {org_name} ({org_id})")
    print(f"Output dir   : {dest.resolve()}")

    print("\nFetching Sales Orders...", end=" ", flush=True)
    orders = list_sales_orders(org_id, args.date_from, args.date_to)
    print(f"{len(orders)} found\n")

    if not orders:
        print("No Sales Orders found for the given criteria.")
        return

    errors = []
    for i, so in enumerate(orders, 1):
        so_id     = so["salesorder_id"]
        so_number = so.get("salesorder_number", so_id)
        so_date   = so.get("date", "")
        print(f"[{i:>4}/{len(orders)}] {so_number}  {so_date}", end="  ")
        try:
            if args.attachments:
                download_so_attachments(org_id, so_id, so_number, dest)
            else:
                download_so_pdf(org_id, so_id, so_number, dest)
        except Exception as e:
            print(f"ERROR: {e}")
            errors.append((so_number, str(e)))

    print(f"\nDone. {len(orders) - len(errors)}/{len(orders)} succeeded.")
    if errors:
        print("\nFailed:")
        for num, msg in errors:
            print(f"  {num}: {msg}")


if __name__ == "__main__":
    main()
