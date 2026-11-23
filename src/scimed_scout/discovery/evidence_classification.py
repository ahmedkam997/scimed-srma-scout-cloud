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
