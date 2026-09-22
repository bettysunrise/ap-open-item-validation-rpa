"""Rule: SAP AP Currency vs Invoice Currency must match exactly."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class CurrencyMatchResult:
    status: str  # GREEN | YELLOW | RED
    reason: str


def compare_currency(sap_currency: Optional[str], invoice_currency: Optional[str]) -> CurrencyMatchResult:
    a = (sap_currency or "").strip().upper()
    b = (invoice_currency or "").strip().upper()

    if not a or not b:
        return CurrencyMatchResult("YELLOW", "Currency 확인 필요 (값 누락)")
    if a == b:
        return CurrencyMatchResult("GREEN", "")
    return CurrencyMatchResult("RED", "SAP Currency와 Invoice Currency 불일치")
