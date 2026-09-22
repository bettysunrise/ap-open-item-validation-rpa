"""
Rules 01-03: Invoice and Packing List are mandatory; at least one
transport document (B/L, AWB, or Courier - including courier evidence
embedded directly in the invoice, per documents/evaluator.py) is
required. Rule 04 (combined CI/PL in one file) is handled upstream by
documents/evaluator.py, which already treats "Invoice present" and
"Packing List present" independently regardless of which file/sheet they
came from.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RequiredDocsResult:
    status: str  # GREEN | RED (never uncertain - existence is a hard fact once documents are read)
    reasons: list[str] = field(default_factory=list)


def check_required_docs(has_invoice: bool, has_packing_list: bool, has_transport_doc: bool) -> RequiredDocsResult:
    reasons: list[str] = []
    if not has_invoice:
        reasons.append("Invoice 미첨부")
    if not has_packing_list:
        reasons.append("Packing List 미첨부")
    if not has_transport_doc:
        reasons.append("BL/AWB/Courier 운송증빙 미첨부")

    return RequiredDocsResult("RED" if reasons else "GREEN", reasons)
