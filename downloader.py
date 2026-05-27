"""Download logic — PDFs and file attachments for any Zoho Books document type."""

import json
from pathlib import Path

from api import api_get
from config import get_active_account


def _safe_name(name: str) -> str:
    return name.replace("/", "_").replace("\\", "_").replace(":", "_")


def _rate_delay() -> float:
    """Seconds to wait between API calls. Configurable per account in accounts.json."""
    return float(get_active_account().get("rate_delay", 0.25))


def download_pdf(org_id: str, doc_id: str, doc_number: str,
                 api_endpoint: str, dest_dir: Path) -> None:
    safe     = _safe_name(doc_number)
    doc_dir  = dest_dir / safe
    doc_dir.mkdir(parents=True, exist_ok=True)
    out_path = doc_dir / f"{safe}.pdf"

    if out_path.exists():
        print(f"  skip  {safe}/{safe}.pdf (already exists)")
        return

    body, ct = api_get(
        f"{api_endpoint}/{doc_id}",
        {"organization_id": org_id, "accept": "pdf"},
        raw=True,
        _delay=_rate_delay(),
    )

    if "pdf" not in ct.lower() and not body.startswith(b"%PDF"):
        try:
            print(f"  warn  {doc_number}: unexpected response — {json.loads(body)}")
        except Exception:
            pass
        return

    out_path.write_bytes(body)
    print(f"  saved {safe}/{safe}.pdf  ({len(body) // 1024} KB)")


def download_attachment(org_id: str, doc_id: str, doc_number: str,
                        api_endpoint: str, dest_dir: Path) -> None:
    safe    = _safe_name(doc_number)
    doc_dir = dest_dir / safe

    try:
        body, ct = api_get(
            f"{api_endpoint}/{doc_id}/attachment",
            {"organization_id": org_id},
            raw=True,
            _delay=_rate_delay(),
        )
    except RuntimeError as e:
        if "404" in str(e):
            return
        raise

    ext = ".bin"
    if   "pdf"  in ct:                  ext = ".pdf"
    elif "png"  in ct:                  ext = ".png"
    elif "jpeg" in ct or "jpg" in ct:   ext = ".jpg"
    elif "zip"  in ct:                  ext = ".zip"

    doc_dir.mkdir(parents=True, exist_ok=True)
    out_path = doc_dir / f"attachment{ext}"

    if out_path.exists():
        print(f"  skip  {safe}/attachment{ext} (already exists)")
        return

    out_path.write_bytes(body)
    print(f"  saved {safe}/attachment{ext}  ({len(body) // 1024} KB)")
