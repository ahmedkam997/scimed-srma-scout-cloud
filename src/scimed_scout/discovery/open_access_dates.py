"""Conservative review-search-date extraction from open-access Europe PMC full text.

This optional source-backed audit never treats an article's publication date as
its search date and never claims that unscreened studies are eligible.
"""
from __future__ import annotations

import re
import json
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
    rf"(?:\d{{1,2}}\s+)?(?:{MONTH})(?:\s+\d{{1,2}},)?\s+\d{{4}}|"
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
SEARCH_LAST = re.compile(rf"\b(?:last (?:literature |database )?search(?: was)?(?: conducted| performed| updated)?|(?:databases? (?:were )?)?last searched)\s+(?:on\s+|in\s+)?(?P<date>{DATE})\b",re.I)
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
    from .review_opportunity import date_bounds
    for pattern in (SEARCH_CUTOFF, SEARCH_LAST, SEARCH_CUTOFF_REVERSE):
        for match in pattern.finditer(normalized):
            raw = match.group("date").strip()
            raw = re.sub(r"^([A-Za-z]+) (\d{1,2}), (\d{4})$",r"\2 \1 \3",raw)
            # Validate exact dates and never guess ambiguous slash notation.
            bounds=date_bounds(raw)
            year = _search_year(raw)
            if year is None or bounds is None:
                continue
            quote = normalized[max(0, match.start() - 45):min(len(normalized), match.end() + 40)]
            # Keep original literal date for auditable evidence; ordering uses bounds.
            found.append((bounds[1], match.end(), match.group("date").strip(), quote.strip(),year))
    if not found:
        return None
    latest = max(found, key=lambda row: (row[0], row[1]))
    return {
        "date": latest[2],
        "year": latest[4],
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
        if not pmcid:return None
        from .competitor_records import identifiers
        ids=identifiers(review)
        if any(len(v)>1 for v in ids.values()):return None
        pmid=next(iter(ids["pmid"]),None)
        doi=next(iter(ids["doi"]),None)
        expected=pmcid.removeprefix("PMC")
        urls=[("EUROPE_PMC_OPEN_ACCESS_FULL_TEXT_METHODS",f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML"),
              ("NCBI_BIOC_OPEN_ACCESS_FULL_TEXT_METHODS",f"https://www.ncbi.nlm.nih.gov/research/bionlp/RESTful/pmcoa.cgi/BioC_json/{pmcid}/unicode")]
        for source,url in urls:
            try:
                raw=self.fetcher(url)
                if not isinstance(raw,bytes) or len(raw)>1_500_000:continue
                if source.startswith("EUROPE"):
                    if b"<!ENTITY" in raw.upper() or re.search(br"<!DOCTYPE[^>]*\[",raw,re.I):continue
                    root=ET.fromstring(raw)
                    if root.tag!="article":continue
                    front=root.find("./front/article-meta")
                    if front is None:continue
                    observed={e.get("pub-id-type"):str(e.text or "").strip() for e in front.findall("article-id")}
                    op=observed.get("pmid");oc=(observed.get("pmc") or observed.get("pmcid") or "").upper().removeprefix("PMC")
                    od=str(observed.get("doi") or "").casefold()
                    if (pmid and op and op!=pmid) or (oc and oc!=expected) or (doi and od and od!=doi):continue
                    if not (oc==expected or (pmid and op==pmid) or (doi and od==doi)):continue
                    passages=[]
                    for sec in root.findall("./body//sec"):
                        heading=" ".join(sec.find("title").itertext()) if sec.find("title") is not None else ""
                        if re.search(r"\b(?:methods?|search strategy|literature search|information sources|study selection|search methods)\b",heading,re.I):
                            passages.extend(" ".join(p.itertext()) for p in sec.findall("./p"))
                            for sub in sec.findall("./sec"):
                                label=" ".join(sub.find("title").itertext()) if sub.find("title") is not None else ""
                                if not re.search(r"\b(?:results?|discussion|conclusion|background)\b",label,re.I):
                                    passages.extend(" ".join(p.itertext()) for p in sub.findall("./p"))
                else:
                    data=json.loads(raw)
                    collections=data if isinstance(data,list) else [data]
                    docs=[d for c in collections if isinstance(c,dict) for d in c.get("documents",[]) if isinstance(d,dict)]
                    if len(docs)!=1:continue
                    doc=docs[0];passages=[];seen_pmid=set();seen_pmc=set()
                    for p in doc.get("passages",[]):
                        info=p.get("infons") or {}
                        for k in ("article-id_pmid","pmid"):
                            if info.get(k):seen_pmid.add(str(info[k]))
                        for k in ("article-id_pmc","article-id_pmcid","pmcid"):
                            if info.get(k):seen_pmc.add(str(info[k]).upper().removeprefix("PMC"))
                        if str(info.get("section_type") or "").upper() in ("METHODS","METHOD","MATERIALS AND METHODS"):
                            passages.append(str(p.get("text") or ""))
                    if (pmid and seen_pmid and seen_pmid!={pmid}) or (seen_pmc and seen_pmc!={expected}):continue
                    if str(doc.get("id") or "").upper().removeprefix("PMC")!=expected and seen_pmc!={expected}:continue
                candidates=[e for passage in passages if (e:=extract_search_date(passage))]
                from .review_opportunity import date_bounds
                def date_end(e):
                    raw=re.sub(r"^([A-Za-z]+) (\d{1,2}), (\d{4})$",r"\2 \1 \3",e["date"])
                    return date_bounds(raw)[1]
                if not candidates:continue
                evidence=max(candidates,key=date_end)
                publication_year=(review.get("payload") or {}).get("year")
                if publication_year and str(publication_year).isdigit() and evidence["year"]>int(publication_year):continue
                return {**evidence,"source_url":url,"source_type":source,"full_text_eligibility_verified":False}
            except (OSError,ValueError,TypeError,AttributeError,KeyError,ET.ParseError,TimeoutError):continue
        return None
