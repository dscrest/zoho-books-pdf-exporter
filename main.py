"""
Zoho Books — Document Downloader
==================================
Fresh auth:
    python3 auth.py

Download Sales Orders:
    python3 main.py --type so

Download Delivery Challans:
    python3 main.py --type dc

Download Transfer Orders:
    python3 main.py --type to

Download all three:
    python3 main.py --type all

Filter by date range:
    python3 main.py --type dc --from 2025-01-01 --to 2025-12-31

Download uploaded attachments instead of generated PDFs:
    python3 main.py --type so --attachments

Skip org picker (useful in scripts):
    python3 main.py --type so --org 743418751
"""

import argparse
import sys
from pathlib import Path

from api import (
    list_delivery_challans,
    list_sales_orders,
    list_transfer_orders,
    select_organization,
)
from auth import select_account
from config import (
    DIR_DELIVERY_CHALLANS,
    DIR_SALES_ORDERS,
    DIR_TRANSFER_ORDERS,
)
from downloader import download_attachment, download_pdf


# Maps doc type → (list_fn, api_endpoint, id_field, number_field, default_dir)
DOC_TYPES = {
    "so": (
        list_sales_orders,
        "salesorders",
        "salesorder_id",
        "salesorder_number",
        DIR_SALES_ORDERS,
    ),
    "dc": (
        list_delivery_challans,
        "deliverychallans",
        "deliverychallan_id",
        "deliverychallan_number",
        DIR_DELIVERY_CHALLANS,
    ),
    "to": (
        list_transfer_orders,
        "transferorders",
        "transfer_order_id",
        "transfer_order_number",
        DIR_TRANSFER_ORDERS,
    ),
}

TYPE_LABELS = {"so": "Sales Orders", "dc": "Delivery Challans", "to": "Transfer Orders"}


def select_module(allowed: list) -> str:
    options = {k: v for k, v in TYPE_LABELS.items() if k in allowed}
    options["all"] = "All (" + ", ".join(options.values()) + ")"

    keys = list(options.keys())
    print("\n┌─ Select Module " + "─" * 41)
    for i, k in enumerate(keys):
        print(f"│  [{i + 1}] {options[k]}")
    print("└" + "─" * 57)

    while True:
        raw = input(f"Enter number [1–{len(keys)}]: ").strip()
        if raw.isdigit() and 1 <= int(raw) <= len(keys):
            return keys[int(raw) - 1]
        print(f"  Please enter a number between 1 and {len(keys)}.")


def run_download(doc_type: str, org_id: str, org_name: str,
                 dest_dir: Path, attachments: bool,
                 date_from: str, date_to: str) -> None:
    list_fn, endpoint, id_field, number_field, _ = DOC_TYPES[doc_type]
    label = TYPE_LABELS[doc_type]

    dest_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n── {label} ──")
    print(f"   Output : {dest_dir.resolve()}")
    print(f"   Fetching...", end=" ", flush=True)

    docs = list_fn(org_id, date_from, date_to)
    print(f"{len(docs)} found\n")

    if not docs:
        print(f"   No {label} found for the given criteria.")
        return

    errors = []
    for i, doc in enumerate(docs, 1):
        doc_id     = doc.get(id_field, "")
        doc_number = doc.get(number_field, doc_id)
        doc_date   = doc.get("date", "")
        print(f"[{i:>4}/{len(docs)}] {doc_number:<22} {doc_date}", end="  ")
        try:
            if attachments:
                download_attachment(org_id, doc_id, doc_number, endpoint, dest_dir)
            else:
                download_pdf(org_id, doc_id, doc_number, endpoint, dest_dir)
        except Exception as e:
            print(f"ERROR: {e}")
            errors.append((doc_number, str(e)))

    print(f"\n   Done. {len(docs) - len(errors)}/{len(docs)} succeeded.")
    if errors:
        print("   Failed:")
        for num, msg in errors:
            print(f"     {num}: {msg}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download Zoho Books document PDFs",
        epilog="For fresh authentication run:  python3 auth.py",
    )
    parser.add_argument(
        "--type", dest="doc_type",
        choices=["so", "dc", "to", "all"],
        default=None,
        help="Skip module picker: so=Sales Orders, dc=Delivery Challans, to=Transfer Orders, all=all",
    )
    parser.add_argument("--attachments", action="store_true",
                        help="Download uploaded file attachments instead of generated PDFs")
    parser.add_argument("--from", dest="date_from", metavar="YYYY-MM-DD",
                        help="Only include documents on or after this date")
    parser.add_argument("--to",   dest="date_to",   metavar="YYYY-MM-DD",
                        help="Only include documents on or before this date")
    parser.add_argument("--org",  metavar="ORG_ID",
                        help="Organization ID — omit to get an interactive picker")
    args = parser.parse_args()

    account = select_account()
    org_id, org_name = select_organization(args.org)

    allowed = account.get("allowed_types", list(DOC_TYPES.keys()))

    # Interactive module picker (skip if --type was passed)
    if args.doc_type:
        selected = args.doc_type
    else:
        selected = select_module(allowed)

    if selected == "all":
        types_to_run = [t for t in DOC_TYPES.keys() if t in allowed]
    else:
        if selected not in allowed:
            sys.exit(f"Account '{account['name']}' does not have access to '{selected}'.")
        types_to_run = [selected]

    for doc_type in types_to_run:
        dest_dir = DOC_TYPES[doc_type][4]
        run_download(
            doc_type, org_id, org_name,
            dest_dir,
            args.attachments,
            args.date_from, args.date_to,
        )

    print("\nAll done.")


if __name__ == "__main__":
    main()
