"""
OCR a standalone image attachment (a real B/L has been seen saved as a
plain .jpg with no PDF wrapper - confirmed in the full 127-item
production run, ~18 files). Reuses the same Tesseract engine already
wired up for scanned PDF pages in pdf_extractor.py, applied directly to
the image instead of a rendered PDF page.
"""
from __future__ import annotations

from pathlib import Path

from .excel_extractor import DocumentComponent
from .pdf_extractor import OCR_AVAILABLE, OCR_LANGS

try:
    import pytesseract
    from PIL import Image
except ImportError:  # pragma: no cover
    pytesseract = None
    Image = None


def extract_image_components(path: str | Path) -> list[DocumentComponent]:
    path = Path(path)

    if not (OCR_AVAILABLE and pytesseract is not None and Image is not None):
        raise ValueError(f"{path} is an image attachment but OCR (Tesseract) is not available on this machine.")

    try:
        with Image.open(path) as img:
            text = pytesseract.image_to_string(img, lang=OCR_LANGS)
    except Exception:  # noqa: BLE001
        text = ""

    # OCR ran but found no text (blank/unreadable scan) - return an empty
    # component rather than raising, so it flows into evaluate/validate the
    # same as any other genuinely empty document: it correctly stays
    # UNKNOWN/YELLOW-or-RED rather than being silently dropped.
    rows = [(line,) for line in text.splitlines() if line.strip()]
    return [
        DocumentComponent(
            source_file=str(path),
            component_name=path.stem,
            rows=rows,
            text=text,
        )
    ]
