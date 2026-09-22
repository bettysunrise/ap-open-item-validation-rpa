"""
Generate a fully synthetic sample report (docs/sample_report.xlsx) for the
portfolio - fictional vendors, fictional amounts, fictional group entities.
No real business data is used anywhere in this script or its output.

Run from the project root: python docs/generate_sample_report.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from validation.engine import ItemValidationResult  # noqa: E402
from report.excel_report import write_raw_grid_report  # noqa: E402
from report.summary import summarize  # noqa: E402

rows = [
    {
        "Source_Row": 1, "Row_Type": "ITEM", "Invoice_Doc_No": "1000100001",
        "PO_Number": "4500100001", "Posting_Date": "2026.08.10",
        "Accounting_Doc": "5100100001", "Vendor_Code": "0000100001",
        "Vendor_Name": "NORTHSTAR GARMENT CO., LTD", "Currency": "USD",
        "Total_Amount": "12,450.00",
    },
    {
        "Source_Row": 2, "Row_Type": "ITEM", "Invoice_Doc_No": "1000100002",
        "PO_Number": "4500100002", "Posting_Date": "2026.08.12",
        "Accounting_Doc": "5100100002", "Vendor_Code": "0000100002",
        "Vendor_Name": "ARIA YANGON CO., LTD", "Currency": "USD",
        "Total_Amount": "8,204.50",
    },
    {
        "Source_Row": 3, "Row_Type": "ITEM", "Invoice_Doc_No": "1000100003",
        "PO_Number": "4500100003", "Posting_Date": "2026.08.14",
        "Accounting_Doc": "5100100003", "Vendor_Code": "0000100003",
        "Vendor_Name": "BLUEOCEAN TRADING LIMITED", "Currency": "USD",
        "Total_Amount": "31,900.00",
    },
    {
        "Source_Row": 4, "Row_Type": "ITEM", "Invoice_Doc_No": "1000100004",
        "PO_Number": "4500100004", "Posting_Date": "2026.08.15",
        "Accounting_Doc": "5100100004", "Vendor_Code": "0000100004",
        "Vendor_Name": "GREATWALL FOREIGN TRADE CO.", "Currency": "USD",
        "Total_Amount": "5,600.00",
    },
    {
        "Source_Row": 5, "Row_Type": "ITEM", "Invoice_Doc_No": "1000100005",
        "PO_Number": "4500100005", "Posting_Date": "2026.08.18",
        "Accounting_Doc": "5100100005", "Vendor_Code": "0000100005",
        "Vendor_Name": "PT MEKAR TEKSTIL INDONESIA", "Currency": "USD",
        "Total_Amount": "19,320.75",
    },
    {
        "Source_Row": 6, "Row_Type": "ITEM", "Invoice_Doc_No": "1000100006",
        "PO_Number": "4500100006", "Posting_Date": "2026.08.20",
        "Accounting_Doc": "5100100006", "Vendor_Code": "0000100006",
        "Vendor_Name": "SAKURA APPAREL CO., LTD", "Currency": "JPY",
        "Total_Amount": "1,204,000",
    },
    {
        "Source_Row": 7, "Row_Type": "SUBTOTAL", "Currency": "USD", "Total_Amount": "77,475.25",
    },
]

results = [
    ItemValidationResult(
        Source_Row=1, Final_Status="GREEN",
        Vendor_Match="GREEN", Amount_Match="GREEN", Currency_Match="GREEN",
        Group_Consignee_Check="GREEN",
        Invoice_Vendor="NORTHSTAR GARMENT CO., LTD", Invoice_Currency="USD",
        Invoice_Total_Amount="12,450.00", Invoice_Consignee="ARIA CO., LTD.",
        Transport_Source="BL sheet", reasons=[],
    ),
    ItemValidationResult(
        Source_Row=2, Final_Status="YELLOW",
        Vendor_Match="GREEN", Amount_Match="GREEN", Currency_Match="GREEN",
        Group_Consignee_Check="GREEN",
        Invoice_Vendor="ARIA YANGON CO., LTD", Invoice_Currency="USD",
        Invoice_Total_Amount="8,204.50", Invoice_Consignee="ARY",
        Transport_Source="embedded in invoice (no separate transport document attached)",
        reasons=["BL/AWB/Courier 운송증빙 미첨부"],
    ),
    ItemValidationResult(
        Source_Row=3, Final_Status="RED",
        Vendor_Match="RED", Amount_Match="GREEN", Currency_Match="GREEN",
        Group_Consignee_Check="GREEN",
        Invoice_Vendor="BLUE OCEAN TRADE LTD", Invoice_Currency="USD",
        Invoice_Total_Amount="31,900.00", Invoice_Consignee="ARIA CO., LTD.",
        Transport_Source="AWB sheet",
        reasons=["SAP Vendor와 Invoice/Shipper 불일치"],
    ),
    ItemValidationResult(
        Source_Row=4, Final_Status="RED",
        Vendor_Match="GREEN", Amount_Match="RED", Currency_Match="GREEN",
        Group_Consignee_Check="GREEN", Amount_Difference="-350.00",
        Invoice_Vendor="GREATWALL FOREIGN TRADE CO.", Invoice_Currency="USD",
        Invoice_Total_Amount="5,250.00", Invoice_Consignee="ARIA CO., LTD.",
        Transport_Source="BL sheet",
        reasons=["SAP AP 금액과 Invoice Total 불일치"],
    ),
    ItemValidationResult(
        Source_Row=5, Final_Status="RED",
        Vendor_Match="GREEN", Amount_Match="GREEN", Currency_Match="GREEN",
        Group_Consignee_Check="RED",
        Invoice_Vendor="PT MEKAR TEKSTIL INDONESIA", Invoice_Currency="USD",
        Invoice_Total_Amount="19,320.75", Invoice_Consignee="NEXAR INTERNATIONAL CO., LTD",
        Transport_Source="BL sheet",
        reasons=["⚠ Consignee가 등록된 그룹사 법인과 일치하지 않습니다: NEXAR INTERNATIONAL CO., LTD / 그룹사 법인으로 변경 필요"],
    ),
    ItemValidationResult(
        Source_Row=6, Final_Status="YELLOW",
        reasons=["인보이스가 여러 건 발견됨 - 어느 것이 맞는지 확인 필요"],
    ),
]

summary_stats = summarize(results)
meta = {
    "Run Date": "2026-01-01T09:00:00",
    "Company Code": "1000",
    "Search Start Date": "2024-01-01",
    "Search End Date": "2026-01-01",
    "Open Items Only": True,
    "_note": "Synthetic sample data for portfolio purposes - no real business data.",
}

out = write_raw_grid_report(
    rows,
    ROOT / "docs" / "sample_report.xlsx",
    meta=meta,
    validation_results=results,
    summary_stats=summary_stats,
)
print("Wrote", out)
print("GREEN/YELLOW/RED:", summary_stats["GREEN Count"], summary_stats["YELLOW Count"], summary_stats["RED Count"])
