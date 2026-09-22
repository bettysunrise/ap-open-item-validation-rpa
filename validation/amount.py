"""
Rule: SAP AP Amount vs Commercial Invoice Total Amount must be equal.

Uses Decimal (never float) for financial comparisons per project rule.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Optional


@dataclass
class AmountMatchResult:
    status: str  # GREEN | YELLOW | RED
    reason: str
    sap_amount: Optional[Decimal]
    other_amount: Optional[Decimal]
    difference: Optional[Decimal]  # other - sap


def to_decimal(value: Any) -> Optional[Decimal]:
    """Parse a SAP- or document-formatted number string into Decimal.
    Returns None (never a guessed/rounded value) if it can't be parsed
    confidently.

    Confirmed real case: an Excel formula cell (e.g. '=SUM(I31)') displays
    as "$792.85" but openpyxl reads its cached result as a raw Python
    float with IEEE-754 noise (792.8499999999849) - str()'ing that float
    reproduces the noise verbatim, so comparing against SAP's clean
    "792.85" fails by ~1e-11. A float value is rounded to 2 decimal places
    (currency's real precision) before converting - this only strips
    binary floating-point representation noise (always far below a cent),
    never a genuine calculation error (which shows up at the cent level
    or above and still triggers RED after rounding). Values already
    given as strings (OCR/PDF-extracted text) never have this artifact
    and are left untouched."""
    if value is None:
        return None
    if isinstance(value, float):
        value = round(value, 2)
    try:
        s = str(value).replace(",", "").strip()
        if s == "":
            return None
        return Decimal(s)
    except InvalidOperation:
        return None


def compare_amount(sap_amount: Any, invoice_amount: Any) -> AmountMatchResult:
    sap_dec = to_decimal(sap_amount)
    inv_dec = to_decimal(invoice_amount)

    if sap_dec is None or inv_dec is None:
        return AmountMatchResult("YELLOW", "금액 확인 필요 (값 누락 또는 형식 오류)", sap_dec, inv_dec, None)

    difference = inv_dec - sap_dec
    if difference == 0:
        return AmountMatchResult("GREEN", "", sap_dec, inv_dec, difference)

    return AmountMatchResult("RED", "SAP AP 금액과 Invoice Total 불일치", sap_dec, inv_dec, difference)
