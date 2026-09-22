"""
Unified entry point: sniff a downloaded attachment's REAL format from its
content (never trust the extension - confirmed real case: a file saved
locally as ".xls" was actually a real .xlsx/OOXML zip) and dispatch to
the matching extractor.

Formats supported: PDF (text-layer + OCR fallback), OOXML .xlsx, legacy
BIFF .xls, RTF (confirmed real case: every ".doc"-named attachment seen
in this system is actually plain RTF, not binary Word), and standalone
JPEG/PNG images (OCR).

Not supported: a genuine OLE-based binary .doc (no real sample has been
seen in this system - only RTF misnamed as .doc - so this is not built
until one actually shows up).
"""
from __future__ import annotations

from pathlib import Path

import olefile

from .excel_extractor import DocumentComponent, extract_excel_components, is_real_xlsx
from .image_extractor import extract_image_components
from .legacy_excel_extractor import extract_legacy_xls_components
from .pdf_extractor import extract_pdf_components
from .rtf_extractor import extract_rtf_components

_OLE_SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


def _is_pdf(path: Path) -> bool:
    try:
        with open(path, "rb") as f:
            return f.read(5) == b"%PDF-"
    except OSError:
        return False


def _is_jpeg(path: Path) -> bool:
    try:
        with open(path, "rb") as f:
            return f.read(3) == b"\xff\xd8\xff"
    except OSError:
        return False


def _is_png(path: Path) -> bool:
    try:
        with open(path, "rb") as f:
            return f.read(8) == b"\x89PNG\r\n\x1a\n"
    except OSError:
        return False


def _is_rtf(path: Path) -> bool:
    try:
        with open(path, "rb") as f:
            return f.read(5) == b"{\\rtf"
    except OSError:
        return False


def _is_legacy_ole(path: Path) -> bool:
    try:
        with open(path, "rb") as f:
            return f.read(8) == _OLE_SIGNATURE
    except OSError:
        return False


def _legacy_ole_kind(path: Path) -> str:
    """Distinguish a real legacy .xls (BIFF, stream 'Workbook'/'Book') from
    a real legacy binary .doc (stream 'WordDocument') - both share the
    exact same OLE compound-file signature, so the signature alone isn't
    enough (checked live: real streams present in the confirmed .xls
    samples are 'Workbook')."""
    try:
        ole = olefile.OleFileIO(str(path))
        try:
            if ole.exists("Workbook") or ole.exists("Book"):
                return "xls"
            if ole.exists("WordDocument"):
                return "doc"
        finally:
            ole.close()
    except Exception:  # noqa: BLE001
        pass
    return "unknown"


def extract_components(path: str | Path) -> list[DocumentComponent]:
    path = Path(path)

    # Office lock/temp files (e.g. "~$foo.xlsx") are created transiently
    # when a viewer app opens a file - confirmed real leftover found after
    # a batch run, not a real attachment. Never attempt to parse these.
    if path.name.startswith("~$"):
        raise ValueError(f"{path} is an Office lock/temp file, not a real attachment.")

    if _is_pdf(path):
        return extract_pdf_components(path)

    if _is_jpeg(path) or _is_png(path):
        return extract_image_components(path)

    if _is_rtf(path):
        return extract_rtf_components(path)

    # Check the exact OLE signature BEFORE the fuzzy zipfile.is_zipfile()
    # check - is_real_xlsx() can false-positive on a genuine legacy .xls
    # (confirmed live).
    if _is_legacy_ole(path):
        kind = _legacy_ole_kind(path)
        if kind == "xls":
            return extract_legacy_xls_components(path)
        if kind == "doc":
            raise ValueError(
                f"{path} is a genuine OLE-based binary .doc file - not yet supported "
                f"(no real sample of this format has been seen in this system; every "
                f"'.doc'-named attachment seen so far has actually been RTF)."
            )
        raise ValueError(f"{path} is an OLE compound file but neither an Excel nor Word stream was found inside it.")

    if is_real_xlsx(path):
        return extract_excel_components(path)

    raise ValueError(
        f"{path} is not a recognized/supported format "
        f"(checked PDF, JPEG/PNG, RTF, OLE .xls/.doc, and xlsx signatures)."
    )
