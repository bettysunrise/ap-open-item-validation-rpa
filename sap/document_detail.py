"""
Commercial Invoice detail screen automation (Phase 2).

Clicking the Invoice_Doc_No hotspot cell in the AP Open Item result grid
opens a custom transaction (its underlying program name lives in
config/settings.json - see DETAIL_PROGRAM below) titled "Commercial
Invoice : Display" - a READ-ONLY display screen (confirmed live
2026-09-14, title contains "Display", not "Change").

Every field ID below was discovered live via tools/discover_sap.py against
this real screen - see sap_discovery/detail_screen_invoice_detail_*.json.

READ-ONLY. No fields are ever set on this screen - only read. Navigation
back to the list uses the universal SAP GUI "Back (F3)" toolbar button.
"""
from __future__ import annotations

import time
from typing import Any

import json
from pathlib import Path

from .connection import get_session_info
from .navigation import check_not_write_screen, get_window_title
from .ap_open_item import TCODE

GRID_ID = "wnd[0]/usr/shell"

EXPECTED_TITLE_SUBSTR = "Commercial Invoice"

# The detail screen's underlying program name is deployment-specific (a
# custom Z-program), so - like TCODE in sap/ap_open_item.py - it's read from
# config/settings.json (gitignored) rather than hardcoded.
_SETTINGS_PATH = Path(__file__).resolve().parent.parent / "config" / "settings.json"
_DEFAULT_DETAIL_PROGRAM = "ZDEMO_AP_PROG"


def _load_detail_program() -> str:
    try:
        settings = json.loads(_SETTINGS_PATH.read_text(encoding="utf-8"))
        return settings.get("detail_program", _DEFAULT_DETAIL_PROGRAM)
    except (OSError, json.JSONDecodeError):
        return _DEFAULT_DETAIL_PROGRAM


DETAIL_PROGRAM = _load_detail_program()

# Subscreen container paths discovered live on the detail screen (screen 2100).
_HEADER_BASE = f"wnd[0]/usr/subSUB0:{DETAIL_PROGRAM}:2100/subSUBT:{DETAIL_PROGRAM}:2111"
_DETAIL_BASE = (
    f"wnd[0]/usr/subSUB0:{DETAIL_PROGRAM}:2100/subSUB1:{DETAIL_PROGRAM}:2120/tabsTABSTRIP/"
    f"tabpTABSTRIP_FC1/ssubTABSTRIP_SCA:{DETAIL_PROGRAM}:2121"
)

# Friendly name -> real field Object ID, all discovered live (none guessed).
FIELD_MAP: dict[str, str] = {
    "CI_No": f"{_HEADER_BASE}/ctxtZTITIVK-IVNUM",
    "Invoice_Doc_No": f"{_HEADER_BASE}/ctxtZTITIVK-IVONO",
    "Invoice_Date": f"{_DETAIL_BASE}/ctxtZTITIVK-CIVDT",
    "Posting_Date": f"{_DETAIL_BASE}/ctxtZTITIVK-BUDAT",
    "PO_Number": f"{_DETAIL_BASE}/txtZTITBLK-EBELN",
    "Vendor_Code": f"{_DETAIL_BASE}/ctxtZTITIVK-LIFNR",
    "Vendor_Name": f"{_DETAIL_BASE}/txtLFA1-NAME1",
    "AP_Account": f"{_DETAIL_BASE}/ctxtZTITIVK-APVEN",
    "Invoice_Amount": f"{_DETAIL_BASE}/txtZTITIVK-IVAMT",
    "AP_Total_Amount": f"{_DETAIL_BASE}/txtZTITIVK-IVAMP",
    "Currency": f"{_DETAIL_BASE}/ctxtZTITIVK-WAERS",
    "Invoice_Reference": f"{_DETAIL_BASE}/txtZTITIVK-XBLNR",
    "Accounting_Doc": f"{_DETAIL_BASE}/txtZTITIVK-BELNR",
    "Fiscal_Year": f"{_DETAIL_BASE}/txtZTITIVK-GJAHR",
    "Incoterm": f"{_DETAIL_BASE}/txtZTITIVK-INCO1",
}


class InvoiceDetailError(RuntimeError):
    pass


def open_invoice_detail(session, row_index: int) -> None:
    """Open the invoice detail screen for a grid row (0-based index).

    IMPORTANT: `GuiCtrlGridView.Click(row, columnId)` was confirmed live
    (2026-09-14) to be unreliable in this environment - it ignores the
    requested row and repeatedly re-triggers whatever row was already
    GuiCtrlGridView.CurrentCellRow (observed: every call opened row 0's
    invoice regardless of the row argument, even after scrolling that row
    into view). The reliable sequence is SetCurrentCell(row, col) followed
    by ClickCurrentCell() - verified to open the correct row's invoice.

    Read-only navigation - a hotspot click, not a write action. Raises
    InvoiceDetailError if the resulting screen isn't the expected
    Commercial Invoice display (safety: never proceed onto an unexpected
    screen).
    """
    try:
        grid = session.findById(GRID_ID)
        grid.SetCurrentCell(row_index, "IVONO")
        time.sleep(0.05)
        grid.ClickCurrentCell()
    except Exception as exc:  # noqa: BLE001
        raise InvoiceDetailError(f"Failed to click invoice hotspot for row {row_index}: {exc}") from exc

    check_not_write_screen(session)

    title = get_window_title(session)
    if EXPECTED_TITLE_SUBSTR not in title:
        raise InvoiceDetailError(
            f"Expected a '{EXPECTED_TITLE_SUBSTR}' screen after clicking row {row_index}, "
            f"got title: '{title}'"
        )


def read_invoice_detail(session) -> dict[str, Any]:
    """Read the key fields off the currently open invoice detail screen."""
    result: dict[str, Any] = {}
    for name, field_id in FIELD_MAP.items():
        try:
            result[name] = session.findById(field_id).text
        except Exception as exc:  # noqa: BLE001
            result[name] = None
            result[f"{name}_error"] = str(exc)
    return result


def close_invoice_detail(session) -> None:
    """Return to the AP Open Item result list via the universal Back (F3) button."""
    try:
        session.findById("wnd[0]/tbar[0]/btn[3]").press()
    except Exception as exc:  # noqa: BLE001
        raise InvoiceDetailError(f"Failed to press Back from invoice detail: {exc}") from exc


def process_item_details(session, rows: list[dict[str, Any]], logger=None) -> list[dict[str, Any]]:
    """For each ITEM row (Row_Type == 'ITEM'), open its invoice detail,
    read the key fields, and return safely to the list.

    Preserves Source_Row. If one item fails, logs it and continues to the
    next row (per project rule: never let one bad row stop the whole run).
    """
    results: list[dict[str, Any]] = []
    item_rows = [r for r in rows if r.get("Row_Type") == "ITEM"]
    total = len(item_rows)

    for idx, row in enumerate(item_rows, start=1):
        source_row = row["Source_Row"]
        if logger and (idx == 1 or idx % 10 == 0 or idx == total):
            logger.info("Processing item detail %d/%d (Source_Row=%s)...", idx, total, source_row)
        row_index = source_row - 1
        detail: dict[str, Any] = {"Source_Row": source_row}

        try:
            open_invoice_detail(session, row_index)
            detail.update(read_invoice_detail(session))
            close_invoice_detail(session)

            info = get_session_info(session)
            if info.get("Transaction") != TCODE:
                raise InvoiceDetailError(
                    f"Did not return to {TCODE} after row {source_row} "
                    f"(now on {info.get('Transaction')})"
                )

            # Defensive cross-check: confirm the detail screen we just read
            # actually belongs to THIS row's invoice. Confirmed live that
            # a wrong-row navigation can happen silently (see
            # open_invoice_detail docstring) - never trust it blindly.
            expected_invoice_no = (row.get("Invoice_Doc_No") or "").strip()
            actual_invoice_no = (detail.get("Invoice_Doc_No") or "").strip()
            if expected_invoice_no and actual_invoice_no and expected_invoice_no != actual_invoice_no:
                raise InvoiceDetailError(
                    f"Row {source_row}: detail screen showed invoice "
                    f"{actual_invoice_no!r} but grid expected {expected_invoice_no!r} "
                    f"(wrong-row navigation)"
                )

            detail["Detail_Status"] = "OK"

        except Exception as exc:  # noqa: BLE001
            detail["Detail_Status"] = "ERROR"
            detail["Detail_Error"] = str(exc)
            if logger:
                logger.error("Row %s: detail read failed: %s", source_row, exc)

            # Best-effort recovery: if we're stranded off the list screen,
            # try one safe Back press (guarded by the write-screen check)
            # so the next row can still be processed.
            try:
                info = get_session_info(session)
                if info.get("Transaction") != TCODE:
                    check_not_write_screen(session)
                    session.findById("wnd[0]/tbar[0]/btn[3]").press()
            except Exception as recovery_exc:  # noqa: BLE001
                if logger:
                    logger.error("Row %s: recovery Back also failed: %s", source_row, recovery_exc)

        results.append(detail)

    return results
