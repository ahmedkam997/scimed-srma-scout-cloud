from __future__ import annotations

import re
from dataclasses import dataclass

from scimed_scout.storage import CandidateRecord


@dataclass(frozen=True, slots=True)
class SearchPlan:
    primary_queries: tuple[str, ...]
    review_queries: tuple[str, ...]
    registry_queries: tuple[str, ...]
    pipeline_queries: tuple[str, ...]


def build_search_plan(candidate: CandidateRecord, *, max_queries: int = 4) -> SearchPlan:
    """Build concise multi-angle discovery searches from PICO concepts.

    A complete clinical question is often too long for keyword retrieval.
    Keep a small, reproducible mix of AI-proposed keywords and PICO pairs.
    These exploratory queries do not constitute a validated systematic search.
    """
    max_queries = max(1, min(8, int(max_queries)))
    subject = _compact(candidate.population, 56)
    concept = _compact(candidate.intervention_exposure_index_test, 66)
    comparator = _compact(candidate.comparator_reference, 48)
    outcome = _compact(" ".join(candidate.outcomes[:1]), 48)
    keywords = [_compact(term, 105) for term in candidate.search_terms if str(term).strip()]
    title = _compact(_strip_review_words(candidate.title), 115)
    question = _compact(_strip_review_words(candidate.review_question), 115)

    broad = _dedupe([
        _join(concept, subject),
        _join(concept, outcome),
        _join(concept, comparator),
        *keywords[:3],
        title,
        question,
    ])
    if not broad:
        broad = [candidate.title.strip()[:115]]

    primary = _dedupe([
        *keywords[:2],
        _join(concept, subject),
        _join(concept, comparator),
        _join(concept, outcome),
        title,
        question,
    ])[:max_queries]

    review = _dedupe([
        _join(broad[0], "systematic review"),
        _join(broad[1] if len(broad) > 1 else broad[0], "meta-analysis"),
        *[_join(term, "systematic review") for term in keywords[:1]],
        _join(title, "systematic review"),
        _join(concept, "meta-analysis"),
    ])[:max_queries]

    # Registration registries need multi-concept *focused* queries. A
    # stand-alone cue such as "LDL cholesterol" or "vitamin D3" retrieves
    # hundreds of protocols and exhausts free pagination without assessing
    # the proposed PICO. Keep the intervention anchor on every search.
    # Do not equate these exploratory queries with an exhaustive search.
    registry_anchor = _registry_concept(concept)
    registry = _dedupe([
        _compact(_join(registry_anchor, _registry_concept(subject)), 105),
        _compact(_join(registry_anchor, _registry_concept(outcome)), 105),
        _compact(_join(registry_anchor, _registry_concept(comparator)), 105),
        _compact(_join(registry_anchor, _registry_concept(title)), 105),
    ])[:max_queries] or primary

    pipeline = _dedupe([
        _compact(_join(registry_anchor, _registry_concept(subject)), 105),
        _compact(_join(registry_anchor, _registry_concept(comparator)), 105),
        _compact(_join(registry_anchor, _registry_concept(outcome)), 105),
        _compact(_join(registry_anchor, _registry_concept(title)), 105),
    ])[:max_queries] or primary

    return SearchPlan(
        tuple(primary),
        tuple(review),
        tuple(registry),
        tuple(pipeline),
    )


def _compact(value: str, limit: int) -> str:
    cleaned = " ".join(str(value or "").split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[:limit].rsplit(" ", 1)[0] or cleaned[:limit]


def _strip_review_words(value: str) -> str:
    return re.sub(
        r"\b(?:systematic review|meta-analysis|meta analysis|systematic reviews)\b",
        "", str(value or ""), flags=re.IGNORECASE,
    ).strip(" ,:-")


def _join(*parts: str) -> str:
    return " ".join(part.strip() for part in parts if part and part.strip())


def _dedupe(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = " ".join((value or "").split()).strip()
        key = normalized.casefold()
        if normalized and key not in seen:
            seen.add(key)
            out.append(normalized)
    return out


def _registry_concept(value: str) -> str:
    """Normalize punctuation and remove long numeric dose parentheticals.

    PICO scope remains visible in the original query and proposal fields.
    Exact dosing details still belong in manual protocol verification.
    """
    text = re.sub(r"\\([^)]*\\d[^)]*\\)", " ", str(value or ""))
    text = text.replace("‑", " ").replace("–", " ").replace("—", " ")
    text = re.sub(r"[^\w\s-]", " ", text, flags=re.UNICODE)
    return " ".join(text.split()[:8])
