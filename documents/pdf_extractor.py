"""
Extract text/components from a PDF attachment - born-digital text layer
first, OCR fallback (Tesseract via pytesseract, page rendered with
PyMuPDF) for scanned pages.

Confirmed live 2026-09-15: real attachments in this SAP system (accessed
via sap/gos_attachment.py) are predominantly PDF - not Excel as first
assumed from a single early sample. They're a genuine MIX of born-digital
PDFs (real text layer - e.g. a "Delivery Receipt" that extracted ~4000
characters of clean tabular text directly) and fully scanned images with
ZERO text layer on every page (a real 36-page sample returned 0
characters via pypdf on every page checked) - OCR is not optional, it is
required for a large share of real documents.

OCR'd text matches the SAME UN Layout Key template used by the Excel
invoice samples (numbered boxes: "1.Supplier", "2.For Account and Risk
of Messers" / Buyer, "3.Notify Party or Consignee", "6.Carrier",
"7.Sailing on or about", "8.No and Date of Invoice", ...) just
linearized into sequential text lines - so the existing label-proximity
helpers in documents/common.py work on it too, once reshaped into
one-line-per-row "rows" (each a 1-tuple) to match their expected shape.

CRITICAL real finding: a single PDF can bundle MULTIPLE logical documents
across page ranges, the same way a single Excel file bundles multiple
sheets (confirmed: the 36-page sample above has page 1 = Commercial
Invoice, pages 2-3 = a sales-order-style page, and pages 10/20/30/35+ =
repeated "DELIVERY RECEIPT" pages, one per shipment that month). Treating
the whole PDF as one component would misclassify it as only ONE type and
silently lose the others - so this module splits a PDF into one
component per detected page-range instead of returning a single
document-wide blob.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from .excel_extractor import DocumentComponent

try:
    import fitz  # PyMuPDF
except ImportError:  # pragma: no cover
    fitz = None

try:
    import pytesseract
    from PIL import Image
except ImportError:  # pragma: no cover
    pytesseract = None
    Image = None

from pypdf import PdfReader

_TESSERACT_CMD_CANDIDATES = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
]


def _configure_tesseract() -> bool:
    if pytesseract is None:
        return False
    for path in _TESSERACT_CMD_CANDIDATES:
        if Path(path).exists():
            pytesseract.pytesseract.tesseract_cmd = path
            return True
    return False


OCR_AVAILABLE = _configure_tesseract()

MIN_TEXT_LENGTH_FOR_DIGITAL = 20  # below this, a page is treated as scanned/needs OCR
OCR_DPI = 200
OCR_LANGS = "eng+kor"
DEFAULT_MAX_OCR_PAGES = 15  # cap per file - a real 36-page scanned sample would otherwise be very slow.
# Confirmed live: a real "Delivery Receipt" section started at (0-based)
# page index 10 in a fully-scanned 36-page file - a budget of exactly 10
# missed it by one page, so this is set with a small margin above that.

# Coarse page-type markers used to detect where a new logical document
# starts within a multi-page PDF. Order matters - more specific phrases
# are checked first. This is intentionally a SUBSET of the full
# documents/classifier.py keyword set - just enough to find section
# boundaries; the real classification of each resulting component still
# goes through classify_component() same as everything else.
_PAGE_MARKER_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("COMMERCIAL_INVOICE", re.compile(r"commercial\s+invoice", re.IGNORECASE)),
    ("PROFORMA_INVOICE", re.compile(r"proforma\s+invoice", re.IGNORECASE)),
    ("DELIVERY_RECEIPT", re.compile(r"delivery\s+receipt", re.IGNORECASE)),
    ("CARGO_RECEIPT", re.compile(r"cargo\s+receipt", re.IGNORECASE)),
    ("PACKING_LIST", re.compile(r"packing\s+list", re.IGNORECASE)),
    ("BILL_OF_LADING", re.compile(r"bill\s+of\s+lading", re.IGNORECASE)),
    ("AIR_WAYBILL", re.compile(r"air\s*waybill", re.IGNORECASE)),
    ("SALES_CONFIRMATION", re.compile(r"sales\s+confirmation", re.IGNORECASE)),
    ("INVOICE", re.compile(r"\binvoice\b", re.IGNORECASE)),
]


def _detect_page_marker(text: str) -> Optional[str]:
    """Return a coarse marker name if this page looks like the START of a
    new logical document, else None (treated as a continuation of
    whatever section came before)."""
    if not text or not text.strip():
        return None
    for name, pattern in _PAGE_MARKER_PATTERNS:
        if pattern.search(text):
            return name
    return None


def _ocr_page(doc, page_index: int) -> str:
    if not OCR_AVAILABLE or fitz is None:
        return ""
    page = doc[page_index]
    pix = page.get_pixmap(dpi=OCR_DPI)
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    try:
        return pytesseract.image_to_string(img, lang=OCR_LANGS)
    except Exception:  # noqa: BLE001
        return ""


def extract_pdf_page_texts(path: str | Path, max_ocr_pages: int = DEFAULT_MAX_OCR_PAGES) -> list[tuple[str, bool]]:
    """Return [(page_text, used_ocr), ...] for every page: real text layer
    when available, OCR fallback otherwise (capped at max_ocr_pages OCR
    calls per file to bound runtime on very long scanned documents)."""
    path = Path(path)
    reader = PdfReader(path)
    results: list[tuple[str, bool]] = []
    ocr_budget = max_ocr_pages
    fitz_doc = None

    for i, page in enumerate(reader.pages):
        try:
            text = page.extract_text() or ""
        except Exception:  # noqa: BLE001
            text = ""

        if len(text.strip()) >= MIN_TEXT_LENGTH_FOR_DIGITAL:
            results.append((text, False))
            continue

        if ocr_budget <= 0 or not OCR_AVAILABLE:
            results.append(("", False))
            continue

        if fitz_doc is None and fitz is not None:
            fitz_doc = fitz.open(path)
        ocr_text = _ocr_page(fitz_doc, i) if fitz_doc is not None else ""
        results.append((ocr_text, bool(ocr_text.strip())))
        ocr_budget -= 1

    if fitz_doc is not None:
        fitz_doc.close()

    return results


def extract_pdf_components(path: str | Path, max_ocr_pages: int = DEFAULT_MAX_OCR_PAGES) -> list[DocumentComponent]:
    """Split a PDF into one DocumentComponent per detected page-range
    section (see module docstring - a single PDF can bundle several
    logical documents). Pages before the first detected marker (e.g. a
    cover page) are grouped into an initial untitled component so their
    text isn't silently dropped.
    """
    path = Path(path)
    page_texts = extract_pdf_page_texts(path, max_ocr_pages=max_ocr_pages)

    sections: list[dict] = []  # {"marker": str|None, "pages": [text, ...]}
    for text, _used_ocr in page_texts:
        marker = _detect_page_marker(text)
        if marker and (not sections or sections[-1]["marker"] != marker or sections[-1].get("closed")):
            sections.append({"marker": marker, "pages": [text]})
        elif sections:
            sections[-1]["pages"].append(text)
        else:
            sections.append({"marker": None, "pages": [text]})

    if not sections:
        sections = [{"marker": None, "pages": [""]}]

    components: list[DocumentComponent] = []
    for idx, section in enumerate(sections):
        combined_text = "\n".join(p for p in section["pages"] if p)
        rows = [(line,) for line in combined_text.splitlines() if line.strip()]
        name = section["marker"] or f"{path.stem}_section{idx + 1}"
        components.append(
            DocumentComponent(
                source_file=str(path),
                component_name=name,
                rows=rows,
                text=combined_text,
            )
        )

    return components
