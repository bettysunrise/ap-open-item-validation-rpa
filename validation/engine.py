"""
Top-level validation orchestrator: runs every independent rule module
against one AP item (Phase 1 grid row + Phase 2 invoice-detail row +
Phase 4 attachment evaluation) and combines them into one final
GREEN/YELLOW/RED status with ALL applicable reasons (never just the
first one), per project rules.

Severity ordering: RED > YELLOW > GREEN. If uncertain, never silently
report GREEN.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Optional

from documents.evaluator import AttachmentEvaluation

from .amount import compare_amount
from .consignee import check_consignee
from .currency import compare_currency
from .posting_date import compare_posting_date
from .required_docs import check_required_docs
from .vendor import compare_vendor

_STATUS_RANK = {"GREEN": 0, "YELLOW": 1, "RED": 2}


def combine_statuses(*statuses: str) -> str:
    present = [s for s in statuses if s]
    if not present:
        return "YELLOW"  # never default to GREEN when nothing was actually checked
    return max(present, key=lambda s: _STATUS_RANK.get(s, 1))


def parse_sap_date(value: Any) -> Optional[Any]:
    """Parse a SAP grid date string (format per config sap_date_format,
    typically 'YYYY.MM.DD') into a date object. Returns None rather than
    guessing if it can't be parsed."""
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    s = str(value).strip()
    for fmt in ("%Y.%m.%d", "%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


@dataclass
class ItemValidationResult:
    Source_Row: int
    Final_Status: str = "YELLOW"
    Error_Reason: str = ""
    Required_Docs_Status: Optional[str] = None
    Vendor_Match: Optional[str] = None
    Amount_Match: Optional[str] = None
    Currency_Match: Optional[str] = None
    Posting_Date_Match: Optional[str] = None
    Group_Consignee_Check: Optional[str] = None
    Amount_Difference: Optional[str] = None
    Invoice_Vendor: Optional[str] = None
    Invoice_Currency: Optional[str] = None
    Invoice_Total_Amount: Optional[str] = None
    Invoice_Consignee: Optional[str] = None
    Transport_Source: Optional[str] = None
    On_Board_Date: Optional[str] = None
    reasons: list[str] = field(default_factory=list)


def validate_item(
    sap_row: dict[str, Any],
    evaluation: AttachmentEvaluation,
    incoterm: Optional[str] = None,
    vendor_alias_config: str = "config/vendor_aliases.json",
    group_entities_config: str = "config/eo_entities.json",
) -> ItemValidationResult:
    """Run all Phase 5 rules for one AP item and produce its final status.

    `sap_row` is one row from sap.ap_open_item.read_grid_rows (Phase 1).
    `evaluation` is the result of documents.evaluator.evaluate_components
    for that item's attachment(s) (Phase 4).
    `incoterm` is the Incoterm read from the Commercial Invoice detail screen
    (Phase 2), used only for the FOB posting-date rule.
    """
    source_row = sap_row["Source_Row"]
    result = ItemValidationResult(Source_Row=source_row)
    statuses: list[str] = []

    required = check_required_docs(evaluation.has_invoice, evaluation.has_packing_list, evaluation.has_transport_doc)
    result.Required_Docs_Status = required.status
    statuses.append(required.status)
    result.reasons.extend(required.reasons)

    if evaluation.unclassified_components:
        result.reasons.append("문서 종류 확인 필요")
        statuses.append("YELLOW")

    invoice_data = evaluation.invoice_data or {}
    if evaluation.multiple_invoices_found:
        # Confirmed real case (2026-09-18) - user-confirmed policy: when an
        # attachment bundles more than one Commercial Invoice section
        # (e.g. a superseded/wrong one plus the real one, no reliable way
        # to tell which from the document alone), never guess which one's
        # vendor/amount/currency/consignee to trust - flag for human
        # review instead of running those comparisons against data that
        # might be from the wrong copy.
        result.reasons.append("인보이스가 여러 건 발견됨 - 어느 것이 맞는지 확인 필요")
        statuses.append("YELLOW")
    elif evaluation.has_invoice:
        vendor_result = compare_vendor(sap_row.get("Vendor_Name"), invoice_data.get("Vendor_Seller"), vendor_alias_config)
        result.Vendor_Match = vendor_result.status
        statuses.append(vendor_result.status)
        if vendor_result.reason:
            result.reasons.append(vendor_result.reason)

        amount_result = compare_amount(sap_row.get("Total_Amount"), invoice_data.get("Total_Amount"))
        result.Amount_Match = amount_result.status
        result.Amount_Difference = str(amount_result.difference) if amount_result.difference is not None else None
        statuses.append(amount_result.status)
        if amount_result.reason:
            result.reasons.append(amount_result.reason)

        currency_result = compare_currency(sap_row.get("Currency"), invoice_data.get("Currency"))
        result.Currency_Match = currency_result.status
        statuses.append(currency_result.status)
        if currency_result.reason:
            result.reasons.append(currency_result.reason)

        consignee_result = check_consignee(invoice_data.get("Consignee_Buyer"), group_entities_config)
        result.Group_Consignee_Check = consignee_result.status
        statuses.append(consignee_result.status)
        if consignee_result.reason:
            result.reasons.append(consignee_result.reason)

        result.Invoice_Vendor = invoice_data.get("Vendor_Seller")
        result.Invoice_Currency = invoice_data.get("Currency")
        result.Invoice_Total_Amount = invoice_data.get("Total_Amount")
        result.Invoice_Consignee = invoice_data.get("Consignee_Buyer")

    on_board_date = None
    if evaluation.transport_data:
        on_board_date = evaluation.transport_data.get("On_Board_Date")
        result.Transport_Source = evaluation.transport_source
        result.On_Board_Date = str(on_board_date) if on_board_date else None

    sap_posting_date = parse_sap_date(sap_row.get("Posting_Date"))
    posting_result = compare_posting_date(sap_posting_date, on_board_date, incoterm)
    if posting_result.applicable:
        result.Posting_Date_Match = posting_result.status
        statuses.append(posting_result.status)
        if posting_result.reason:
            result.reasons.append(posting_result.reason)

    result.Final_Status = combine_statuses(*statuses)
    result.Error_Reason = " / ".join(result.reasons)
    return result
