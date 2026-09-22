"""
Parse a Commercial Invoice document component (e.g. one Excel sheet
classified as DOC_INVOICE) into the fields Phase 5 validation needs:
Vendor/Seller, Currency, Total Amount, Invoice Number, Invoice Date,
Consignee/Buyer.

Also extracts a bonus "Carrier_Info" / "Sailing_Date" pair when present -
confirmed live (2026-09-15) that some vendors embed courier/shipping
evidence (e.g. "DHL(WAYBILL 44 7205 7483)" + a sailing date) directly on
the Commercial Invoice itself rather than as a separate courier document.
This can serve as supporting (not automatically sufficient - flag for
review) evidence toward Rule 03's transport-document requirement when no
separate B/L/AWB/courier document exists.

Heuristic, validated against one real sample so far (a UN Layout Key
style invoice - a common industry template, not vendor-specific, so this
should generalize reasonably, but MUST be re-validated against more real
vendor invoices before being trusted at scale). Anything not confidently
located is returned as None - callers must treat that as "needs review"
(YELLOW), never guess a value.
"""
from __future__ import annotations

import re
from typing import Any, Optional

from .common import (
    cell_text,
    extract_consignee,
    extract_seller,
    find_date_in_text_near,
    find_date_near,
    find_label_cell,
    find_value_near,
)

AMOUNT_LABEL_RE = re.compile(r"(grand\s*t?tl\s*amount|total\s*amount|grand\s*total)", re.IGNORECASE)
TOTAL_ONLY_RE = re.compile(r"^total$", re.IGNORECASE)
CURRENCY_SYMBOL_MAP = {"$": "USD", "₩": "KRW", "¥": "JPY", "€": "EUR", "£": "GBP"}
CURRENCY_CODE_RE = re.compile(r"\b(USD|KRW|JPY|CNY|EUR|GBP|HKD|VND|MMK|IDR)\b")
# Some vendors abbreviate the currency to 2 letters in a table cell
# (confirmed real case: "US" instead of "USD" next to a TOTAL row).
CURRENCY_ABBREVIATIONS = {"US": "USD", "US$": "USD", "RMB": "CNY", "HK": "HKD"}
AMOUNT_NUMBER_RE = re.compile(r"[\d,]+\.?\d*")


def extract_invoice_number(rows: list[tuple[Any, ...]]) -> Optional[str]:
    # "No and Date of Invoice" (no punctuation) is a real 3rd-vendor
    # variant of "No. & Date of Invoice" - OCR also tends to drop "&"/".".
    keywords = [
        "no. & date of invoice", "no & date of invoice", "no and date of invoice",
        "invoice no", "invoice number",
    ]
    hit = find_label_cell(rows, keywords)
    value = find_value_near(rows, *hit, label_keywords=keywords) if hit else None
    return value if _looks_like_plausible_reference(value) else None


_COMPANY_NAME_MARKERS_RE = re.compile(r"\b(CO\.?,?\s*LTD|LIMITED|LLC|INC|CORP)\b", re.IGNORECASE)


def _looks_like_plausible_reference(value: Optional[str]) -> bool:
    """A real invoice/reference number is short and alphanumeric-with-
    dashes (e.g. 'AR-03/2025', 'GLCEO-26040128', 'S23-8H006'). Confirmed
    real OCR bug: two side-by-side columns landed on one text line, so
    the 'invoice number' label's neighbor value came back as a full
    company name (30+ chars, contains 'CO.,LTD'). Better to report
    nothing (-> YELLOW downstream) than a value that's obviously wrong."""
    if not value:
        return True  # nothing to reject
    if len(value) > 30:
        return False
    if _COMPANY_NAME_MARKERS_RE.search(value):
        return False
    return True


def extract_carrier_info(rows: list[tuple[Any, ...]]) -> Optional[str]:
    keywords = ["carrier"]
    hit = find_label_cell(rows, keywords)
    return find_value_near(rows, *hit, max_row_offset=3, label_keywords=keywords) if hit else None


def extract_sailing_date(rows: list[tuple[Any, ...]]):
    keywords = ["sailing on or about", "sailing date", "date of shipment"]
    hit = find_label_cell(rows, keywords)
    if not hit:
        return None
    return find_date_near(rows, *hit) or find_date_in_text_near(rows, *hit, label_keywords=keywords)


def extract_total_amount(rows: list[tuple[Any, ...]]) -> tuple[Optional[str], Optional[str]]:
    """Scan for a 'grand total amount'-style cell that embeds both the
    currency symbol/code and the number in one cell (confirmed real
    pattern: 'GRAND TTL AMOUNT$270').

    Falls back to a row-based pattern (confirmed real, second vendor):
    a cell containing exactly 'TOTAL' with quantity/unit/currency/amount
    spread across later cells in the SAME row - the last numeric cell in
    that row is taken as the amount, and any recognized currency
    code/abbreviation elsewhere in the row as the currency.
    """
    for row in rows:
        for cell in row:
            text = cell_text(cell)
            if not text or not AMOUNT_LABEL_RE.search(text):
                continue
            currency = None
            code_match = CURRENCY_CODE_RE.search(text)
            if code_match:
                currency = code_match.group(1)
            else:
                for sym, code in CURRENCY_SYMBOL_MAP.items():
                    if sym in text:
                        currency = code
                        break
            amounts = AMOUNT_NUMBER_RE.findall(text)
            amount = amounts[-1] if amounts else None
            if amount:
                return currency, amount

    for row in rows:
        if not any(TOTAL_ONLY_RE.match(cell_text(c)) for c in row if c is not None):
            continue
        numeric_cells = [c for c in row if isinstance(c, (int, float))]
        if not numeric_cells:
            continue
        amount = numeric_cells[-1]
        currency = None
        for cell in row:
            token = cell_text(cell).upper()
            if token in CURRENCY_ABBREVIATIONS:
                currency = CURRENCY_ABBREVIATIONS[token]
                break
            if CURRENCY_CODE_RE.fullmatch(token):
                currency = token
                break
        return currency, str(amount)

    # Third fallback (line-based text - PDF/OCR content reshaped into
    # one-line-per-row by documents/pdf_extractor.py): a whole line
    # STARTING with "TOTAL" followed by numbers on that same line, e.g.
    # "TOTAL 10,051 8,873.54" - unlike the grid-cell case, the line is
    # never just the bare word "total", so TOTAL_ONLY_RE (exact match)
    # doesn't apply here.
    #
    # NOTE: an earlier attempt to prefer a currency-bearing "total" line
    # over a bare one (to dodge a "Total Quantity: 405"-style false match)
    # was tried and reverted 2026-09-18 - confirmed live it broke a
    # previously-correct real case (a real invoice had the true grand
    # total on a currency-less line, "TOTAL 21,372 15,764.48", but ALSO a
    # per-line-item subtotal on a currency-bearing line, "Total 26,493)
    # YDS USD 20,329.50" - preferring the currency-bearing line grabbed
    # the wrong one). Multiple "total"-prefixed lines with different
    # meanings appear in real invoices and can't be reliably disambiguated
    # by currency-presence alone, so this keeps the simpler "first match
    # wins" behavior that was already validated against real samples.
    for row in rows:
        for cell in row:
            text = cell_text(cell)
            if not re.match(r"^total\b", text, re.IGNORECASE):
                continue
            amounts = AMOUNT_NUMBER_RE.findall(text)
            if not amounts:
                continue
            currency = None
            code_match = CURRENCY_CODE_RE.search(text)
            if code_match:
                currency = code_match.group(1)
            else:
                for sym, code in CURRENCY_SYMBOL_MAP.items():
                    if sym in text:
                        currency = code
                        break
            return currency, amounts[-1]

    return None, None


def parse_commercial_invoice(rows: list[tuple[Any, ...]]) -> dict[str, Any]:
    currency, amount = extract_total_amount(rows)
    return {
        "Vendor_Seller": extract_seller(rows),
        "Consignee_Buyer": extract_consignee(rows),
        "Invoice_Number": extract_invoice_number(rows),
        "Currency": currency,
        "Total_Amount": amount,
        "Carrier_Info": extract_carrier_info(rows),
        "Sailing_Date": extract_sailing_date(rows),
    }
