"""Conservative bibliographic evidence-type classification.

A query containing 'systematic review' frequently retrieves individual RCTs
and other articles in OpenAlex/Crossref. Do not label every search hit a
published review. Unknown hits are retained separately for manual audit.
"""
from __future__ import annotations

import re
from typing import Any

from scimed_scout.sources.base import SearchRecord


_REVIEW_TITLE = re.compile(
    r"\b(?:systematic\s+review|systematic\s+literature\s+review|"
    r"meta[ -]analysis|umbrella\s+review|scoping\s+review|"
    r"network\s+meta[ -]analysis|living\s+(?:systematic\s+)?review|"
    r"evidence\s+(?:and\s+)?gap\s+map|evidence\s+mapping|"
    r"systematic\s+evidence\s+synthesis|"
    r"rapid\s+review|Cochrane\s+(?:database\s+of\s+)?systematic\s+reviews)\b",
    re.IGNORECASE,
)
_REVIEW_ABSTRACT = re.compile(
    r"\b(?:systematic(?:ally)?\s+(?:searched|reviewed)|"
    r"systematic\s+review|meta[ -]analysis|"
    r"we\s+(?:searched|screened)\s+(?:PubMed|Medline|Embase|Scopus)|"
    r"following\s+PRISMA\s+guidelines|"
    r"pooled\s+(?:estimates|data|effect\s+sizes))\b",
    re.IGNORECASE,
)
_PRIMARY_TITLE = re.compile(
    r"\b(?:randomi[sz]ed|double[ -]blind|placebo[ -]controlled|"
    r"cross[ -]over\s+(?:trial|study)|clinical\s+trial|"
    r"prospective\s+cohort|case[ -]control|case\s+report|"
    r"phase\s+[1-4ivx]+\s+trial)\b",
    re.IGNORECASE,
)
_NON_STUDY = re.compile(r"\b(?:editorial|erratum|correction|commentary|letter\s+to\s+the\s+editor)\b", re.I)


def _types(record: SearchRecord) -> list[str]:
    meta = record.metadata if isinstance(record.metadata, dict) else {}
    values: list[str] = []
    for key in ("publicationTypes", "pubtype", "publication_types", "type", "type_crossref"):
        value = meta.get(key)
        if isinstance(value, list):
            values += [str(v).casefold() for v in value]
        elif isinstance(value, str):
            values.append(value.casefold())
    return values


def classify_review_search_hit(record: SearchRecord) -> str:
    """Return CONFIRMED_REVIEW_CUE / PRIMARY_OR_NONREVIEW / NEEDS_BIBLIOGRAPHIC_CHECK.

    This classification is a citation-level triage, not a full-text review
    quality assessment. Metadata-only 'article' is never a review claim.
    """
    title = str(record.title or "").strip()
    meta = record.metadata if isinstance(record.metadata, dict) else {}
    types = _types(record)
    # Crossref includes peer-review reports whose titles quote the
    # reviewed manuscript (often containing 'systematic review'). They
    # are not independent systematic review publications.
    if re.match(r"^\s*(?:review\s+for|peer[ -]review\s+report|"
                r"reviewer\s+report)\b", title, re.IGNORECASE):
        return "PRIMARY_OR_NONREVIEW"
    if any("systematic review" in t or "meta-analysis" in t for t in types):
        return "CONFIRMED_REVIEW_CUE"
    if _REVIEW_TITLE.search(title):
        return "CONFIRMED_REVIEW_CUE"
    if any("randomized controlled trial" in t or "clinical trial" in t for t in types):
        return "PRIMARY_OR_NONREVIEW"
    if _PRIMARY_TITLE.search(title) or _NON_STUDY.search(title):
        return "PRIMARY_OR_NONREVIEW"
    abstract = str(meta.get("abstract") or "")
    if _REVIEW_ABSTRACT.search(abstract):
        return "CONFIRMED_REVIEW_CUE"
    # A generic PubMed 'Review' pubtype is not an SRMA, but competing
    # narrative reviews deserve manual review and should not be fabricated.
    return "NEEDS_BIBLIOGRAPHIC_CHECK"


def classify_registration_search_hit(record: SearchRecord) -> str:
    """OSF includes preregistrations of primary experiments, not only reviews."""
    if record.source == "PROSPERO":
        return "REVIEW_REGISTRATION_CUE"
    title = str(record.title or "")
    meta = record.metadata if isinstance(record.metadata, dict) else {}
    abstract = str(meta.get("abstract") or "")
    if _REVIEW_TITLE.search(title) or _REVIEW_ABSTRACT.search(abstract):
        return "REVIEW_REGISTRATION_CUE"
    if _PRIMARY_TITLE.search(title) or re.search(
        r"\b(?:recruitment|study\s+participants|experimental\s+design|"
        r"laboratory\s+experiment|participant\s+allocation)\b", abstract, re.I
    ):
        return "PRIMARY_STUDY_PREREGISTRATION"
    return "UNCLASSIFIED_REGISTRATION"


_PICO_INTERVENTION_NOISE = {
    "treatment", "treatments", "therapy", "therapies", "intervention",
    "interventions", "efficacy", "effect", "effects", "safety", "use",
    "using", "administration", "ingestion", "oral", "intravenous",
    "supplementation", "supplement", "supplements", "extract",
    "standardized", "study", "clinical", "dose", "doses", "mg",
    "per", "kg", "before", "after", "during", "compared",
    "versus", "against", "versus", "with", "without", "and",
    "for", "the", "adult", "adults", "patient", "patients",
    "index", "test", "testing", "evaluation", "diagnosis",
    "monitoring", "assay", "agent", "medicine",
}


def _normalize_token(token: str) -> str:
    token = token.casefold()
    return token[:-1] if len(token) >= 6 and token.endswith("s") else token


def review_intervention_citation_signal(candidate: Any, record: SearchRecord) -> str:
    """Conservative metadata-only PICO screen for broad review-search hits.

    No signal = move to manual bibliography tier, NOT scientific exclusion.
    Abstract and title mentions are source-linked signals only, and cannot
    establish clinical review overlap without the actual review methods.
    """
    intervention = str(getattr(candidate, "intervention_exposure_index_test", "") or "")
    intervention_terms = {
        _normalize_token(t)
        for t in re.findall(r"[a-z0-9]+", intervention.casefold())
        if t not in _PICO_INTERVENTION_NOISE and len(t) >= 3
    }
    if not intervention_terms:
        return "INTERVENTION_NOT_SPECIFIC_ENOUGH_TO_TRIAGE"
    metadata = record.metadata if isinstance(record.metadata, dict) else {}
    parts = [
        str(record.title or ""), str(metadata.get("abstract") or ""),
        str(metadata.get("abstractText") or ""),
        str(metadata.get("summary") or ""),
        str(metadata.get("description") or ""),
    ]
    citation = " ".join(parts).casefold()
    citation_terms = {
        _normalize_token(t) for t in re.findall(r"[a-z0-9]+", citation)
        if len(t) >= 3
    }
    if intervention_terms & citation_terms:
        return "INTERVENTION_IN_REVIEW_CITATION"
    return "NO_INTERVENTION_MENTION_IN_REVIEW_CITATION_MANUAL_CHECK"
