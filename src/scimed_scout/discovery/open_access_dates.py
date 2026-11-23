"""Conservative review-search-date extraction from open-access Europe PMC full text.

This optional source-backed audit never treats an article's publication date as
its search date and never claims that unscreened studies are eligible.
"""
from __future__ import annotations

import re
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Callable


MONTH = (
    r"January|February|March|April|May|June|July|August|"
    r"September|October|November|December"
)
DATE = (
    rf"(?:\d{{4}}-\d{{2}}(?:-\d{{2}})?|"
    rf"(?:\d{{1,2}}\s+)?(?:{MONTH})\s+\d{{4}}|"
    rf"\d{{1,2}}[/-]\d{{1,2}}[/-]\d{{4}})"
)
SEARCH_CUTOFF = re.compile(
    rf"\b(?:search(?:ed|es|ing)?|search strategy|literature search|"
    rf"database searches|electronic searches)\b"
    rf"[^.;!?\n]{{0,145}}?"
    rf"\b(?:through|until|up to|to|before|ending on|last searched on)\s+"
    rf"(?P<date>{DATE})\b",
    flags=re.IGNORECASE,
)
SEARCH_CUTOFF_REVERSE = re.compile(
    rf"\b(?:through|until|up to|to)\s+(?P<date>{DATE})\b"
    rf"[^.;!?\n]{{0,60}}?\b(?:searched|searches|literature search)\b",
    flags=re.IGNORECASE,
)


def _search_year(date: str) -> int | None:
    years = re.findall(r"(?:19|20)\d{2}", date)
    if not years:
        return None
    value = int(years[-1])
    return value if 1900 <= value <= datetime.now(timezone.utc).year else None


def extract_search_date(text: str) -> dict | None:
    """Retain the exact source passage instead of inferring an unknown date."""
    normalized = re.sub(r"\s+", " ", str(text or ""))[:140000]
    found = []
    for pattern in (SEARCH_CUTOFF, SEARCH_CUTOFF_REVERSE):
        for match in pattern.finditer(normalized):
            raw = match.group("date").strip()
            year = _search_year(raw)
            if year is None:
                continue
            quote = normalized[max(0, match.start() - 45):min(len(normalized), match.end() + 40)]
            found.append((year, match.end(), raw, quote.strip()))
    if not found:
        return None
    latest = max(found, key=lambda row: (row[0], row[1]))
    return {
        "date": latest[2],
        "year": latest[0],
        "quote": latest[3][:230],
    }


def _pmcid(record: dict) -> str | None:
    payload = record.get("payload") or {}
    meta = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    options = [meta.get("pmcid"), meta.get("pmcId"), record.get("source_record_id")]
    for row in (meta.get("articleids") or meta.get("articleIds") or []):
        if isinstance(row, dict) and str(row.get("idtype") or row.get("idType") or "").casefold() in ("pmc", "pmcid"):
            options.append(row.get("value") or row.get("id"))
    for raw in options:
        if raw and (match := re.fullmatch(r"PMC\d{4,12}", str(raw).strip(), flags=re.IGNORECASE)):
            return match.group().upper()
    return None


def _fetch_xml(url: str) -> bytes:
    request = urllib.request.Request(url, headers={
        "User-Agent": "SciMed-Review-Scout/1.0 (open-access review metadata)",
        "Accept": "application/xml",
    })
    with urllib.request.urlopen(request, timeout=10) as response:
        return response.read(1_500_001)


class OpenAccessSearchDateResolver:
    def __init__(self, fetcher: Callable[[str], bytes] | None = None):
        self.fetcher = fetcher or _fetch_xml

    def resolve(self, review: dict) -> dict | None:
        pmcid = _pmcid(review)
        if not pmcid:
            return None
        url = f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML"
        try:
            raw = self.fetcher(url)
            if not isinstance(raw, bytes) or len(raw) > 1_500_000:
                return None
            # JATS XML often declares a harmless external DTD. ElementTree
            # does not fetch that DTD. Reject entity declarations, which
            # could expand attacker-controlled text, but keep ordinary DTD
            # declarations so genuine open-access Methods remain readable.
            if b"<!ENTITY" in raw[:65536] or b"<!DOCTYPE" in raw[:65536] and b"[" in raw[:1024].split(b">", 1)[0]:
                return None
            root = ET.fromstring(raw)
        except (OSError, ValueError, ET.ParseError, TimeoutError):
            return None

        sections = []
        for section in root.findall(".//sec"):
            title = " ".join(section.find("title").itertext()) if section.find("title") is not None else ""
            if re.search(r"(?:method|search|literature|identification|selection)", title, re.IGNORECASE):
                sections.append(" ".join(section.itertext())[:12000])
        if not sections:
            return None
        evidence = extract_search_date(" ".join(sections))
        if not evidence:
            return None
        publication_year = (review.get("payload") or {}).get("year")
        if publication_year and str(publication_year).isdigit():
            if evidence["year"] > int(publication_year) + 1:
                return None
        return {
            **evidence,
            "source_url": url,
            "source_type": "EUROPE_PMC_OPEN_ACCESS_FULL_TEXT_METHODS",
            "full_text_eligibility_verified": False,
        }
