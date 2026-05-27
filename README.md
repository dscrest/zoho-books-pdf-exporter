# Zoho Books PDF Exporter

A modular Python CLI to bulk-download **Sales Orders**, **Delivery Challans**, and **Transfer Orders** as PDFs from Zoho Books. Supports multiple Zoho accounts, interactive menus, incremental downloads, and automatic token refresh.

---

## Features

- Multi-account support (`.com` and `.in` data centres)
- Interactive pickers for account, organisation, and document type — with last-used defaults
- Incremental — skips already-downloaded files on repeat runs
- Per-account scope restriction (e.g. read-only DC + TO for live accounts)
- Automatic OAuth token refresh
- Configurable rate limiting to stay within Zoho API limits
- Date range filtering
- **Secure token storage** — tokens and client secrets stored in the OS keychain (macOS Keychain, Windows Credential Manager, Linux SecretService)

---

## Architecture

```
so-downloader-zb/
├── config.py              # Constants, active-account state
├── auth.py                # OAuth token management, keychain storage, account picker
├── api.py                 # HTTP layer, Zoho Books API calls
├── downloader.py          # PDF / attachment save logic
├── main.py                # CLI entry point, interactive menus
├── requirements.txt       # keyring dependency
├── accounts.json          # Your credentials (git-ignored)
├── accounts.example.json  # Template — copy to accounts.json
└── so-downloader.py       # Original monolith (reference only)
```

### Module responsibilities

| File | Responsibility |
|---|---|
| `config.py` | Directory paths, default endpoints, active-account context (module-level state shared across all modules) |
| `auth.py` | Load/save tokens via OS keychain, exchange auth codes, refresh access tokens, in-memory token cache, account picker UI, one-time migration from plain token files |
| `api.py` | Single `api_get()` function used everywhere, paginated document listing, organisation picker with last-used defaults |
| `downloader.py` | `download_pdf()` and `download_attachment()` — both generic, work for any document type |
| `main.py` | Argument parsing, account → org → module picker flow, `run_download()` loop |

### Runtime flow

```
python3 main.py
       │
       ▼
 select_account()          auth.py   — reads accounts.json, shows picker
       │
       ▼
 select_organization()     api.py    — uses org_id from account if set,
       │                              otherwise calls /organizations API
       ▼
 select_module()           main.py   — shows SO / DC / TO / All menu
       │                              (filtered by account's allowed_types)
       ▼
 list_*()                  api.py    — paginated fetch (200/page)
       │
       ▼
 download_pdf()            downloader.py — skips if file exists,
                                           else fetches PDF with rate delay
```

### Token lifecycle

```
accounts.json ──► auth.py (first run: migrate to keychain)
                     │
                     ├── OS keychain (macOS / Windows / Linux)
                     │   tokens stored securely, never in plain files
                     │
                     ├── in-memory cache (_token_cache)
                     │   avoids keychain reads on every API call
                     │
                     └── auto-refresh when expires_at reached
                             │
                             ▼
                         save_tokens() ── updates keychain + cache
```

---

## Setup

### 1. Install dependencies

```bash
git clone https://github.com/dscrest/zoho-books-pdf-exporter.git
cd zoho-books-pdf-exporter
pip install -r requirements.txt
```

### 2. Create a Self Client in Zoho API Console

1. Go to [https://api-console.zoho.com](https://api-console.zoho.com) (or `zoho.in` for India accounts)
2. Create a **Self Client** app
3. Copy the **Client ID** and **Client Secret**

### 3. Configure accounts.json

```bash
cp accounts.example.json accounts.json
```

Then fill in your credentials:

```json
[
  {
    "name": "My Company",
    "client_id": "1000.XXXX",
    "client_secret": "XXXX",
    "scope": "ZohoBooks.fullaccess.all",
    "auth_base": "https://accounts.zoho.com/oauth/v2"
  }
]
```

> **Security note:** `client_secret` in `accounts.json` is only needed for the first run — it is automatically migrated to the OS keychain and removed from the file.

**All account fields:**

| Field | Required | Description |
|---|---|---|
| `name` | Yes | Display name shown in picker |
| `client_id` | Yes | From Zoho API Console |
| `client_secret` | First run only | Migrated to keychain automatically |
| `scope` | Yes | OAuth scope — see below |
| `auth_base` | No | `zoho.com` (default) or `zoho.in` |
| `org_id` | No | Skip org picker — use this org directly |
| `org_name` | No | Display name when org_id is set |
| `allowed_types` | No | Restrict to `["dc", "to"]` etc. Default: all |
| `rate_delay` | No | Seconds between PDF calls. Default: `0.25` |

**Scopes:**

| Use case | Scope |
|---|---|
| Full access | `ZohoBooks.fullaccess.all` |
| DC + TO only (live/restricted account) | `ZohoBooks.deliverychallans.READ,ZohoBooks.transferorders.READ` |
| SO only | `ZohoBooks.salesorders.READ` |

### 4. Authenticate

```bash
python3 auth.py
```

Follow the steps — generates a code in Zoho API Console, paste it when prompted. Tokens are stored securely in the OS keychain.

---

## Usage

```bash
# Interactive — account → org → module picker
python3 main.py

# Skip module picker
python3 main.py --type so       # Sales Orders
python3 main.py --type dc       # Delivery Challans
python3 main.py --type to       # Transfer Orders
python3 main.py --type all      # All permitted types

# Date filter (recommended for daily runs)
python3 main.py --from 2026-01-01
python3 main.py --from 2026-01-01 --to 2026-03-31

# Download uploaded attachments instead of generated PDFs
python3 main.py --attachments

# Skip org picker (for scripting)
python3 main.py --org 743418751
```

### Output structure

```
SalesOrders/
  SO-00176/
    SO-00176.pdf
DeliveryChallans/
  PSSRT-DC-00270/
    PSSRT-DC-00270.pdf
TransferOrders/
  TO-01807/
    TO-01807.pdf
```

---

## API consumption tips

Zoho Books allows ~2500 API calls/day on most plans. Each PDF download = 1 call.

**For daily incremental runs** (most efficient):
```bash
python3 main.py --from 2026-05-27   # only today's new documents
```

**For initial bulk download**, split by date range across multiple days:
```bash
python3 main.py --type dc --from 2025-01-01 --to 2025-06-30
python3 main.py --type dc --from 2025-07-01 --to 2025-12-31
```

Already-downloaded files are always skipped — safe to re-run.

Slow down if hitting rate limits:
```json
"rate_delay": 0.5
```

---

## Re-authenticating

Tokens auto-refresh during normal use. If a refresh token expires (after ~1 year):

```bash
python3 auth.py   # select the account to re-authenticate
```

---

## Security

- `accounts.json` is in `.gitignore` — never committed
- `client_secret` is stored in the OS keychain, not in any file
- Tokens are stored in the OS keychain, not in plain JSON files
- Use restricted scopes (`READ` only) for live/production accounts
- Keychain integration via the `keyring` library (macOS Keychain / Windows Credential Manager / Linux SecretService)
