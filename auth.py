"""
Zoho OAuth token management.

Tokens and client secrets are stored in the OS secure keychain (macOS Keychain,
Windows Credential Manager, Linux SecretService) via the `keyring` library.
Plain token files are never written.

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

import keyring

from config import (
    DEFAULT_AUTH_BASE,
    KEYRING_SERVICE,
    LASTUSED_FILE,
    get_active_account,
    load_accounts,
    set_active_account,
)


# ── Keyring helpers ───────────────────────────────────────────────────────────

def _kr_key(suffix: str) -> str:
    return f"{get_active_account()['name']}_{suffix}"


def _keyring_load_tokens() -> dict:
    raw = keyring.get_password(KEYRING_SERVICE, _kr_key("tokens"))
    return json.loads(raw) if raw else {}


def _keyring_save_tokens(tokens: dict) -> None:
    keyring.set_password(KEYRING_SERVICE, _kr_key("tokens"), json.dumps(tokens))


def get_client_secret() -> str:
    """Return client secret from keyring, falling back to accounts.json."""
    secret = keyring.get_password(KEYRING_SERVICE, _kr_key("secret"))
    if not secret:
        secret = get_active_account().get("client_secret", "")
    return secret


def store_client_secret(secret: str) -> None:
    keyring.set_password(KEYRING_SERVICE, _kr_key("secret"), secret)


# ── One-time migration from plain files ───────────────────────────────────────

def _migrate_if_needed() -> None:
    account = get_active_account()

    # Migrate token file → keyring (only if keychain is empty — never overwrite)
    token_file = Path(account.get("token_file", ""))
    if token_file.exists():
        try:
            if not _keyring_load_tokens():
                tokens = json.loads(token_file.read_text())
                _keyring_save_tokens(tokens)
                print(f"  Migrated tokens for '{account['name']}' → keychain")
            token_file.unlink()
        except Exception as e:
            print(f"  Warning: could not migrate token file: {e}")

    # Migrate client_secret from accounts.json → keyring
    if account.get("client_secret"):
        try:
            store_client_secret(account["client_secret"])
            _remove_secret_from_accounts_json(account["name"])
            print(f"  Migrated client_secret for '{account['name']}' → keychain")
        except Exception as e:
            print(f"  Warning: could not migrate client_secret: {e}")


def _remove_secret_from_accounts_json(account_name: str) -> None:
    from config import ACCOUNTS_FILE
    accounts = json.loads(ACCOUNTS_FILE.read_text())
    for a in accounts:
        if a["name"] == account_name and "client_secret" in a:
            del a["client_secret"]
    ACCOUNTS_FILE.write_text(json.dumps(accounts, indent=2))


# ── Token file (in-memory cache backed by keyring) ────────────────────────────

_token_cache: dict = {}


def _auth_base() -> str:
    return get_active_account().get("auth_base", DEFAULT_AUTH_BASE)


def load_tokens() -> dict:
    global _token_cache
    if _token_cache:
        return _token_cache
    _token_cache = _keyring_load_tokens()
    return _token_cache


def save_tokens(tokens: dict) -> None:
    global _token_cache
    _keyring_save_tokens(tokens)
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
        "client_secret": get_client_secret(),
        "code":          code.strip(),
    })
    if "error" in data:
        raise RuntimeError(f"Token exchange failed: {data}")
    data["expires_at"] = time.time() + data.get("expires_in", 3600) - 60
    data["scope"]      = account.get("scope", "")
    save_tokens(data)
    print(f"Tokens saved to keychain for '{account['name']}'")
    return data


def refresh_access_token(tokens: dict) -> dict:
    account = get_active_account()
    data = _post(f"{_auth_base()}/token", {
        "grant_type":    "refresh_token",
        "client_id":     account["client_id"],
        "client_secret": get_client_secret(),
        "refresh_token": tokens["refresh_token"],
    })
    if "error" in data:
        raise RuntimeError(f"Token refresh failed: {data}")
    tokens["access_token"] = data["access_token"]
    tokens["expires_at"]   = time.time() + data.get("expires_in", 3600) - 60
    save_tokens(tokens)
    return tokens


def get_access_token() -> str:
    account = get_active_account()
    tokens  = load_tokens()
    if not tokens:
        sys.exit(
            f"No tokens for '{account['name']}'.\n"
            "Run:  python3 auth.py  to authenticate."
        )
    # Warn if the token was issued for a different scope
    token_scope   = tokens.get("scope", "")
    account_scope = account.get("scope", "")
    if token_scope and account_scope and token_scope != account_scope:
        sys.exit(
            f"Scope mismatch for '{account['name']}'.\n"
            f"  Token scope  : {token_scope}\n"
            f"  Account scope: {account_scope}\n"
            "Run:  python3 auth.py  to re-authenticate with the updated scope."
        )
    if time.time() >= tokens.get("expires_at", 0):
        tokens = refresh_access_token(tokens)
    return tokens["access_token"]


# ── Last-used helpers ─────────────────────────────────────────────────────────

def load_last_used() -> dict:
    return json.loads(LASTUSED_FILE.read_text()) if LASTUSED_FILE.exists() else {}


def save_last_used(data: dict) -> None:
    current = load_last_used()
    current.update(data)
    LASTUSED_FILE.write_text(json.dumps(current, indent=2))


# ── Account picker ────────────────────────────────────────────────────────────

def select_account() -> dict:
    global _token_cache
    accounts = load_accounts()
    if not accounts:
        sys.exit("No accounts configured in accounts.json.")

    last_name = load_last_used().get("account")

    if len(accounts) == 1:
        account = accounts[0]
        set_active_account(account)
        _token_cache = {}
        _migrate_if_needed()
        return account

    print("\n┌─ Select Account " + "─" * 40)
    for i, a in enumerate(accounts):
        tag = "  ← last used" if a["name"] == last_name else ""
        print(f"│  [{i + 1}] {a['name']}{tag}")
    print("└" + "─" * 57)

    default_idx = next((i + 1 for i, a in enumerate(accounts) if a["name"] == last_name), None)
    prompt = f"Enter number [1–{len(accounts)}]"
    if default_idx:
        prompt += f", or Enter for [{last_name}]"

    while True:
        raw = input(f"{prompt}: ").strip()
        if not raw and default_idx:
            account = accounts[default_idx - 1]
            break
        if raw.isdigit() and 1 <= int(raw) <= len(accounts):
            account = accounts[int(raw) - 1]
            break
        print(f"  Please enter a number between 1 and {len(accounts)}.")

    set_active_account(account)
    _token_cache = {}
    _migrate_if_needed()
    save_last_used({"account": account["name"]})
    return account


# ── Interactive fresh-token flow (run this file directly) ─────────────────────

def interactive_auth() -> None:
    print("\n=== Zoho Books — Fresh Token Setup ===\n")

    account = select_account()
    scope   = account.get("scope", "ZohoBooks.fullaccess.all")

    # Prompt for client_secret if not in keyring or accounts.json
    secret = get_client_secret()
    if not secret:
        secret = input(f"Enter Client Secret for '{account['name']}': ").strip()
        if not secret:
            sys.exit("No client secret provided. Aborting.")
        store_client_secret(secret)
        print("  Client secret saved to keychain.")

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
        exchange_code(code)
        print(f"\nAuthentication successful for '{account['name']}'!")
        print("  Tokens stored securely in keychain.")
        print("\nYou can now run:  python3 main.py\n")
    except RuntimeError as e:
        sys.exit(f"\nError: {e}")


if __name__ == "__main__":
    interactive_auth()
