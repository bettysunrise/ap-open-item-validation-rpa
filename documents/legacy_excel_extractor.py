"""
Extract text/rows from a genuine legacy OLE .xls attachment (BIFF format)
using xlrd - openpyxl only reads OOXML/xlsx, so a real legacy .xls
(confirmed real samples in tests/fixtures/gos_samples/ and in the full
127-item production run - ~36 files) needs a separate reader.

Mirrors excel_extractor.py's per-sheet DocumentComponent shape so
downstream classification/parsing (documents/common.py etc.) is agnostic
to which format the sheet came from.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import xlrd

from .excel_extractor import DocumentComponent


def extract_legacy_xls_components(path: str | Path) -> list[DocumentComponent]:
    path = Path(path)
    book = xlrd.open_workbook(str(path))
    components: list[DocumentComponent] = []

    for sheet in book.sheets():
        rows: list[tuple[Any, ...]] = []
        text_parts: list[str] = []
        for r in range(sheet.nrows):
            row_values = tuple(sheet.cell_value(r, c) for c in range(sheet.ncols))
            rows.append(row_values)
            for cell in row_values:
                if cell is not None and str(cell).strip() != "":
                    text_parts.append(str(cell).strip())
        components.append(
            DocumentComponent(
                source_file=str(path),
                component_name=sheet.name,
                rows=rows,
                text="\n".join(text_parts),
            )
        )

    return components
