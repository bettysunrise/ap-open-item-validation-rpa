"""
Compute SUMMARY sheet statistics (counts by final status and by error
category) from a list of validation/engine.ItemValidationResult.
"""
from __future__ import annotations

from collections import Counter
from typing import Any

ERROR_CATEGORIES = [
    "Invoice 미첨부",
    "Packing List 미첨부",
    "BL/AWB/Courier 운송증빙 미첨부",
    "SAP Vendor와 Invoice/Shipper 불일치",
    "SAP AP 금액과 Invoice Total 불일치",
    "SAP Currency와 Invoice Currency 불일치",
    "FOB 자산 인식일 불일치: SAP Posting Date ≠ BL On Board Date",
]


def summarize(results: list[Any]) -> dict[str, Any]:
    status_counts = Counter(r.Final_Status for r in results)
    error_counts: Counter[str] = Counter()

    for r in results:
        for category in ERROR_CATEGORIES:
            if category in r.Error_Reason:
                error_counts[category] += 1
        if any(consignee_marker in r.Error_Reason for consignee_marker in ("그룹사 법인으로 변경 필요",)):
            error_counts["Consignee 오류"] += 1

    return {
        "Total Items": len(results),
        "GREEN Count": status_counts.get("GREEN", 0),
        "YELLOW Count": status_counts.get("YELLOW", 0),
        "RED Count": status_counts.get("RED", 0),
        "error_counts": dict(error_counts),
    }
