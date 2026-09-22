"""
Extract text/rows from an Excel attachment for classification and parsing.

Confirmed live (2026-09-15, see sap/attachment.py docstring): SAP-downloaded
attachments can have a misleading extension (a real .xlsx/OOXML file saved
locally as ".xls"). Always sniff the real format from content instead of
trusting the extension.

A single attachment can bundle several document types as separate sheets
(confirmed real example: one workbook with "VENDOR PI", "SALES
CONFIRMATION", "PAYMENT REQUEST", "INVOICE", "BL", "SHIPPING PACKING
LIST", " PACKING LIST " sheets). Each sheet is treated as one candidate
document component to classify independently.
"""
from __future__ import annotations

import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import openpyxl


@dataclass
class DocumentComponent:
    """One classifiable unit extracted from an attachment (e.g. one sheet)."""

    source_file: str
    component_name: str  # sheet name
    rows: list[tuple[Any, ...]] = field(default_factory=list)
    text: str = ""  # all non-empty cell values, joined, for keyword search


def is_real_xlsx(path: str | Path) -> bool:
    """Sniff whether a file is really an OOXML/xlsx zip, regardless of its
    on-disk extension (SAP-downloaded attachments can be mislabeled)."""
    try:
        return zipfile.is_zipfile(path)
    except Exception:  # noqa: BLE001
        return False


def extract_excel_components(path: str | Path) -> list[DocumentComponent]:
    """Read every sheet of an Excel file into a DocumentComponent.

    Raises ValueError if the file isn't actually a readable xlsx (content
    sniffed, not judged by extension).
    """
    path = Path(path)
    if not is_real_xlsx(path):
        raise ValueError(f"{path} does not look like a real .xlsx (OOXML zip) file")

    wb = openpyxl.load_workbook(path, data_only=True)
    components: list[DocumentComponent] = []

    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        rows: list[tuple[Any, ...]] = list(ws.iter_rows(values_only=True))
        text_parts = [
            str(cell).strip()
            for row in rows
            for cell in row
            if cell is not None and str(cell).strip() != ""
        ]
        components.append(
            DocumentComponent(
                source_file=str(path),
                component_name=sheet_name,
                rows=rows,
                text="\n".join(text_parts),
            )
        )

    return components
