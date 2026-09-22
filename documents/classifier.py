"""
Document type classification for one component (e.g. one Excel sheet or
one file) extracted from a SAP attachment.

Priority per project rule: filename/component-name hint first; if that's
ambiguous, fall back to content inspection. Never classify solely from an
ambiguous name (e.g. "scan001.pdf") - fall through to UNKNOWN/LOW
confidence rather than guessing, so downstream logic marks it YELLOW
("문서 종류 확인 필요") instead of silently assuming a type.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

DOC_INVOICE = "INVOICE"
DOC_PROFORMA_INVOICE = "PROFORMA_INVOICE"
DOC_PACKING_LIST = "PACKING_LIST"
DOC_BL = "BL"
DOC_AWB = "AWB"
DOC_COURIER = "COURIER"
# Confirmed real document types (2026-09-15, PDF attachments accessed via
# FB03/GOS): "Delivery Receipt" / "Cargo Receipt" are this business's
# proof-of-shipment documents for domestic/local-trucking moves (real
# sample: Seller/Buyer/Carrier="By Truck" fields, no ocean B/L at all) -
# functionally the same role as a B/L/AWB/courier waybill for Rule 03,
# just a different real-world label. IMPORTANT: a real sample was found
# where SAP's own attachment TITLE said "BL" but the actual content was a
# Delivery Receipt - never trust the filename/title over content here.
DOC_DELIVERY_RECEIPT = "DELIVERY_RECEIPT"
DOC_CARGO_RECEIPT = "CARGO_RECEIPT"
DOC_SALES_CONFIRMATION = "SALES_CONFIRMATION"
DOC_PAYMENT_REQUEST = "PAYMENT_REQUEST"
DOC_OTHER = "OTHER"
DOC_UNKNOWN = "UNKNOWN"

# Document types that count toward the required-document rules (01-03).
# SALES_CONFIRMATION / PAYMENT_REQUEST / OTHER are informational only.
REQUIRED_DOC_TYPES = {
    DOC_INVOICE, DOC_PACKING_LIST, DOC_BL, DOC_AWB, DOC_COURIER,
    DOC_DELIVERY_RECEIPT, DOC_CARGO_RECEIPT,
}

COURIER_KEYWORDS = ["dhl", "fedex", "ups", "ems", "tnt", "courier"]

_TOKEN_RE = re.compile(r"[a-z0-9]+")

# Matches "B/L Number", "B/L No", "BL NO." etc. - see classify_by_content.
_BL_NUMBER_RE = re.compile(r"\bb\s*/\s*l\s*(no\.?|number)\b")


@dataclass
class ClassificationResult:
    doc_type: str
    confidence: str  # "HIGH" | "LOW"
    reason: str
    is_empty: bool = False


def _tokens(s: str) -> list[str]:
    return _TOKEN_RE.findall(s.lower())


def _has_token(tokens: list[str], word: str) -> bool:
    return word in tokens


def _has_phrase(text_lower: str, phrase: str) -> bool:
    return phrase in text_lower


def classify_by_name(name: str) -> Optional[ClassificationResult]:
    tokens = _tokens(name)
    lower = name.lower()

    if _has_phrase(lower, "commercial invoice"):
        return ClassificationResult(DOC_INVOICE, "HIGH", "name contains 'commercial invoice'")
    if _has_phrase(lower, "proforma invoice") or _has_token(tokens, "pi"):
        return ClassificationResult(DOC_PROFORMA_INVOICE, "HIGH", "name indicates proforma invoice")
    if _has_phrase(lower, "sales confirmation"):
        return ClassificationResult(DOC_SALES_CONFIRMATION, "HIGH", "name contains 'sales confirmation'")
    if _has_phrase(lower, "payment request"):
        return ClassificationResult(DOC_PAYMENT_REQUEST, "HIGH", "name contains 'payment request'")
    if _has_phrase(lower, "packing list") or _has_phrase(lower, "packinglist") or _has_token(tokens, "pl"):
        return ClassificationResult(DOC_PACKING_LIST, "HIGH", "name indicates packing list")
    if _has_phrase(lower, "delivery receipt") or _has_phrase(lower, "deliveryreceipt"):
        return ClassificationResult(DOC_DELIVERY_RECEIPT, "HIGH", "name contains 'delivery receipt'")
    if _has_phrase(lower, "cargo receipt") or _has_phrase(lower, "cargoreciept") or _has_phrase(lower, "cargoreceipt"):
        return ClassificationResult(DOC_CARGO_RECEIPT, "HIGH", "name contains 'cargo receipt'")
    if _has_phrase(lower, "bill of lading") or _has_token(tokens, "bl"):
        # LOW confidence: a real sample had SAP's own attachment title say
        # "BL" while the actual content was a Delivery Receipt - the name
        # alone is not trustworthy here, content inspection must confirm.
        return ClassificationResult(DOC_BL, "LOW", "name indicates B/L - verify with content (filenames here are unreliable)")
    if _has_phrase(lower, "air waybill") or _has_token(tokens, "awb"):
        return ClassificationResult(DOC_AWB, "HIGH", "name indicates AWB")
    if any(_has_token(tokens, kw) for kw in COURIER_KEYWORDS):
        return ClassificationResult(DOC_COURIER, "HIGH", "name indicates a courier company")
    if _has_token(tokens, "ci") or _has_phrase(lower, "invoice"):
        return ClassificationResult(DOC_INVOICE, "LOW", "name loosely suggests invoice - verify with content")
    return None


def classify_by_content(text: str) -> Optional[ClassificationResult]:
    if not text or not text.strip():
        return None
    lower = text.lower()

    if "commercial invoice" in lower:
        return ClassificationResult(DOC_INVOICE, "HIGH", "content contains 'COMMERCIAL INVOICE'")
    if "proforma invoice" in lower:
        return ClassificationResult(DOC_PROFORMA_INVOICE, "HIGH", "content contains 'PROFORMA INVOICE'")
    if "sales" in lower and "confirmation" in lower:
        return ClassificationResult(DOC_SALES_CONFIRMATION, "HIGH", "content contains 'SALES CONFIRMATION'")
    if "payment" in lower and "request" in lower:
        return ClassificationResult(DOC_PAYMENT_REQUEST, "HIGH", "content contains 'PAYMENT REQUEST'")
    if "packing list" in lower:
        return ClassificationResult(DOC_PACKING_LIST, "HIGH", "content contains 'PACKING LIST'")
    if "delivery receipt" in lower:
        return ClassificationResult(DOC_DELIVERY_RECEIPT, "HIGH", "content contains 'DELIVERY RECEIPT'")
    if "cargo receipt" in lower:
        return ClassificationResult(DOC_CARGO_RECEIPT, "HIGH", "content contains 'CARGO RECEIPT'")
    if "bill of lading" in lower:
        return ClassificationResult(DOC_BL, "HIGH", "content contains 'BILL OF LADING'")
    if _BL_NUMBER_RE.search(lower):
        # Confirmed real case: a genuine house B/L (has B/L Number, Port
        # of Loading/Discharge, Vessel, "SURRENDERED B/L", "Shipper's
        # Load & Count") never spells out "Bill of Lading" anywhere,
        # always abbreviating it as "B/L" - the exact-phrase check above
        # misses this carrier's template entirely.
        return ClassificationResult(DOC_BL, "HIGH", "content contains 'B/L Number'")
    if "air waybill" in lower or "airway bill" in lower:
        return ClassificationResult(DOC_AWB, "HIGH", "content contains 'AIR WAYBILL'")
    if any(kw in lower for kw in COURIER_KEYWORDS):
        return ClassificationResult(DOC_COURIER, "LOW", "content mentions a courier company name")
    if "invoice" in lower:
        # Real OCR'd sample said just "INVOICE" (as a UN Layout Key title),
        # never the exact phrase "COMMERCIAL INVOICE" - accept the looser
        # match too rather than missing it, but at lower confidence since
        # OCR noise / unrelated mentions of the word are possible.
        return ClassificationResult(DOC_INVOICE, "LOW", "content mentions 'invoice' but not the exact 'COMMERCIAL INVOICE' phrase")
    return None


def classify_component(name: str, text: str) -> ClassificationResult:
    """Classify one document component (e.g. one Excel sheet).

    An empty component (no extractable text at all - confirmed real case:
    a "BL" sheet that exists but is completely blank) is flagged via
    is_empty and must NOT be counted as document presence by callers,
    regardless of its name/type.
    """
    is_empty = not text or not text.strip()

    by_name = classify_by_name(name)
    by_content = classify_by_content(text)

    if by_name and by_name.confidence == "HIGH":
        result = by_name
    elif by_content:
        result = by_content
    elif by_name:
        result = by_name
    else:
        result = ClassificationResult(DOC_UNKNOWN, "LOW", "no filename or content match - needs manual review (문서 종류 확인 필요)")

    result.is_empty = is_empty
    return result
