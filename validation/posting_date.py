"""
Rule: for FOB transactions, asset recognition is based on ETD - SAP
Posting Date must equal the B/L (or embedded courier) On Board Date.

FOB detection source: the Incoterm field (ZTITIVK-INCO1, e.g. "FOB",
"CIF") read from the Commercial Invoice detail screen in
sap/document_detail.py (Phase 2) - discovered live, not guessed. If that
field is unavailable, this rule is simply not applicable (never inferred
from anything else).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional


@dataclass
class PostingDateMatchResult:
    status: str  # GREEN | YELLOW | RED
    reason: str
    applicable: bool  # False when the item isn't FOB - rule doesn't apply


def is_fob(incoterm: Optional[str]) -> bool:
    return bool(incoterm) and "fob" in incoterm.strip().lower()


def compare_posting_date(
    sap_posting_date: Optional[date],
    on_board_date: Optional[date],
    incoterm: Optional[str],
) -> PostingDateMatchResult:
    if not is_fob(incoterm):
        return PostingDateMatchResult("GREEN", "", applicable=False)

    if on_board_date is None:
        return PostingDateMatchResult("YELLOW", "BL On Board Date 확인 필요", applicable=True)

    if sap_posting_date is None:
        return PostingDateMatchResult("YELLOW", "SAP Posting Date 확인 필요", applicable=True)

    if sap_posting_date == on_board_date:
        return PostingDateMatchResult("GREEN", "", applicable=True)

    return PostingDateMatchResult(
        "RED",
        "FOB 자산 인식일 불일치: SAP Posting Date ≠ BL On Board Date",
        applicable=True,
    )
