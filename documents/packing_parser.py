"""
Parse a Packing List document component: per project rules, we mainly
need existence + Shipper/Consignee + a reference number to cross-check
against the invoice.

Same UN Layout Key style template as the commercial invoice in our real
sample ("SHIPPING PACKING LIST" sheet shared the identical Seller/Buyer/
Carrier box layout) - reuses the shared label-proximity helpers.
"""
from __future__ import annotations

from typing import Any, Optional

from .common import extract_consignee, extract_seller, find_label_cell, find_value_near


def extract_reference_number(rows: list[tuple[Any, ...]]) -> Optional[str]:
    hit = find_label_cell(rows, ["no. & date of invoice", "reference no", "ref no"])
    return find_value_near(rows, *hit) if hit else None


def parse_packing_list(rows: list[tuple[Any, ...]]) -> dict[str, Any]:
    return {
        "Shipper": extract_seller(rows),
        "Consignee": extract_consignee(rows),
        "Reference_Number": extract_reference_number(rows),
    }
