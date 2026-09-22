"""
Tie classification + parsing together for one attachment file: decide
which required document types (Invoice / Packing List / Transport doc)
are present, per project Rules 01-04, and return their parsed field data
for Phase 5 validation to consume.

An empty component (classified but with no real content - confirmed real
case: a "BL" sheet that exists but is blank) never counts as document
presence, regardless of its classified type.

A component classified UNKNOWN with LOW confidence is surfaced separately
so the caller can flag "문서 종류 확인 필요" (YELLOW) rather than silently
ignoring it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from .classifier import (
    DOC_AWB,
    DOC_BL,
    DOC_CARGO_RECEIPT,
    DOC_COURIER,
    DOC_DELIVERY_RECEIPT,
    DOC_INVOICE,
    DOC_PACKING_LIST,
    DOC_UNKNOWN,
    classify_component,
)
from .excel_extractor import DocumentComponent
from .invoice_parser import parse_commercial_invoice
from .packing_parser import parse_packing_list
from .transport_parser import parse_transport_document

# Delivery Receipt / Cargo Receipt are this business's real proof-of-
# shipment documents for domestic/local-trucking moves (confirmed live
# 2026-09-15) - functionally the same role as B/L/AWB/courier for Rule 03.
TRANSPORT_TYPES = {DOC_BL, DOC_AWB, DOC_COURIER, DOC_DELIVERY_RECEIPT, DOC_CARGO_RECEIPT}


@dataclass
class AttachmentEvaluation:
    has_invoice: bool = False
    has_packing_list: bool = False
    has_transport_doc: bool = False
    invoice_data: Optional[dict[str, Any]] = None
    packing_list_data: Optional[dict[str, Any]] = None
    packing_list_source: Optional[str] = None  # "PACKING_LIST sheet" | "substituted by DELIVERY_RECEIPT" | ...
    transport_data: Optional[dict[str, Any]] = None
    transport_source: Optional[str] = None  # "BL sheet" | "AWB sheet" | "Courier sheet" | "embedded in invoice"
    unclassified_components: list[str] = field(default_factory=list)
    component_classifications: list[dict[str, Any]] = field(default_factory=list)
    multiple_invoices_found: bool = False  # confirmed real case - see evaluate_components docstring


# Real Commercial Invoice sections seen so far top out around 8500
# characters. Confirmed real bug: a BL's multi-page "DEFINITIONS" legal
# terms section (38000+ characters) happened to mention the bare phrase
# "commercial invoice" deep inside a Carrier-inspection-rights clause,
# which made pdf_extractor.py's page-marker splitter start a new
# "COMMERCIAL_INVOICE"-labeled section right there and classify_component
# confidently (HIGH) misclassify the whole legal blob as a real invoice -
# its Shipper/Consignee "values" then came from random definitional
# clauses ("means the party named as Consignee on the face of this bill
# of lading..."). A real single invoice section is never this long, so
# this is a safe, generic guard against this whole failure mode.
MAX_PLAUSIBLE_INVOICE_LENGTH = 15000


def evaluate_components(components: list[DocumentComponent]) -> AttachmentEvaluation:
    result = AttachmentEvaluation()
    receipt_component: Optional[DocumentComponent] = None  # first DELIVERY_RECEIPT/CARGO_RECEIPT seen, for the packing-list fallback below
    first_invoice_text: Optional[str] = None

    for comp in components:
        classification = classify_component(comp.component_name, comp.text)

        if classification.doc_type == DOC_INVOICE and len(comp.text) > MAX_PLAUSIBLE_INVOICE_LENGTH:
            classification.doc_type = DOC_UNKNOWN
            classification.confidence = "LOW"
            classification.reason = (
                f"rejected as INVOICE - {len(comp.text)} chars is implausibly long for a single "
                f"invoice section (likely a misclassified multi-page legal/terms block)"
            )

        result.component_classifications.append(
            {
                "component_name": comp.component_name,
                "doc_type": classification.doc_type,
                "confidence": classification.confidence,
                "is_empty": classification.is_empty,
                "reason": classification.reason,
            }
        )

        if classification.is_empty:
            continue  # present tab, no real content - never counts

        if classification.doc_type == DOC_UNKNOWN or classification.confidence == "LOW":
            if classification.doc_type == DOC_UNKNOWN:
                result.unclassified_components.append(comp.component_name)

        if classification.doc_type == DOC_INVOICE and result.has_invoice:
            # Confirmed real case (2026-09-18): a single PDF bundled TWO
            # Commercial Invoice sections - one superseded/wrong, one
            # correct, no reliable way to tell which from the document
            # alone (user confirmed: don't guess which is real - flag for
            # human review instead). Keep using the FIRST one found (so
            # has_invoice/invoice_data stay populated - Rule 01 still
            # sees a document present) but mark this ambiguity so
            # Phase 5 downgrades the whole item to YELLOW rather than
            # trusting a vendor/amount/consignee comparison that might be
            # checking the wrong copy.
            #
            # IMPORTANT: the SAME attachment is routinely downloaded again
            # on a later run (confirmed real: identical files timestamped
            # both 2026-09-15 and 2026-09-16 sit side by side in
            # attachments/Source_Row_<n>/) - that byte-identical re-download
            # is NOT a second invoice and must not trigger this flag, so
            # only count it when the text actually differs.
            #
            # ALSO confirmed real: a sales-contract/terms page can get
            # mis-split and mis-classified as a second "Commercial
            # Invoice" purely because it happens to mention the phrase
            # "Commercial invoice in triplicate" in a documents-required
            # checklist - it has no real Shipper/Exporter field at all.
            # Only trust this as a genuine second invoice if it actually
            # parses a real seller name (a contract/terms page won't).
            if comp.text.strip() != (first_invoice_text or "").strip():
                candidate_vendor = parse_commercial_invoice(comp.rows).get("Vendor_Seller")
                if candidate_vendor:
                    result.multiple_invoices_found = True

        if classification.doc_type == DOC_INVOICE and not result.has_invoice:
            result.has_invoice = True
            result.invoice_data = parse_commercial_invoice(comp.rows)
            first_invoice_text = comp.text

        elif classification.doc_type == DOC_PACKING_LIST and not result.has_packing_list:
            result.has_packing_list = True
            result.packing_list_data = parse_packing_list(comp.rows)
            result.packing_list_source = f"{classification.doc_type} sheet"

        elif classification.doc_type in TRANSPORT_TYPES and not result.has_transport_doc:
            result.has_transport_doc = True
            result.transport_data = parse_transport_document(comp.rows)
            result.transport_source = f"{classification.doc_type} sheet"

        if classification.doc_type in (DOC_DELIVERY_RECEIPT, DOC_CARGO_RECEIPT) and receipt_component is None:
            receipt_component = comp

    # Fallback per Rule 02 (user-confirmed 2026-09-16): for domestic/
    # local-trucking shipments this business genuinely never issues a
    # separate Packing List - the Delivery Receipt/Cargo Receipt's own
    # item/quantity table serves that role. Only used when no dedicated
    # Packing List component was found, and clearly tagged as a
    # substitution (not a real separate Packing List) for transparency.
    if not result.has_packing_list and receipt_component is not None:
        result.has_packing_list = True
        result.packing_list_data = parse_packing_list(receipt_component.rows)
        result.packing_list_source = (
            f"substituted by {receipt_component.component_name} (no separate Packing List for this shipment type)"
        )

    # Fallback per Rule 03: some vendors embed courier evidence directly in
    # the Commercial Invoice's "Carrier"/"Sailing on or about" fields
    # instead of attaching a separate transport document (confirmed real
    # case, 2026-09-15: DHL waybill number + date on the invoice itself,
    # empty "BL" sheet). This still counts as a form of evidence, but is
    # flagged distinctly so a reviewer can judge it (not silently treated
    # as equal-confidence to a real separate transport document).
    if not result.has_transport_doc and result.invoice_data:
        carrier_info = result.invoice_data.get("Carrier_Info")
        sailing_date = result.invoice_data.get("Sailing_Date")
        if carrier_info or sailing_date:
            result.has_transport_doc = True
            result.transport_data = {
                "Shipper": result.invoice_data.get("Vendor_Seller"),
                "Consignee": result.invoice_data.get("Consignee_Buyer"),
                "Document_Number": carrier_info,
                "On_Board_Date": sailing_date,
                "Courier_Name": None,
            }
            result.transport_source = "embedded in invoice (no separate transport document attached)"

    return result
