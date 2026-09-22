"""
Parse a B/L, AWB, or Courier document component: Shipper, Consignee,
document number, and the ship/flight/on-board date (used later for FOB
posting-date validation).

Not yet validated against a real populated B/L/AWB sheet (our one real
sample's "BL" sheet was present but completely empty - the shipment
actually moved by courier, with the courier waybill number embedded in
the Commercial Invoice's "Carrier" field instead - see
documents/invoice_parser.py extract_carrier_info/extract_sailing_date).
This parser follows the same UN Layout Key label conventions as the
invoice/packing-list parsers since B/L forms typically share that
numbering; it MUST be re-validated against a real B/L/AWB sample before
being trusted.
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

COURIER_KEYWORDS = ["dhl", "fedex", "ups", "ems", "tnt"]

# "Delivery Receipt" / "Cargo Receipt" real field labels (confirmed live
# 2026-09-15 - this business's actual proof-of-shipment documents for
# domestic/local-trucking moves, a completely different layout from the
# UN Layout Key B/L-style templates).
_DOC_NUMBER_KEYWORDS = [
    "b/l no", "bl no", "bill of lading no", "awb no", "air waybill no", "waybill no",
    "delivery receipt no", "cargo receipt no",
]
_DATE_KEYWORDS = [
    "on board date", "sailing on or about", "sailing date", "date of shipment", "flight date",
    "shipment date",
]


def extract_document_number(rows: list[tuple[Any, ...]]) -> Optional[str]:
    hit = find_label_cell(rows, _DOC_NUMBER_KEYWORDS)
    if hit:
        value = find_value_near(rows, *hit, label_keywords=_DOC_NUMBER_KEYWORDS)
        if value:
            return value
    # Fall back: a waybill number is sometimes embedded inline, e.g.
    # "DHL(WAYBILL 44 7205 7483)".
    for row in rows:
        for cell in row:
            text = cell_text(cell)
            match = re.search(r"waybill\s*[:#]?\s*([\d\s]{6,})", text, re.IGNORECASE)
            if match:
                return match.group(1).strip()
    return None


def extract_on_board_date(rows: list[tuple[Any, ...]]):
    hit = find_label_cell(rows, _DATE_KEYWORDS)
    if not hit:
        return None
    # Try the structured (Excel date-cell) path first, then the
    # text-pattern path (PDF/OCR rows never have real date cells).
    return find_date_near(rows, *hit) or find_date_in_text_near(rows, *hit, label_keywords=_DATE_KEYWORDS)


def extract_courier_name(rows: list[tuple[Any, ...]]) -> Optional[str]:
    for row in rows:
        for cell in row:
            text = cell_text(cell).lower()
            for kw in COURIER_KEYWORDS:
                if kw in text:
                    return kw.upper()
    return None


def parse_transport_document(rows: list[tuple[Any, ...]]) -> dict[str, Any]:
    return {
        "Shipper": extract_seller(rows),
        "Consignee": extract_consignee(rows),
        "Document_Number": extract_document_number(rows),
        "On_Board_Date": extract_on_board_date(rows),
        "Courier_Name": extract_courier_name(rows),
    }
