# Zoho Books PDF Exporter

A modular Python CLI to bulk-download **Sales Orders**, **Delivery Challans**, and **Transfer Orders** as PDFs from Zoho Books. Supports multiple Zoho accounts, interactive menus, incremental downloads, and automatic token refresh.

---

## Features

- Multi-account support (`.com` and `.in` data centres)
- Interactive pickers for account, organisation, and document type
- Incremental — skips already-downloaded files on repeat runs
- Per-account scope restriction (e.g. read-only DC + TO for live accounts)
- Automatic OAuth token refresh
- Configurable rate limiting to stay within Zoho API limits
- Date range filtering

---

## Architecture

```
so-downloader-zb/
├── config.py          # Constants, active-account state
├── auth.py            # OAuth token management, account picker
├── api.py             # HTTP layer, Zoho Books API calls
├── downloader.py      # PDF / attachment save logic
├── main.py            # CLI entry point, interactive menus
├── accounts.json      # Your credentials (git-ignored)
├── accounts.example.json  # Template — copy to accounts.json
└── tokens/            # Saved OAuth tokens (git-ignored)
    ├── octfis.json
    └── praveg.json
```

### Module responsibilities

| File | Responsibility |
|---|---|
| `config.py` | Directory paths, default endpoints, active-account context (module-level state shared across all modules) |
| `auth.py` | Load/save tokens, exchange auth codes, refresh access tokens, in-memory token cache, account picker UI |
| `api.py` | Single `api_get()` function used everywhere, paginated document listing, organisation picker, in-memory API base cache |
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
accounts.json ──► auth.py (load_tokens)
                     │
                     ├── in-memory cache (_token_cache)
                     │   avoids disk reads on every API call
                     │
                     └── auto-refresh when expires_at reached
                             │
                             ▼
                         save_tokens() ── updates cache + disk
```

---

## Setup

### 1. Install (no dependencies — stdlib only)

```bash
git clone https://github.com/dscrest/zoho-books-pdf-exporter.git
cd zoho-books-pdf-exporter
cp accounts.example.json accounts.json
```

### 2. Create a Self Client in Zoho API Console

1. Go to [https://api-console.zoho.com](https://api-console.zoho.com) (or `zoho.in` for India accounts)
2. Create a **Self Client** app
3. Copy the **Client ID** and **Client Secret** into `accounts.json`

### 3. Configure accounts.json

```json
[
  {
    "name": "My Company",
    "client_id": "1000.XXXX",
    "client_secret": "XXXX",
    "token_file": "tokens/mycompany.json",
    "scope": "ZohoBooks.fullaccess.all",
    "auth_base": "https://accounts.zoho.com/oauth/v2"
  }
]
```

**All account fields:**

| Field | Required | Description |
|---|---|---|
| `name` | Yes | Display name shown in picker |
| `client_id` | Yes | From Zoho API Console |
| `client_secret` | Yes | From Zoho API Console |
| `token_file` | Yes | Where to store tokens (relative path) |
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

Follow the steps — generates a code in Zoho API Console, paste it when prompted. Tokens are saved to `tokens/`.

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

## Security notes

- `accounts.json` and `tokens/` are in `.gitignore` — never committed
- Use restricted scopes (`READ` only) for live/production accounts
- Tokens are stored locally in `tokens/` — keep this directory private
