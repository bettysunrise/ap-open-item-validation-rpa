"""
Rule: the Invoice/B-L/AWB Consignee should be one of the company's own
group entities (subsidiaries/branches).

Entity names are managed via config/eo_entities.json (never hardcoded)
so the list can grow without a code change.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .vendor import normalize_company_name


@dataclass
class ConsigneeMatchResult:
    status: str  # GREEN | YELLOW | RED
    reason: str


def _load_eo_entities(config_path: str | Path) -> set[str]:
    path = Path(config_path)
    if not path.exists():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    return {normalize_company_name(n) for n in data.get("entities", [])}


def check_consignee(consignee: Optional[str], config_path: str | Path = "config/eo_entities.json") -> ConsigneeMatchResult:
    if not consignee or not consignee.strip():
        return ConsigneeMatchResult("YELLOW", "Consignee 확인 필요 (값 누락)")

    entities = _load_eo_entities(config_path)
    if not entities:
        return ConsigneeMatchResult("YELLOW", "그룹사 법인 목록(config/eo_entities.json)이 비어있어 확인 필요")

    normalized = normalize_company_name(consignee)
    if normalized in entities:
        return ConsigneeMatchResult("GREEN", "")

    # OCR'd multi-column source documents can join the Consignee value
    # with an unrelated neighboring field on the same line (confirmed
    # real case: a document's Consignee cell read as "<ABBREV> PRODUCTION
    # OF <COUNTRY>" - the abbreviation is the real consignee value, and
    # "PRODUCTION OF <COUNTRY>" bled in from a "Remarks" column sharing
    # the same OCR line). Accept a match on just the first token so a
    # short known abbreviation isn't wrongly rejected because of trailing
    # noise - still an exact match on that token, never a fuzzy/partial one.
    first_token = normalized.split(" ")[0] if normalized else ""
    if first_token and first_token in entities:
        return ConsigneeMatchResult("GREEN", "")

    return ConsigneeMatchResult(
        "RED",
        f"⚠ Consignee가 등록된 그룹사 법인과 일치하지 않습니다: {consignee} / 그룹사 법인으로 변경 필요",
    )
