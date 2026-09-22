"""
Rule: SAP AP Vendor vs Invoice Vendor/Seller (and, when available, BL/AWB
Shipper) should be the same legal entity.

GREEN: exact match after normalization (case/whitespace/punctuation/
common suffixes like CO.,LTD / LTD / LIMITED / PT).
YELLOW: similar but not confidently the same entity.
RED: clearly different.

Config-driven alias table (config/vendor_aliases.json) lets recurring
known-equivalent name pairs be declared without hardcoding them in code.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Optional

SUFFIX_PATTERNS = [
    r"\bco\.,?\s*ltd\.?\b",
    r"\bcompany\s+limited\b",
    r"\bcompany\s+ltd\.?\b",
    r"\blimited\b",
    r"\bltd\.?\b",
    r"\bpte\.?\b",
    r"\bpt\.?\b",
    r"\binc\.?\b",
    r"\bcorp(oration)?\.?\b",
]

YELLOW_SIMILARITY_THRESHOLD = 0.6


@dataclass
class VendorMatchResult:
    status: str  # GREEN | YELLOW | RED
    reason: str
    normalized_a: str
    normalized_b: str
    similarity: float


def normalize_company_name(name: Optional[str]) -> str:
    """Uppercase, strip punctuation, and remove common legal-entity
    suffixes so trivial formatting differences don't cause a false
    mismatch (e.g. 'PT MEKAR TEKSTIL INDONESIA' vs
    'PT. MEKAR TEKSTIL INDONESIA' both normalize to the same string).
    Returns a human-readable (spaced) form - see comparison_key() for the
    whitespace-insensitive form used for the actual GREEN/equal check."""
    if not name:
        return ""
    s = name.upper()
    s = re.sub(r"[.,()]", " ", s)
    for pat in SUFFIX_PATTERNS:
        s = re.sub(pat, " ", s, flags=re.IGNORECASE)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def comparison_key(name: Optional[str]) -> str:
    """Whitespace-insensitive comparison key. Per project rule, whitespace
    is itself a normalization dimension (alongside punctuation) - this
    catches cases like SAP 'GLC TRADING LIMITED' vs Invoice 'G.L.C TRADING
    LIMITED', where the period-to-space substitution in
    normalize_company_name would otherwise split 'HS' into 'H S' and
    cause a false non-match."""
    return re.sub(r"\s+", "", normalize_company_name(name))


def _load_alias_groups(config_path: str | Path) -> list[set[str]]:
    path = Path(config_path)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [{normalize_company_name(n) for n in group} for group in data.get("groups", [])]


def _same_alias_group(a: str, b: str, groups: list[set[str]]) -> bool:
    return any(a in g and b in g for g in groups)


def compare_vendor(
    name_a: Optional[str],
    name_b: Optional[str],
    alias_config_path: str | Path = "config/vendor_aliases.json",
) -> VendorMatchResult:
    """Compare two company names (e.g. SAP Vendor vs Invoice Seller)."""
    norm_a = normalize_company_name(name_a)
    norm_b = normalize_company_name(name_b)

    if not norm_a or not norm_b:
        return VendorMatchResult("YELLOW", "Vendor/Shipper 명칭 확인 필요 (값 누락)", norm_a, norm_b, 0.0)

    if norm_a == norm_b or comparison_key(name_a) == comparison_key(name_b):
        return VendorMatchResult("GREEN", "", norm_a, norm_b, 1.0)

    if _same_alias_group(norm_a, norm_b, _load_alias_groups(alias_config_path)):
        return VendorMatchResult("GREEN", "", norm_a, norm_b, 1.0)

    similarity = SequenceMatcher(None, norm_a, norm_b).ratio()
    if similarity >= YELLOW_SIMILARITY_THRESHOLD:
        return VendorMatchResult("YELLOW", "Vendor/Shipper 명칭 확인 필요", norm_a, norm_b, similarity)

    return VendorMatchResult("RED", "SAP Vendor와 Invoice/Shipper 불일치", norm_a, norm_b, similarity)
