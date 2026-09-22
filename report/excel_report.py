"""
Excel report generation.

Phase 1 scope only: write the RAW AP Open Item grid rows to an Excel workbook,
exactly as read from SAP (no validation, no document matching yet).
Preserves Source_Row (original SAP grid order).

Later phases will extend this module with SUMMARY / VALIDATION_RESULT /
ERROR_LOG sheets once the validation engine exists.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

SUBTOTAL_FILL = PatternFill(start_color="FFFF00", end_color="FFFF00", fill_type="solid")
ERROR_FILL = PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid")

# Phase 2: fields read from the Commercial Invoice detail screen
# (sap/document_detail.py FIELD_MAP), plus Source_Row + status/error.
DETAIL_COLUMNS = [
    "Source_Row",
    "Detail_Status",
    "CI_No",
    "Invoice_Doc_No",
    "Invoice_Date",
    "Posting_Date",
    "PO_Number",
    "Vendor_Code",
    "Vendor_Name",
    "AP_Account",
    "Invoice_Amount",
    "AP_Total_Amount",
    "Currency",
    "Invoice_Reference",
    "Accounting_Doc",
    "Fiscal_Year",
    "Incoterm",
    "Detail_Error",
]

# Phase 3: attachment presence/metadata (sap/attachment.py process_attachments).
ATTACHMENT_COLUMNS = [
    "Source_Row",
    "Attachment_Status",
    "Has_Files_Indicator",
    "Attachment_Count",
    "File_Names",
    "Attachment_Error",
]

# Phase 5: final validation result (validation/engine.py ItemValidationResult)
# joined with key Phase 1 grid identifiers, per project spec section 16.
VALIDATION_RESULT_COLUMNS = [
    "Source_Row",
    "Status",
    "Accounting_Doc",
    "Invoice_Doc_No",
    "PO_Number",
    "Vendor_Name",
    "Posting_Date",
    "Currency",
    "Total_Amount",
    "Invoice_Vendor",
    "Invoice_Currency",
    "Invoice_Total_Amount",
    "Invoice_Consignee",
    "Transport_Source",
    "On_Board_Date",
    "Vendor_Match",
    "Amount_Match",
    "Currency_Match",
    "Posting_Date_Match",
    "Group_Consignee_Check",
    "Amount_Difference",
    "Error_Reason",
]

STATUS_FILLS = {
    "GREEN": PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid"),
    "YELLOW": PatternFill(start_color="FFEB9C", end_color="FFEB9C", fill_type="solid"),
    "RED": PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid"),
}
STATUS_SORT_ORDER = {"RED": 0, "YELLOW": 1, "GREEN": 2}

# Column order for the raw export sheet. Source_Row first, then the
# friendly field names in the same left-to-right order as the real SAP
# grid (see sap/ap_open_item.py GRID_COLUMNS).
RAW_COLUMNS = [
    "Source_Row",
    "Row_Type",
    "Select",
    "Invoice_Doc_No",
    "PO_Type",
    "PO_Number",
    "BL_Number",
    "Posting_Date",
    "Accounting_Doc",
    "Payment_Term",
    "Payment_Date",
    "BIGO",
    "Purchasing_Group",
    "Vendor_Code",
    "Vendor_Name",
    "Buyer",
    "Tax_Code",
    "Currency",
    "Total_Amount",
    "Currency_USD",
    "Total_Amount_USD",
    "Currency_KRW",
    "Total_Amount_KRW",
    "Files",
    "Clearing_Doc",
    "Clearing_Date",
    "Invoice_Acc_No",
    "Request_Date",
    "Requester_Name",
    "Requester_Mail",
    "Remark",
    "Plan_Date",
    "Changed_On",
    "Changed_Time",
]


def write_raw_grid_report(
    rows: list[dict[str, Any]],
    output_path: str | Path,
    meta: dict[str, Any] | None = None,
    detail_rows: list[dict[str, Any]] | None = None,
    attachment_rows: list[dict[str, Any]] | None = None,
    validation_results: list[Any] | None = None,
    summary_stats: dict[str, Any] | None = None,
) -> Path:
    """Write raw AP Open Item rows to an Excel file, preserving SAP order.

    `rows` is the list of dicts returned by sap.ap_open_item.read_grid_rows.
    `detail_rows` (optional) is the list returned by
    sap.document_detail.process_item_details - written to a second sheet
    (AP_OPEN_ITEMS_DETAIL) for cross-checking against the raw grid.
    `meta` (optional) is written to a small header block on a META sheet
    (run date, company code, date range, row count) for traceability.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    wb = Workbook()
    ws = wb.active
    ws.title = "AP_OPEN_ITEMS_RAW"

    header_font = Font(bold=True)
    for col_idx, col_name in enumerate(RAW_COLUMNS, start=1):
        cell = ws.cell(row=1, column=col_idx, value=col_name)
        cell.font = header_font

    for row_idx, row in enumerate(rows, start=2):
        is_subtotal = row.get("Row_Type") == "SUBTOTAL"
        for col_idx, col_name in enumerate(RAW_COLUMNS, start=1):
            cell = ws.cell(row=row_idx, column=col_idx, value=row.get(col_name))
            if is_subtotal:
                cell.fill = SUBTOTAL_FILL

    ws.freeze_panes = "A2"
    if rows:
        ws.auto_filter.ref = f"A1:{get_column_letter(len(RAW_COLUMNS))}{len(rows) + 1}"

    # Reasonable column widths based on header length (raw dump - keep simple)
    for col_idx, col_name in enumerate(RAW_COLUMNS, start=1):
        ws.column_dimensions[get_column_letter(col_idx)].width = max(12, len(col_name) + 2)

    if detail_rows:
        detail_ws = wb.create_sheet("AP_OPEN_ITEMS_DETAIL")
        for col_idx, col_name in enumerate(DETAIL_COLUMNS, start=1):
            cell = detail_ws.cell(row=1, column=col_idx, value=col_name)
            cell.font = header_font

        for row_idx, row in enumerate(detail_rows, start=2):
            is_error = row.get("Detail_Status") == "ERROR"
            for col_idx, col_name in enumerate(DETAIL_COLUMNS, start=1):
                cell = detail_ws.cell(row=row_idx, column=col_idx, value=row.get(col_name))
                if is_error:
                    cell.fill = ERROR_FILL

        detail_ws.freeze_panes = "A2"
        detail_ws.auto_filter.ref = f"A1:{get_column_letter(len(DETAIL_COLUMNS))}{len(detail_rows) + 1}"
        for col_idx, col_name in enumerate(DETAIL_COLUMNS, start=1):
            detail_ws.column_dimensions[get_column_letter(col_idx)].width = max(12, len(col_name) + 2)

    if attachment_rows:
        att_ws = wb.create_sheet("AP_OPEN_ITEMS_ATTACHMENTS")
        for col_idx, col_name in enumerate(ATTACHMENT_COLUMNS, start=1):
            cell = att_ws.cell(row=1, column=col_idx, value=col_name)
            cell.font = header_font

        for row_idx, row in enumerate(attachment_rows, start=2):
            values = dict(row)
            files = values.get("Files") or []
            # "FILEP" is the old DICON-popup mechanism's filename field;
            # "BITM_DESCR" is the real one used by GOS attachments (see
            # sap/gos_attachment.py) - check both so this sheet works for
            # either source.
            values["File_Names"] = "; ".join(f.get("BITM_DESCR") or f.get("FILEP", "") for f in files) if files else ""
            is_error = values.get("Attachment_Status") == "ERROR"
            for col_idx, col_name in enumerate(ATTACHMENT_COLUMNS, start=1):
                cell = att_ws.cell(row=row_idx, column=col_idx, value=values.get(col_name))
                if is_error:
                    cell.fill = ERROR_FILL

        att_ws.freeze_panes = "A2"
        att_ws.auto_filter.ref = f"A1:{get_column_letter(len(ATTACHMENT_COLUMNS))}{len(attachment_rows) + 1}"
        for col_idx, col_name in enumerate(ATTACHMENT_COLUMNS, start=1):
            att_ws.column_dimensions[get_column_letter(col_idx)].width = max(12, len(col_name) + 2)

    if validation_results:
        rows_by_source = {r["Source_Row"]: r for r in rows}
        val_ws = wb.create_sheet("VALIDATION_RESULT")
        for col_idx, col_name in enumerate(VALIDATION_RESULT_COLUMNS, start=1):
            cell = val_ws.cell(row=1, column=col_idx, value=col_name)
            cell.font = header_font

        sorted_results = sorted(
            validation_results,
            key=lambda r: (STATUS_SORT_ORDER.get(r.Final_Status, 1), r.Source_Row),
        )

        for row_idx, vr in enumerate(sorted_results, start=2):
            sap_row = rows_by_source.get(vr.Source_Row, {})
            combined = {
                "Source_Row": vr.Source_Row,
                "Status": vr.Final_Status,
                "Accounting_Doc": sap_row.get("Accounting_Doc"),
                "Invoice_Doc_No": sap_row.get("Invoice_Doc_No"),
                "PO_Number": sap_row.get("PO_Number"),
                "Vendor_Name": sap_row.get("Vendor_Name"),
                "Posting_Date": sap_row.get("Posting_Date"),
                "Currency": sap_row.get("Currency"),
                "Total_Amount": sap_row.get("Total_Amount"),
                "Invoice_Vendor": vr.Invoice_Vendor,
                "Invoice_Currency": vr.Invoice_Currency,
                "Invoice_Total_Amount": vr.Invoice_Total_Amount,
                "Invoice_Consignee": vr.Invoice_Consignee,
                "Transport_Source": vr.Transport_Source,
                "On_Board_Date": vr.On_Board_Date,
                "Vendor_Match": vr.Vendor_Match,
                "Amount_Match": vr.Amount_Match,
                "Currency_Match": vr.Currency_Match,
                "Posting_Date_Match": vr.Posting_Date_Match,
                "Group_Consignee_Check": vr.Group_Consignee_Check,
                "Amount_Difference": vr.Amount_Difference,
                "Error_Reason": vr.Error_Reason,
            }
            fill = STATUS_FILLS.get(vr.Final_Status)
            for col_idx, col_name in enumerate(VALIDATION_RESULT_COLUMNS, start=1):
                cell = val_ws.cell(row=row_idx, column=col_idx, value=combined.get(col_name))
                if col_name == "Status" and fill:
                    cell.fill = fill
                if col_name == "Error_Reason":
                    cell.alignment = cell.alignment.copy(wrap_text=True)

        val_ws.freeze_panes = "A2"
        val_ws.auto_filter.ref = f"A1:{get_column_letter(len(VALIDATION_RESULT_COLUMNS))}{len(sorted_results) + 1}"
        for col_idx, col_name in enumerate(VALIDATION_RESULT_COLUMNS, start=1):
            width = 40 if col_name == "Error_Reason" else max(12, len(col_name) + 2)
            val_ws.column_dimensions[get_column_letter(col_idx)].width = width

    if summary_stats:
        summary_ws = wb.create_sheet("SUMMARY", 0)  # first sheet
        summary_ws.append(["Run Date", (meta or {}).get("Run Date")])
        summary_ws.append(["Company Code", (meta or {}).get("Company Code")])
        summary_ws.append(["Search Start Date", (meta or {}).get("Search Start Date")])
        summary_ws.append(["Search End Date", (meta or {}).get("Search End Date")])
        summary_ws.append(["Open Items Only", (meta or {}).get("Open Items Only")])
        summary_ws.append([])
        summary_ws.append(["Total Items", summary_stats.get("Total Items")])
        summary_ws.append(["GREEN Count", summary_stats.get("GREEN Count")])
        summary_ws.append(["YELLOW Count", summary_stats.get("YELLOW Count")])
        summary_ws.append(["RED Count", summary_stats.get("RED Count")])
        summary_ws.append([])
        summary_ws.append(["Error Category", "Count"])
        for category, count in summary_stats.get("error_counts", {}).items():
            summary_ws.append([category, count])
        summary_ws.column_dimensions["A"].width = 45
        summary_ws.column_dimensions["B"].width = 20

    if meta:
        meta_ws = wb.create_sheet("META")
        meta_ws.append(["Key", "Value"])
        for key, value in meta.items():
            meta_ws.append([key, value])
        meta_ws.column_dimensions["A"].width = 24
        meta_ws.column_dimensions["B"].width = 40

    wb.save(output_path)
    return output_path
