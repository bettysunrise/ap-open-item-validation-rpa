"""
Custom AP Open Item ("[Import]Remittance Management") transaction automation.

READ-ONLY. Fills the selection screen with Company Code + Posting Date
range + "Open Items" filter, executes the report (F8 - a display/search
action, not a write action), and reads the resulting ALV grid.

Every Object ID below was discovered LIVE against the real selection
screen and result grid using tools/discover_sap.py - none are guessed.
Raw discovery dumps are kept under sap_discovery/ for reference:
  - ap_open_item_selection_*.json    (selection screen fields)
  - ap_open_item_results_ok_grid_*.json (result grid columns + sample rows)

The transaction code itself is deployment-specific (this is a custom
Z-transaction, not a standard SAP one) so it lives in config/settings.json
(gitignored) rather than being hardcoded here - see config/settings.example.json
for the expected shape.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from .navigation import check_not_write_screen, open_transaction

_SETTINGS_PATH = Path(__file__).resolve().parent.parent / "config" / "settings.json"
_DEFAULT_TCODE = "ZDEMO_AP_OPEN"


def _load_tcode() -> str:
    try:
        settings = json.loads(_SETTINGS_PATH.read_text(encoding="utf-8"))
        return settings.get("transaction_code", _DEFAULT_TCODE)
    except (OSError, json.JSONDecodeError):
        return _DEFAULT_TCODE


TCODE = _load_tcode()

# Selection screen field IDs (relative to the session), discovered live.
FIELD_COMPANY_CODE = "wnd[0]/usr/ctxtP_BUKRS"
FIELD_POSTING_DATE_LOW = "wnd[0]/usr/ctxtS_BUDAT-LOW"
FIELD_POSTING_DATE_HIGH = "wnd[0]/usr/ctxtS_BUDAT-HIGH"
RADIO_OPEN_ITEMS = "wnd[0]/usr/radR_7"   # "Open Items"
RADIO_ALL = "wnd[0]/usr/radR_1"          # "All"
BTN_EXECUTE = "wnd[0]/tbar[1]/btn[8]"    # tooltip confirmed live: "Execute   (F8)"

GRID_ID = "wnd[0]/usr/shell"             # ALV grid (GuiShell/GridView), confirmed live

# Result grid column technical IDs -> friendly report field names, in the
# same left-to-right order as the real SAP grid (ColumnOrder), discovered live.
GRID_COLUMNS: dict[str, str] = {
    "MARK2": "Select",
    "IVONO": "Invoice_Doc_No",
    "BSART": "PO_Type",
    "EBELN": "PO_Number",
    "IBLNO": "BL_Number",
    "BUDAT": "Posting_Date",
    "BELNR_I": "Accounting_Doc",
    "ZTERM": "Payment_Term",
    "ZDATE": "Payment_Date",
    "ZBIGO": "BIGO",
    "EKGRP": "Purchasing_Group",
    "APVEN": "Vendor_Code",
    "NAME1": "Vendor_Name",
    "NAME2": "Buyer",
    "MWSKZH": "Tax_Code",
    "WAERS": "Currency",
    "IVAMP": "Total_Amount",
    "WAERS_U": "Currency_USD",
    "IVAMP_U": "Total_Amount_USD",
    "WAERS_K": "Currency_KRW",
    "IVAMP_K": "Total_Amount_KRW",
    "DICON": "Files",
    "AUGBL": "Clearing_Doc",
    "AUGDT": "Clearing_Date",
    "BELNR": "Invoice_Acc_No",
    "ZOLLD": "Request_Date",
    "PERNR": "Requester_Name",
    "SMTP_ADDR": "Requester_Mail",
    "REMAK": "Remark",
    "MADAT": "Plan_Date",
    "UDAT": "Changed_On",
    "UTME": "Changed_Time",
}


class APOpenItemError(RuntimeError):
    pass


def _is_subtotal_row(row: dict[str, Any]) -> bool:
    """Detect ALV per-currency subtotal/grand-total rows.

    Confirmed live (2026-09-14) that this transaction's result grid includes trailing
    subtotal rows (one per currency) inside RowCount - these have no
    Invoice_Doc_No / Vendor_Code (the item identity fields) and only
    carry currency + summed amount columns. They are not real AP items
    and must not be treated as one downstream.
    """
    invoice_no = (row.get("Invoice_Doc_No") or "").strip()
    vendor_code = (row.get("Vendor_Code") or "").strip()
    return invoice_no == "" and vendor_code == ""


@dataclass
class SearchCriteria:
    company_code: str
    end_date: date
    start_date: date
    open_items_only: bool = True

    @classmethod
    def from_end_date(
        cls,
        company_code: str,
        end_date: date,
        lookback_years: int = 2,
        open_items_only: bool = True,
    ) -> "SearchCriteria":
        try:
            start_date = end_date.replace(year=end_date.year - lookback_years)
        except ValueError:
            # end_date is Feb 29 and (end_date.year - lookback_years) isn't a leap year
            start_date = end_date.replace(month=2, day=28, year=end_date.year - lookback_years)
        return cls(
            company_code=company_code,
            end_date=end_date,
            start_date=start_date,
            open_items_only=open_items_only,
        )


def open_and_search(session, criteria: SearchCriteria, sap_date_format: str = "%Y.%m.%d") -> None:
    """Navigate to the AP Open Item transaction, fill the selection screen, and execute.

    Only allowed read actions are performed: navigate, input search
    criteria, select a filter radio button, execute display/search.
    No SAP data is changed.
    """
    open_transaction(session, TCODE)
    check_not_write_screen(session)

    try:
        session.findById(FIELD_COMPANY_CODE).text = criteria.company_code
        session.findById(FIELD_POSTING_DATE_LOW).text = criteria.start_date.strftime(sap_date_format)
        session.findById(FIELD_POSTING_DATE_HIGH).text = criteria.end_date.strftime(sap_date_format)
        if criteria.open_items_only:
            session.findById(RADIO_OPEN_ITEMS).select()
        else:
            session.findById(RADIO_ALL).select()
    except Exception as exc:  # noqa: BLE001
        raise APOpenItemError(f"Failed to fill {TCODE} selection screen: {exc}") from exc

    check_not_write_screen(session)

    try:
        session.findById(BTN_EXECUTE).press()
    except Exception as exc:  # noqa: BLE001
        raise APOpenItemError(f"Failed to press Execute on {TCODE}: {exc}") from exc

    check_not_write_screen(session)

    sbar = session.findById("wnd[0]/sbar")
    if sbar.MessageType == "E":
        raise APOpenItemError(
            f"SAP reported an error after Execute (likely a bad date format or "
            f"selection value): {sbar.Text}"
        )


def read_grid_rows(session) -> list[dict[str, Any]]:
    """Read every row of the AP Open Item result grid, preserving SAP order.

    Returns a list of dicts, one per row, with friendly field names plus
    a 1-based Source_Row matching the original SAP grid row order. Does
    not select, sort, or filter the grid - pure read access.

    IMPORTANT: the ALV grid (GuiShell/GridView) only keeps rows near the
    current scroll position in its local render buffer. Calling
    GetCellValue on a row outside that buffer silently returns an empty
    string instead of the real value (confirmed live 2026-09-14 - reading
    all 128 rows without scrolling returned real data for the first ~59
    rows and completely blank data for the remaining ~69). To avoid this,
    we page through the grid with firstVisibleRow before reading each
    block, which is a read-only scroll action (no selection, no data
    change) and forces every row to be rendered before it is read.
    """
    try:
        grid = session.findById(GRID_ID)
    except Exception as exc:  # noqa: BLE001
        raise APOpenItemError(
            f"Could not find the result grid at {GRID_ID}. The report may have "
            f"returned no data, or the screen layout changed. Original error: {exc}"
        ) from exc

    try:
        row_count = grid.RowCount
    except Exception as exc:  # noqa: BLE001
        raise APOpenItemError(f"Could not read RowCount from grid: {exc}") from exc

    try:
        visible_row_count = grid.VisibleRowCount or 1
    except Exception:  # noqa: BLE001
        visible_row_count = 1

    rows: list[dict[str, Any]] = [None] * row_count  # type: ignore[list-item]
    current = 0
    while current < row_count:
        try:
            grid.firstVisibleRow = current
        except Exception as exc:  # noqa: BLE001
            raise APOpenItemError(f"Failed to scroll grid to row {current}: {exc}") from exc

        # After scrolling, some cells can briefly report a stale value left
        # over from the previous scroll position (confirmed live 2026-09-14:
        # isolated wrong PO_Number values that matched a DIFFERENT row's
        # value). Wait for the GUI to finish repainting before reading.
        waited = 0.0
        while getattr(session, "Busy", False) and waited < 5.0:
            time.sleep(0.05)
            waited += 0.05
        time.sleep(0.15)

        block_end = min(current + visible_row_count, row_count)
        for r in range(current, block_end):
            row: dict[str, Any] = {"Source_Row": r + 1}
            for tech_id, friendly in GRID_COLUMNS.items():
                try:
                    row[friendly] = grid.GetCellValue(r, tech_id)
                except Exception as exc:  # noqa: BLE001
                    row[friendly] = None
                    row[f"{friendly}_error"] = str(exc)
            row["Row_Type"] = "SUBTOTAL" if _is_subtotal_row(row) else "ITEM"
            rows[r] = row
        current = block_end

    return rows
