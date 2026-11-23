"""Free bibliographic cues for clinically specific review-topic generation.

Seed titles are PubMed *search results*, not eligible independent trials,
synthesis gaps, confirmed publication year, or evidence of novelty.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
import re

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


_NONPRIMARY_SEED_TITLE = re.compile(
    r"\b(?:rationale and design|trial design|study protocol|protocol for|"
    r"expert consensus|consensus statement|clinical practice guideline|"
    r"systematic review|scoping review|meta.analysis|umbrella review|"
    r"editorial|erratum|correction to|commentary)\b",
    flags=re.I,
)


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
        # PubMed sometimes indexes future print-year citations ahead of
        # publication. Do not present a 2027 print-year record as an already
        # published original trial in a 2026 discovery run. Nor should an
        # expert consensus or protocol be treated as direct primary evidence.
        if (
            len(title) < 18 or title.casefold() in seen
            or _NONPRIMARY_SEED_TITLE.search(title)
            or (record.year is not None and record.year > year)
        ):
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



_GAP_SIGNAL = re.compile(
    r"\b(?:future research|further research|further studies|further (?:randomized )?trials|"
    r"additional (?:randomized )?trials|more (?:randomized )?trials|"
    r"more high.quality studies|low certainty|very low certainty|"
    r"evidence (?:is|remains|was) (?:limited|insufficient|uncertain)|"
    r"insufficient evidence|limited evidence|uncertainty remains|"
    r"larger studies|larger trials|research is needed|"
    r"lack of evidence|research gap|evidence gap)\b", re.I,
)


def recent_review_gap_cues(
    specialty: str, question_type: str = "ALL", *,
    client: Any | None = None,
    now: datetime | None = None, max_records: int = 6,
) -> list[dict[str, Any]]:
    """Extract evidence gap *leads* directly from published review abstracts.

    Uses the public Europe PMC core API and its review publication-type
    query. These are not validated gap statements, guaranteed SRMAs, search
    cutoffs, prospective novelty clearance or available independent studies.
    """
    from scimed_scout.sources.europe_pmc import EuropePMCSource
    from scimed_scout.discovery.evidence_classification import classify_review_search_hit

    specialty = str(specialty or "").strip()
    if not specialty or specialty.upper() == "ALL":
        return []
    current_year = (now or datetime.now(timezone.utc)).year
    subject = TERMS.get(specialty.casefold(), '"' + specialty.replace('"', '') + '"')
    subject = re.sub(r"\[(?:Title/Abstract|MeSH Terms)\]", "", subject)
    query = (
        f"{subject} AND PUB_TYPE:review "
        f"AND PUB_YEAR:[{current_year - 5} TO {current_year}]"
    )
    try:
        result = (client or EuropePMCSource()).search(query, limit=32)
    except Exception:
        return []
    if result.status != SourceStatus.SEARCHED_POSITIVE:
        return []
    output: list[dict[str, Any]] = []
    seen = set()
    for record in result.records:
        if len(output) >= max(1, min(10, int(max_records))):
            break
        if classify_review_search_hit(record) != "CONFIRMED_REVIEW_CUE":
            continue
        metadata = record.metadata if isinstance(record.metadata, dict) else {}
        raw = str(metadata.get("abstractText") or metadata.get("abstract") or "")
        plain = re.sub(r"<[^>]*>", " ", raw).replace("\r", " ").replace("\n", " ")
        plain = re.sub(r"\s+", " ", plain).strip()
        sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z])", plain)
        gap = ""
        gap_signal = ""
        for piece in sentences:
            match = _GAP_SIGNAL.search(piece)
            if not match or re.search(
                r"\b(?:no|without|not an?)\s+(?:documented\s+)?(?:evidence|research|knowledge)\s+gap\b",
                piece, flags=re.I,
            ):
                continue
            # In long abstracts, the actual evidence-gap phrase can occur
            # after 330 characters. Center the excerpt on the matched words.
            # Never present a truncated methods/results sentence as a quoted
            # claim of an actual research gap.
            gap_signal = match.group(0)
            if len(piece) <= 330:
                gap = piece
            else:
                left = max(0, match.start() - 80)
                right = min(len(piece), match.end() + 210)
                gap = ("…" if left else "") + piece[left:right] + (
                    "…" if right < len(piece) else ""
                )
            break
        if not gap:
            continue
        key = (record.doi or record.title).casefold()
        if not key or key in seen:
            continue
        seen.add(key)
        output.append({
            "title": str(record.title or "")[:230],
            "year": record.year,
            "source": "Europe PMC",
            "url": record.url or (f"https://doi.org/{record.doi}" if record.doi else ""),
            "doi": record.doi or "",
            "pmid": record.record_id,
            "gap_sentence_from_abstract": gap[:330],
            "matched_gap_phrase": gap_signal,
            "last_literature_search_date": None,
            "fulltext_gap_verified": False,
            "new_independent_eligible_studies_confirmed": None,
            "update_justified": False,
            "role": "PUBLISHED_REVIEW_ABSTRACT_GAP_LEAD_ONLY",
        })
    return output


def review_gap_prompt(gaps: list[dict[str, Any]]) -> str:
    """Feed citations and quoted limitations as data, never as AI instructions."""
    if not gaps:
        return ""
    rows = "\n".join(
        f"- Review citation: {item['title']} ({item.get('year') or 'year unknown'}; "
        f"DOI {item.get('doi') or 'unknown'}; {item.get('url') or 'no URL'}). "
        f"Quoted abstract uncertainty: {item['gap_sentence_from_abstract']}"
        for item in gaps[:6]
    )
    return (
        "Published review abstracts with possible evidence-gap statements "
        "(bibliographic leads only; do NOT assume these reviews are old or "
        "that a meta-analysis is feasible):\n"
        + rows
        + "\nUse these to propose clinically important, precise update questions "
        "ONLY when newer independent studies may exist. An insufficient-studies "
        "gap may instead require NEW PRIMARY RESEARCH, not an SRMA. "
        "Verify original search cutoffs, duplicate reviews, protocols, "
        "eligible studies and evidence availability before declaring novelty."
    )


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
