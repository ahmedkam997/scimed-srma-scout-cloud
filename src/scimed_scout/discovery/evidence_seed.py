"""Free bibliographic cues for clinically specific review-topic generation.

Seed titles are PubMed *search results*, not eligible independent trials,
synthesis gaps, confirmed publication year, or evidence of novelty.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from scimed_scout.domain import SourceStatus
from scimed_scout.sources.pubmed import PubMedSource


TERMS = {
    "cardiology": '("heart failure"[Title/Abstract] OR "atrial fibrillation"[Title/Abstract] OR "cardiovascular"[Title/Abstract])',
    "neurology": '("stroke"[Title/Abstract] OR "multiple sclerosis"[Title/Abstract] OR "neurology"[Title/Abstract])',
    "oncology": '("neoplasm"[MeSH Terms] OR "cancer"[Title/Abstract])',
    "orthopedics": '("fracture"[Title/Abstract] OR "arthroplasty"[Title/Abstract] OR "orthopedic"[Title/Abstract])',
    "general surgery": '("surgery"[Title/Abstract] OR "surgical"[Title/Abstract])',
    "nephrology": '("kidney"[Title/Abstract] OR "dialysis"[Title/Abstract])',
    "radiology": '("radiology"[Title/Abstract] OR "medical imaging"[Title/Abstract])',
    "emergency medicine": '("emergency department"[Title/Abstract] OR "emergency care"[Title/Abstract])',
}


def recent_pubmed_cues(
    specialty: str,
    question_type: str = "ALL",
    *,
    client: Any | None = None,
    now: datetime | None = None,
    max_records: int = 10,
) -> list[dict[str, Any]]:
    specialty = str(specialty or "").strip()
    if not specialty or specialty.upper() == "ALL":
        return []

    year = (now or datetime.now(timezone.utc)).year
    subject = TERMS.get(specialty.casefold(), f'"{specialty.replace(chr(34), "")}"[Title/Abstract]')
    topic = str(question_type or "").strip().upper()
    if topic == "DIAGNOSTIC_ACCURACY":
        design_filter = '("diagnosis"[MeSH Subheading] OR "diagnostic accuracy"[Title/Abstract])'
    elif topic in ("ETIOLOGY_RISK", "PREVALENCE_INCIDENCE", "PROGNOSIS"):
        design_filter = '("Cohort Studies"[MeSH Terms] OR "observational"[Title/Abstract])'
    else:
        design_filter = '("Randomized Controlled Trial"[Publication Type] OR "clinical trial"[Title/Abstract])'

    query = (
        f'{subject} AND {design_filter}'
        f' AND ("{year - 2}/01/01"[Date - Publication] : "{year}/12/31"[Date - Publication])'
    )
    try:
        result = (client or PubMedSource()).search(query, limit=min(15, max(1, max_records)))
    except Exception:
        return []
    if result.status != SourceStatus.SEARCHED_POSITIVE:
        return []
    output = []
    seen: set[str] = set()
    for record in result.records:
        title = str(record.title or "").strip()
        if len(title) < 18 or title.casefold() in seen:
            continue
        seen.add(title.casefold())
        output.append({
            "title": title[:220],
            "year": record.year,
            "source": "PubMed",
            "url": record.url,
            "pmid": record.record_id,
            "verified_inclusion": False,
        })
        if len(output) >= max_records:
            break
    return output


def cue_prompt(cues: list[dict[str, Any]]) -> str:
    if not cues:
        return ""
    rows = "\n".join(
        f"- {item['title']} ({item.get('year') or 'year unknown'}; PMID {item.get('pmid') or 'unknown'})"
        for item in cues[:10]
    )
    return (
        "Recent PubMed records (unverified eligibility) for identifying feasible, "
        "specific new clinical questions. These titles do NOT prove novelty, "
        "trial independence, treatment effectiveness, or unaddressed evidence. "
        "Build focused, varied PICO questions from these cues while avoiding generic, "
        "well-synthesized textbook comparisons. Validate later against existing reviews.\n"
        + rows
    )
