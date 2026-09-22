"""
Generic label-proximity extraction helpers shared by the document parsers.

The real sample we validated against ("INVOICE" / "SHIPPING PACKING LIST"
sheets, 2026-09-15) follows the widely-used UN Layout Key style trade
document template (numbered boxes: "1. Seller", "2. Buyer", "6. Carrier",
"7. Sailing on or about", ...), where a label sits in one cell and its
value sits 1-3 rows below, usually in the same column (occasionally
shifted by a column or two due to merged cells in the source template).
Since this layout is a common industry template (not this one vendor's
invention), a label-proximity search generalizes better than fixed
coordinates - but it is still a heuristic. Fields it cannot confidently
locate must be treated as unknown (-> YELLOW downstream), never guessed.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, Optional

NUMBERED_BOX_RE = re.compile(r"^\d+\.$")


def cell_text(v: Any) -> str:
    return "" if v is None else str(v).strip()


def find_label_cell(rows: list[tuple[Any, ...]], label_keywords: list[str]) -> Optional[tuple[int, int]]:
    """Return (row, col) of the first cell whose text contains any of the
    given (lowercase) keywords.

    Confirmed real bug: a Notify Party box's real VALUE was the literal
    text "SAME AS CONSIGNEE" (a common cross-reference shorthand on these
    B/L-style templates), which itself contains the word "consignee" - so
    a keyword search for "consignee" wrongly matched this value cell
    instead of the real Consignee/Buyer box elsewhere in the document,
    and (since a hit was found at all) never fell through to try the
    Buyer-keyword search. A cell whose own text starts with "same as" is
    always this kind of cross-reference, never a real label box - skip it.
    """
    for r, row in enumerate(rows):
        for c, cell in enumerate(row):
            text = cell_text(cell).lower()
            if not text or text.startswith("same as"):
                continue
            for kw in label_keywords:
                if kw in text:
                    return r, c
    return None


_NUMBERED_BOX_LABEL_RE = re.compile(r"\b\d{1,2}\s*\.\s*[A-Z]")

# A short capitalized phrase immediately followed by ':' or ';' - the
# near-universal way commercial-document field labels are formatted
# ("Bill To;", "Contract No: EAST260811-001", "Invoice No:", "Date:").
# Confirmed real bug: a PDF's text layer listed a box's label line, then
# (in reading order, not visual order) an ADJACENT box's "Contract No:
# EAST260811-001" / "Bill To;" line before the real value - neither
# started with a digit nor was short-lowercase, so they weren't caught by
# the checks below. A real company name/value never has this shape (a
# comma or period breaks the character class before any ':'/';' can be
# reached), so this is safe to reject generically.
_LABEL_COLON_RE = re.compile(r"^[A-Za-z][A-Za-z .&/]{0,28}[:;]")

# This business's own invoice-number convention: "ARY-<PARTNER> - <date
# digits>" (e.g. "ARY-NORTHSTAR - 260829", "ARY-BLUEOCEAN - 260911"). Confirmed
# real bug: in some PDFs this reference-number line physically appears
# BEFORE the real Shipper/Exporter company-name line (reversed from the
# label's own box order), so the neighbor-row search accepted it as the
# value instead of skipping to the next line. A trailing date (if still
# attached) is stripped first so the match isn't defeated by it.
_INVOICE_REF_ONLY_RE = re.compile(r"^[A-Z]{2,6}-[A-Za-z]+\s*-\s*\d{4,8}$")

# A vessel/voyage number ("V.246S", "V.0407N") - confirmed real case: once
# "SHIP ON OR ABOUT" (a box header, see below) is correctly rejected, the
# very next line was "UNI-ACCPRD V.0407N 09-Aug-26" - the Vessel column's
# own value bleeding in from a still-different column on the same merged
# row, not the Shipper's name either. No real company name contains a
# "V.<digits>" voyage-code token.
_VOYAGE_CODE_RE = re.compile(r"\bV\.\s*\d+[A-Z]?\b")

# Known UN Layout Key box-header phrases that keep bleeding into value
# fields when OCR/PDF text extraction merges several column headers onto
# one physical line (confirmed real, recurring case: "Vessel Shipper SHIP
# ON OR ABOUT" - matching "shipper" leaves "SHIP ON OR ABOUT", which is
# actually the NEXT column's header, box "7. Sailing on or about" written
# without numbering). None of the earlier generic checks (numbered-box,
# label-colon, invoice-ref) catch a short all-caps phrase with no digits
# or punctuation, so these specific recurring phrases are recognized by
# exact text. Add to this list as new real cases turn up - do not widen
# it into a fuzzy/partial match.
_KNOWN_BOX_HEADER_PHRASES = {
    "ship on or about",
    "sailing on or about",
    "port of discharge",
    "place of delivery",
    "port of loading",
    "final destination",
    "notify party",
    "pre-carriage",
    "description of goods",
}


def _looks_like_leftover_label_text(remainder: str) -> bool:
    """Reject a remainder that's just more label wording rather than a
    real value.

    Two confirmed real cases:
    1. Label text 'Invoice No. and date' matched keyword 'invoice no',
       leaving remainder '. and date' - a short, all-lowercase phrase
       with no digits, clearly not an actual invoice number/company
       name/date value.
    2. OCR of a table joined several column headers onto one physical
       line: '6. Carrier 7.Sailing on or about BRAND: ZIBEN' - matching
       'carrier' left remainder '7.Sailing on or about BRAND: ZIBEN',
       which DOES have digits/uppercase (so case 1's check misses it) but
       is unmistakably another numbered box label bleeding through, not
       the carrier's actual value ('By Truck', found on the next line).
       These UN-Layout-Key style templates consistently number their
       boxes ('1.', '2.', ... '12.') - a remainder starting with that
       pattern is almost never a real value.
    """
    cleaned = remainder.strip(" .:,-")
    if not cleaned:
        return True
    if len(cleaned) <= 20 and cleaned == cleaned.lower() and not any(ch.isdigit() for ch in cleaned):
        return True
    if _NUMBERED_BOX_LABEL_RE.match(cleaned):
        return True
    if _LABEL_COLON_RE.match(cleaned):
        return True
    without_trailing_date = _TRAILING_DATE_RE.sub("", cleaned).strip()
    if _INVOICE_REF_ONLY_RE.match(without_trailing_date):
        return True
    cleaned_lower = cleaned.lower()
    if any(phrase in cleaned_lower for phrase in _KNOWN_BOX_HEADER_PHRASES):
        # Substring (not exact-equality) match: several of these headers
        # routinely land concatenated on ONE merged line (confirmed real
        # case: "Port of Discharge Place of Delivery E.TA. YANGON" is
        # three headers - only checking for a WHOLE-line exact match
        # would miss lines like this that combine more than one).
        return True
    if _VOYAGE_CODE_RE.search(cleaned):
        return True
    return False


def extract_inline_value(cell_value: Any, label_keywords: list[str]) -> Optional[str]:
    """If a single cell holds both the label and the value inline (real
    example: 'BUYER :NORDIC APPAREL' in one cell, no separate value
    cell), split on the matched keyword or a following ':' and return the
    remainder. Returns None if there's no plausible remainder text (empty,
    leftover label wording - see _looks_like_leftover_label_text, or the
    remainder is itself just another word from the same label_keywords
    set - see below)."""
    text = cell_text(cell_value)
    if not text:
        return None
    lower = text.lower()
    for kw in label_keywords:
        idx = lower.find(kw)
        if idx == -1:
            continue
        remainder = text[idx + len(kw):]
        remainder = remainder.lstrip(" :./\t-")
        if not remainder.strip():
            continue
        if _looks_like_leftover_label_text(remainder):
            continue
        # Real templates often combine near-synonym labels in one header
        # (confirmed real case: "1)Shipper/Exporter" as a SINGLE compound
        # label, not "label: value"). Matching "shipper" first left
        # "/Exporter" as the remainder, which then looked like a
        # plausible short value and was wrongly returned as if it were
        # the actual company name. Reject a remainder that is itself
        # (after stripping leading punctuation) just another keyword from
        # the SAME synonym list.
        remainder_key = remainder.strip().lower().lstrip("/")
        if any(remainder_key == other or remainder_key.startswith(other + " ") for other in label_keywords):
            continue
        return remainder.strip()
    return None


def find_value_near(
    rows: list[tuple[Any, ...]],
    r: int,
    c: int,
    max_row_offset: int = 3,
    col_window: int = 2,
    label_keywords: Optional[list[str]] = None,
) -> Optional[str]:
    """Search below (and slightly around) a label cell for the first
    plausible value: non-empty text that isn't itself a numbered-box
    label like '8.'.

    If `label_keywords` is given, first checks whether the label cell
    itself already contains the value inline (e.g. 'BUYER :NORDIC
    APPAREL' in one cell) before searching neighboring cells - confirmed
    real case where a template mixes both styles across sheets.
    """
    if label_keywords is not None:
        inline = extract_inline_value(rows[r][c], label_keywords)
        if inline:
            return inline

    # Some Excel templates put the value in the cell(s) immediately beside
    # the label on the SAME row (confirmed real case: row = (None,
    # "MESSRS", "ARIA CO., LTD.", ...) - label at col 1, value at col 2),
    # not below it. Check same-row neighbors before falling through to
    # the below-row search.
    same_row = rows[r]
    same_row_candidates = [c + off for off in range(1, col_window + 1)] + [c - off for off in range(1, col_window + 1)]
    for cc in same_row_candidates:
        if 0 <= cc < len(same_row):
            raw = same_row[cc]
            if isinstance(raw, (date, datetime)):
                continue
            text = cell_text(raw)
            if text and not NUMBERED_BOX_RE.match(text) and not _looks_like_leftover_label_text(text):
                return text

    n_rows = len(rows)
    for dr in range(1, max_row_offset + 1):
        rr = r + dr
        if rr >= n_rows:
            break
        row = rows[rr]
        candidates = [c] + [c + off for off in range(1, col_window + 1)] + [c - off for off in range(1, col_window + 1)]
        for cc in candidates:
            if 0 <= cc < len(row):
                raw = row[cc]
                if isinstance(raw, (date, datetime)):
                    # A date/datetime cell almost never IS the free-text
                    # value for a Seller/Buyer/Carrier/Invoice-No field -
                    # it usually belongs to a neighboring date label that
                    # happens to share the row. Skip it so text lookups
                    # don't silently grab the wrong field's value
                    # (confirmed live: this previously made Carrier_Info
                    # return the Sailing Date's timestamp instead of the
                    # actual carrier text).
                    continue
                text = cell_text(raw)
                # Same leftover-label-text guard used by extract_inline_value
                # (same cell) must also apply here (neighboring cell/line) -
                # confirmed real bug: candidates like "8. No & date of
                # invoice" or "4. Port of Loading  5. Final destination"
                # (another box's label bleeding in, e.g. from OCR/adjacent
                # column layout) were being accepted as if they were the
                # real value because NUMBERED_BOX_RE only rejects a bare
                # "8." with nothing else attached.
                if text and not NUMBERED_BOX_RE.match(text) and not _looks_like_leftover_label_text(text):
                    return text
    return None


def find_date_near(
    rows: list[tuple[Any, ...]],
    r: int,
    c: int,
    max_row_offset: int = 3,
    col_window: int = 2,
) -> Optional[date]:
    """Like find_value_near, but only accepts real date/datetime cell
    values (openpyxl already parses date-formatted cells) - never parses
    an arbitrary string as a date to avoid guessing a wrong format."""
    n_rows = len(rows)
    for dr in range(1, max_row_offset + 1):
        rr = r + dr
        if rr >= n_rows:
            break
        row = rows[rr]
        for cc in range(max(0, c - col_window), min(len(row), c + col_window + 1)):
            v = row[cc]
            if isinstance(v, datetime):
                return v.date()
            if isinstance(v, date):
                return v
    return None


_TEXT_DATE_PATTERNS = [
    r"\d{4}[-/.]\d{1,2}[-/.]\d{1,2}",  # 2025-03-20 / 2025.03.20
    r"\d{1,2}[-/][A-Za-z]{3,9}[-/]\d{2,4}",  # 25-April-2025
    r"\d{1,2}[-/]\d{1,2}[-/]\d{2,4}",  # 25/03/2025
]
_TEXT_DATE_RE = re.compile("(" + "|".join(_TEXT_DATE_PATTERNS) + ")")
_TEXT_DATE_FORMATS = ["%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%d-%B-%Y", "%d-%b-%Y", "%d/%m/%Y", "%d-%m-%Y"]


def _parse_date_token(token: str) -> Optional[date]:
    for fmt in _TEXT_DATE_FORMATS:
        try:
            return datetime.strptime(token, fmt).date()
        except ValueError:
            continue
    return None


def find_date_in_text_near(
    rows: list[tuple[Any, ...]],
    r: int,
    c: int,
    max_row_offset: int = 3,
    label_keywords: Optional[list[str]] = None,
) -> Optional[date]:
    """Like find_date_near, but for PDF/OCR text rows where a date is
    never a real date/datetime cell - it's plain text, often inline with
    its own label on one line (confirmed real case: 'SHIPMENT DATE :
    2025-03-20' as a single OCR'd line). Scans the label's own line first
    (if label_keywords given), then the next few lines, for a recognizable
    date pattern - never guesses a format not in _TEXT_DATE_FORMATS."""
    n_rows = len(rows)
    search_rows = [r] if label_keywords is not None else []
    search_rows += [r + dr for dr in range(1, max_row_offset + 1) if r + dr < n_rows]

    for rr in search_rows:
        for cell in rows[rr]:
            text = cell_text(cell)
            match = _TEXT_DATE_RE.search(text)
            if match:
                parsed = _parse_date_token(match.group(1))
                if parsed:
                    return parsed
    return None


_TRAILING_DATE_RE = re.compile(
    r"\s+(\d{1,2}[-/][A-Za-z]{3,9}[-/]\d{2,4}|\d{1,2}[-/]\d{1,2}[-/]\d{2,4})\s*$"
)


def _strip_trailing_date(value: Optional[str]) -> Optional[str]:
    """Two side-by-side columns can land on the same OCR text line (a
    company name column next to an invoice-date column) - confirmed real
    case: 'GLOBAL APPAREL CO.,LTD. 25-April-2025' extracted as one value when
    it should just be the company name. Strip a trailing date-looking
    suffix rather than reject the whole value, since the leading part is
    usually still correct."""
    if not value:
        return value
    return _TRAILING_DATE_RE.sub("", value).strip() or None


# A real invoice/reference number (e.g. "EO260515-01AIR") - letters then
# digits then a dash-joined alphanumeric suffix, no spaces. Real company
# names never end this way (they end in "LTD"/"CO"/"LIMITED"/etc, not a
# bare code), so this is safe to strip as a same-line neighbor column
# rather than part of the value itself.
_TRAILING_REF_CODE_RE = re.compile(r"\s+[A-Z]{1,5}\d{4,}-[0-9A-Z]+\s*$")


def _strip_trailing_reference_code(value: Optional[str]) -> Optional[str]:
    """Confirmed real case: 'ARIA VINA CO., LTD ARV260515-01AIR 15-May-26' -
    the Shipper/Exporter column landed on the same OCR line as BOTH the
    neighboring 'No & date of invoice' column's reference number AND its
    date (the box layout has them side by side). _strip_trailing_date
    handles the date suffix; this handles the reference-number suffix
    left over after that, so the real company name doesn't come back
    polluted with an unrelated invoice number and wrongly fail the vendor
    name comparison."""
    if not value:
        return value
    return _TRAILING_REF_CODE_RE.sub("", value).strip() or None


# A neighboring box's "<Label>: value" fragment embedded later in the same
# string (same shape as _LABEL_COLON_RE, but searched anywhere rather than
# anchored to the start, since here it's a SUFFIX polluting an otherwise
# real value rather than the whole candidate).
_EMBEDDED_LABEL_COLON_RE = re.compile(r"\s+[A-Za-z][A-Za-z .&/]{0,28}[:;]")


def _strip_trailing_labeled_field(value: Optional[str]) -> Optional[str]:
    """Confirmed real case: a PDF's text layer fused a Shipper box's real
    value with the adjacent 'Invoice No:' box's label+value on the same
    line - 'GREATWALL FOREIGN TRADE(GROUP)GLOBAL TRADING Invoice No:
    2026TE-5288'. The parenthesis in the real company name defeats the
    start-anchored _LABEL_COLON_RE check, so this instead finds the
    embedded label pattern WHEREVER it occurs and truncates the value
    there, keeping only the (usually correct) leading part."""
    if not value:
        return value
    match = _EMBEDDED_LABEL_COLON_RE.search(value)
    if match:
        return value[: match.start()].strip() or None
    return value


_DUPLICATE_GAP_RE = re.compile(r"\s{2,}")


def _collapse_duplicate_value(value: Optional[str]) -> Optional[str]:
    """Two side-by-side boxes with the SAME content (confirmed real case:
    a 'Consignee'/'Bill To' pair both listing the identical company, PDF
    text layer produced 'ARIA,.CO.LTD       ARIA,.CO.LTD' as one value, joined
    by the wide gap that separated the two columns) - collapse to a single
    copy so comparisons work normally instead of failing because of the
    literal duplication."""
    if not value:
        return value
    for gap_match in _DUPLICATE_GAP_RE.finditer(value):
        first, second = value[: gap_match.start()].strip(), value[gap_match.end():].strip()
        if first and first == second:
            return first
    return value


_MAX_PLAUSIBLE_FIELD_LENGTH = 200


def _reject_if_too_long(value: Optional[str]) -> Optional[str]:
    """A real Seller/Buyer/Consignee value is a company name (plus maybe a
    short address), not an entire invoice. Confirmed real bug: a source
    file had an entire invoice pasted into one giant unstructured cell (no
    real row/column separation), so once a label was found inline, the
    'remainder' was hundreds of characters of raw invoice text rather than
    a company name. Better to report nothing (-> YELLOW) than a value this
    obviously wrong."""
    if value and len(value) > _MAX_PLAUSIBLE_FIELD_LENGTH:
        return None
    return value


def extract_seller(rows: list[tuple[Any, ...]]) -> Optional[str]:
    # "Shipper" / "Exporter" / "Supplier" are all used interchangeably
    # with "Seller" across different vendors' invoice templates -
    # confirmed real cases 2026-09-15 (3 different vendors, 3 different
    # words for the identical role).
    keywords = ["seller", "shipper", "exporter", "supplier"]
    hit = find_label_cell(rows, keywords)
    value = find_value_near(rows, *hit, label_keywords=keywords) if hit else None
    value = _strip_trailing_reference_code(_strip_trailing_date(value))
    value = _strip_trailing_labeled_field(value)
    return _reject_if_too_long(value)


def extract_buyer(rows: list[tuple[Any, ...]]) -> Optional[str]:
    # "For Account & Risk of Messrs" is a real UN Layout Key synonym for
    # "Buyer" used on some vendors' templates (confirmed real case) -
    # "messrs" alone is a distinctive enough token to match safely.
    keywords = ["buyer", "messrs"]
    hit = find_label_cell(rows, keywords)
    value = find_value_near(rows, *hit, label_keywords=keywords) if hit else None
    value = _strip_trailing_labeled_field(value)
    return _reject_if_too_long(value)


def extract_consignee(rows: list[tuple[Any, ...]]) -> Optional[str]:
    keywords = ["consignee"]
    hit = find_label_cell(rows, keywords)
    if hit:
        value = _strip_trailing_labeled_field(find_value_near(rows, *hit, label_keywords=keywords))
        value = _collapse_duplicate_value(value)
        return _reject_if_too_long(value)
    # Many of these templates use "Buyer" where a Western B/L would say
    # "Consignee" - fall back to Buyer if no explicit Consignee label exists.
    return extract_buyer(rows)
