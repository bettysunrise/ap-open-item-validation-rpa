"""
Extract text from an RTF attachment.

Confirmed real finding (2026-09-16): every real attachment seen with a
".doc" extension in this SAP system is actually plain RTF (starts with
the literal bytes "{\\rtf1"), NOT the legacy OLE-based binary .doc format
- so this only needs a plain RTF-to-text converter (striprtf), not Word
automation. If a genuine OLE-based .doc ever shows up, file_extractor.py
raises a distinct "not yet supported" error for it rather than routing it
here, since this parser cannot read that format.

RTF encodes non-ASCII characters (confirmed real samples contain
Vietnamese and Korean text) as \\uNNNN escapes inside an otherwise
ASCII-ish control-word stream, so the raw bytes are read with a
permissive single-byte codec (errors replaced, never raising) before
striprtf resolves the real Unicode content.
"""
from __future__ import annotations

from pathlib import Path

from striprtf.striprtf import rtf_to_text

from .excel_extractor import DocumentComponent


def extract_rtf_components(path: str | Path) -> list[DocumentComponent]:
    path = Path(path)
    raw_bytes = path.read_bytes()
    raw_text = raw_bytes.decode("cp1252", errors="replace")
    text = rtf_to_text(raw_text)

    rows = [(line,) for line in text.splitlines() if line.strip()]
    return [
        DocumentComponent(
            source_file=str(path),
            component_name=path.stem,
            rows=rows,
            text=text,
        )
    ]
