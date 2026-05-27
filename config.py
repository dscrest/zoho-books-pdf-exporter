import json
from pathlib import Path

ACCOUNTS_FILE = Path("accounts.json")
TOKENS_DIR    = Path("tokens")

DEFAULT_AUTH_BASE = "https://accounts.zoho.com/oauth/v2"
DEFAULT_API_BASE  = "https://www.zohoapis.com/books/v3"

DIR_SALES_ORDERS      = Path("SalesOrders")
DIR_DELIVERY_CHALLANS = Path("DeliveryChallans")
DIR_TRANSFER_ORDERS   = Path("TransferOrders")

_active_account: dict = None


def load_accounts() -> list[dict]:
    if not ACCOUNTS_FILE.exists():
        raise RuntimeError(
            f"{ACCOUNTS_FILE} not found. "
            "Create it with your Zoho API credentials."
        )
    accounts = json.loads(ACCOUNTS_FILE.read_text())
    return [a for a in accounts if a.get("client_id")]


def set_active_account(account: dict) -> None:
    global _active_account
    _active_account = account


def get_active_account() -> dict:
    if _active_account is None:
        raise RuntimeError("No account selected. Run main.py to start.")
    return _active_account
