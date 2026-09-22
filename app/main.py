"""
AP Open Item Validation RPA - entry point.

Phase 0/1 (always run): attach to the logged-in SAP GUI session, open
the custom AP Open Item transaction, search Open Items for the given
Company Code + Posting Date range, read the full result grid, export it
to Excel (Source_Row preserved).

Optional phases, each behind a flag:
  --with-detail       Phase 2: per-item Commercial Invoice detail screen
                       (Incoterm/FOB, cross-check fields).
  --with-attachments  Phase 3: per-item real attachments via FB03's
                       standard GOS "Attachment list" (see
                       sap/gos_attachment.py - NOT the AP Open Item
                       transaction's own Files popup, which was confirmed
                       live 2026-09-15 to be the wrong mechanism for this
                       business).
  --with-validation   Phase 5: full GREEN/YELLOW/RED validation (implies
                       --with-attachments and --with-detail).

Usage:
    python app/main.py --end-date 2026-09-14
    python app/main.py                      (prompts for the end date)
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sap.connection import SapConnectionError, attach_session, get_session_info  # noqa: E402
from sap.ap_open_item import SearchCriteria, APOpenItemError, TCODE, open_and_search, read_grid_rows  # noqa: E402
from sap.navigation import open_transaction  # noqa: E402
from sap.document_detail import process_item_details  # noqa: E402
from sap.gos_attachment import process_gos_attachments  # noqa: E402
from documents.file_extractor import extract_components  # noqa: E402
from documents.evaluator import AttachmentEvaluation, evaluate_components  # noqa: E402
from validation.engine import validate_item  # noqa: E402
from report.excel_report import write_raw_grid_report  # noqa: E402
from report.summary import summarize  # noqa: E402

CONFIG_PATH = ROOT / "config" / "settings.json"
LOG_DIR = ROOT / "logs"
OUTPUT_DIR = ROOT / "output"
ATTACHMENTS_DIR = ROOT / "attachments"


def load_settings() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def setup_logging() -> Path:
    LOG_DIR.mkdir(exist_ok=True)
    log_path = LOG_DIR / f"{datetime.now().strftime('%Y-%m-%d_%H%M%S')}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(log_path, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    return log_path


def parse_end_date(value: str) -> date:
    if value.strip().lower() == "today":
        return date.today()
    for fmt in ("%Y-%m-%d", "%Y.%m.%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Could not parse end date '{value}'. Use YYYY-MM-DD.")


def main() -> int:
    parser = argparse.ArgumentParser(description=f"{TCODE} Open Item -> raw Excel export (Phase 1)")
    parser.add_argument("--end-date", type=str, default=None, help="End date (YYYY-MM-DD). Start date = end date - lookback_years.")
    parser.add_argument(
        "--with-detail",
        action="store_true",
        help="Phase 2: also open each item's invoice detail screen (slow - "
             "SAP-side render time per item) and add an AP_OPEN_ITEMS_DETAIL sheet.",
    )
    parser.add_argument(
        "--with-attachments",
        action="store_true",
        help="Phase 3: for each item, open its Accounting Document in FB03 "
             "and check the standard GOS 'Attachment list' (the mechanism "
             "actually used for real trade documents - confirmed live "
             "2026-09-15, NOT the AP Open Item transaction's own Files/DICON "
             "popup), downloading any attachments into "
             "attachments/Source_Row_<n>/ and adding an "
             "AP_OPEN_ITEMS_ATTACHMENTS sheet.",
    )
    parser.add_argument(
        "--with-validation",
        action="store_true",
        help="Phase 5: run full GREEN/YELLOW/RED validation (vendor/amount/"
             "currency/posting-date/consignee/required-docs) using downloaded "
             "attachments, adding SUMMARY and VALIDATION_RESULT sheets. "
             "Implies --with-attachments and --with-detail (needed for Incoterm/FOB).",
    )
    args = parser.parse_args()
    if args.with_validation:
        args.with_attachments = True
        args.with_detail = True

    log_path = setup_logging()
    log = logging.getLogger(__name__)
    settings = load_settings()

    end_date_str = args.end_date
    if not end_date_str:
        end_date_str = input("Enter End Date (YYYY-MM-DD): ").strip()

    try:
        end_date = parse_end_date(end_date_str)
    except ValueError as exc:
        log.error(str(exc))
        return 1

    criteria = SearchCriteria.from_end_date(
        company_code=settings["company_code"],
        end_date=end_date,
        lookback_years=settings["lookback_years"],
        open_items_only=settings["open_items_only"],
    )

    log.info("Starting run. Log file: %s", log_path)
    log.info(
        "Search criteria: company_code=%s start_date=%s end_date=%s open_items_only=%s",
        criteria.company_code, criteria.start_date, criteria.end_date, criteria.open_items_only,
    )

    try:
        session = attach_session()
    except SapConnectionError as exc:
        log.error("Could not attach to SAP: %s", exc)
        return 1

    info = get_session_info(session)
    log.info(
        "Attached to SAP session: system=%s client=%s user=%s transaction=%s",
        info.get("SystemName"), info.get("Client"), info.get("User"), info.get("Transaction"),
    )

    try:
        open_and_search(session, criteria, sap_date_format=settings["sap_date_format"])
    except APOpenItemError as exc:
        log.error("%s search failed: %s", TCODE, exc)
        return 1

    log.info("Execute succeeded. Reading result grid...")

    try:
        rows = read_grid_rows(session)
    except APOpenItemError as exc:
        log.error("Failed to read result grid: %s", exc)
        return 1

    item_count = sum(1 for r in rows if r.get("Row_Type") == "ITEM")
    subtotal_count = len(rows) - item_count
    log.info(
        "Read %d row(s) from %s (Source_Row preserved): %d item(s), %d subtotal row(s).",
        len(rows), TCODE, item_count, subtotal_count,
    )

    detail_rows = None
    if args.with_detail:
        log.info("Phase 2: opening invoice detail for %d item(s) (this is slow - SAP-side render time)...", item_count)
        detail_rows = process_item_details(session, rows, logger=log)
        ok_count = sum(1 for d in detail_rows if d.get("Detail_Status") == "OK")
        err_count = len(detail_rows) - ok_count
        log.info("Phase 2 done: %d OK, %d error(s).", ok_count, err_count)

    attachment_rows = None
    if args.with_attachments:
        log.info("Phase 3: checking GOS attachments (via FB03) for %d item(s)...", item_count)
        attachment_rows = process_gos_attachments(
            session, rows, dest_root=ATTACHMENTS_DIR, company_code=criteria.company_code, logger=log,
        )
        with_files = sum(1 for a in attachment_rows if a.get("Attachment_Count", 0) > 0)
        att_err = sum(1 for a in attachment_rows if a.get("Attachment_Status") == "ERROR")
        log.info("Phase 3 done: %d item(s) had attachments, %d error(s).", with_files, att_err)

        # process_gos_attachments leaves the session on FB03, not the AP Open Item transaction -
        # re-navigate back in case anything later needs the grid again.
        try:
            open_transaction(session, TCODE)
            open_and_search(session, criteria, sap_date_format=settings["sap_date_format"])
        except APOpenItemError as exc:
            log.warning("Could not re-navigate back to %s after Phase 3: %s", TCODE, exc)

    validation_results = None
    summary_stats = None
    if args.with_validation:
        log.info("Phase 5: running validation for %d item(s)...", item_count)
        incoterm_by_row = {d["Source_Row"]: d.get("Incoterm") for d in (detail_rows or [])}
        paths_by_row = {a["Source_Row"]: a.get("Downloaded_Paths") or [] for a in (attachment_rows or [])}

        validation_results = []
        for row in rows:
            if row.get("Row_Type") != "ITEM":
                continue
            source_row = row["Source_Row"]
            downloaded_paths = paths_by_row.get(source_row, [])

            components = []
            for path in downloaded_paths:
                try:
                    components.extend(extract_components(path))
                except ValueError as exc:
                    log.warning("Row %s: could not extract '%s' (%s) - not yet supported, skipping.", source_row, path, exc)

            evaluation = evaluate_components(components) if components else AttachmentEvaluation()
            result = validate_item(row, evaluation, incoterm=incoterm_by_row.get(source_row))
            validation_results.append(result)

        summary_stats = summarize(validation_results)
        log.info(
            "Phase 5 done: GREEN=%d YELLOW=%d RED=%d",
            summary_stats["GREEN Count"], summary_stats["YELLOW Count"], summary_stats["RED Count"],
        )

    OUTPUT_DIR.mkdir(exist_ok=True)
    output_path = OUTPUT_DIR / f"AP_OPEN_ITEMS_RAW_{end_date.isoformat()}.xlsx"
    meta = {
        "Run Date": datetime.now().isoformat(timespec="seconds"),
        "SAP System": info.get("SystemName"),
        "SAP Client": info.get("Client"),
        "SAP User": info.get("User"),
        "Company Code": criteria.company_code,
        "Search Start Date": criteria.start_date.isoformat(),
        "Search End Date": criteria.end_date.isoformat(),
        "Open Items Only": criteria.open_items_only,
        "Total Rows": len(rows),
        "Item Rows": item_count,
        "Subtotal Rows (per-currency, not real items)": subtotal_count,
    }
    if detail_rows is not None:
        meta["Detail Rows OK"] = sum(1 for d in detail_rows if d.get("Detail_Status") == "OK")
        meta["Detail Rows Error"] = sum(1 for d in detail_rows if d.get("Detail_Status") == "ERROR")
    if attachment_rows is not None:
        meta["Items With Attachments"] = sum(1 for a in attachment_rows if a.get("Attachment_Count", 0) > 0)
        meta["Attachment Errors"] = sum(1 for a in attachment_rows if a.get("Attachment_Status") == "ERROR")
    write_raw_grid_report(
        rows, output_path, meta=meta, detail_rows=detail_rows, attachment_rows=attachment_rows,
        validation_results=validation_results, summary_stats=summary_stats,
    )

    log.info("Wrote Excel report: %s", output_path)
    print(f"\nDone. {item_count} open item row(s) (+{subtotal_count} subtotal row(s)) written to: {output_path}")
    print(f"Log file: {log_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
