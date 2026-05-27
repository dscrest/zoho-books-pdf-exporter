"""
Zoho OAuth token management.

Run directly for a guided fresh-token flow:
    python3 auth.py
"""

import json
import sys
import time
import urllib.parse
import urllib.request
import urllib.error
from pathlib import Path

from config import DEFAULT_AUTH_BASE, get_active_account, load_accounts, set_active_account


# ── Token file ────────────────────────────────────────────────────────────────

_token_cache: dict = {}


def _token_path() -> Path:
    return Path(get_active_account()["token_file"])


def _auth_base() -> str:
    return get_active_account().get("auth_base", DEFAULT_AUTH_BASE)


def load_tokens() -> dict:
    global _token_cache
    if _token_cache:
        return _token_cache
    path = _token_path()
    _token_cache = json.loads(path.read_text()) if path.exists() else {}
    return _token_cache


def save_tokens(tokens: dict) -> None:
    global _token_cache
    path = _token_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(tokens, indent=2))
    _token_cache = tokens


# ── OAuth helpers ─────────────────────────────────────────────────────────────

def _post(url: str, data: dict) -> dict:
    body = urllib.parse.urlencode(data).encode()
    req  = urllib.request.Request(url, data=body, method="POST")
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return json.loads(e.read())


def exchange_code(code: str) -> dict:
    account = get_active_account()
    data = _post(f"{_auth_base()}/token", {
        "grant_type":    "authorization_code",
        "client_id":     account["client_id"],
        "client_secret": account["client_secret"],
        "code":          code.strip(),
    })
    if "error" in data:
        raise RuntimeError(f"Token exchange failed: {data}")
    data["expires_at"] = time.time() + data.get("expires_in", 3600) - 60
    save_tokens(data)
    print(f"Tokens saved to {_token_path()}")
    return data


def refresh_access_token(tokens: dict) -> dict:
    account = get_active_account()
    data = _post(f"{_auth_base()}/token", {
        "grant_type":    "refresh_token",
        "client_id":     account["client_id"],
        "client_secret": account["client_secret"],
        "refresh_token": tokens["refresh_token"],
    })
    if "error" in data:
        raise RuntimeError(f"Token refresh failed: {data}")
    tokens["access_token"] = data["access_token"]
    tokens["expires_at"]   = time.time() + data.get("expires_in", 3600) - 60
    save_tokens(tokens)
    return tokens


def get_access_token() -> str:
    tokens = load_tokens()
    if not tokens:
        sys.exit(
            f"No tokens for account '{get_active_account()['name']}'.\n"
            "Run:  python3 auth.py  to authenticate."
        )
    if time.time() >= tokens.get("expires_at", 0):
        tokens = refresh_access_token(tokens)
    return tokens["access_token"]


# ── Account picker ────────────────────────────────────────────────────────────

def select_account() -> dict:
    accounts = load_accounts()
    if not accounts:
        sys.exit("No accounts configured in accounts.json.")

    if len(accounts) == 1:
        account = accounts[0]
        print(f"Account : {account['name']}")
        set_active_account(account)
        return account

    print("\n┌─ Select Account " + "─" * 40)
    for i, a in enumerate(accounts):
        print(f"│  [{i + 1}] {a['name']}")
    print("└" + "─" * 57)

    while True:
        raw = input(f"Enter number [1–{len(accounts)}]: ").strip()
        if raw.isdigit() and 1 <= int(raw) <= len(accounts):
            account = accounts[int(raw) - 1]
            set_active_account(account)
            return account
        print(f"  Please enter a number between 1 and {len(accounts)}.")


# ── Interactive fresh-token flow (run this file directly) ─────────────────────

def interactive_auth() -> None:
    print("\n=== Zoho Books — Fresh Token Setup ===\n")

    account = select_account()
    scope = account.get("scope", "ZohoBooks.fullaccess.all")
    print(f"\nSetting up tokens for: {account['name']}")
    print("-" * 40)
    print("1. Go to  https://api-console.zoho.com")
    print("2. Open your Self Client app")
    print("3. Click 'Generate Code'")
    print(f"4. Enter scope:  {scope}")
    print("5. Set duration: 10 minutes")
    print("6. Copy the generated code\n")

    code = input("Paste the code here and press Enter: ").strip()
    if not code:
        sys.exit("No code entered. Aborting.")

    try:
        tokens = exchange_code(code)
        print(f"\nAuthentication successful for '{account['name']}'!")
        print(f"  Token file : {_token_path()}")
        print("\nYou can now run:  python3 main.py\n")
    except RuntimeError as e:
        sys.exit(f"\nError: {e}")


if __name__ == "__main__":
    interactive_auth()
