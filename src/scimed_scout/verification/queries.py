from __future__ import annotations

from dataclasses import dataclass

from scimed_scout.storage import CandidateRecord


@dataclass(frozen=True, slots=True)
class SearchPlan:
    primary_queries: tuple[str, ...]
    review_queries: tuple[str, ...]
    registry_queries: tuple[str, ...]
    pipeline_queries: tuple[str, ...]


def build_search_plan(candidate: CandidateRecord, *, max_queries: int = 4) -> SearchPlan:
    base = _dedupe([
        candidate.review_question,
        candidate.title,
        *candidate.search_terms,
        _join(candidate.population, candidate.intervention_exposure_index_test),
        _join(candidate.intervention_exposure_index_test, candidate.comparator_reference),
        _join(candidate.population, candidate.intervention_exposure_index_test, candidate.comparator_reference),
    ])[:max_queries]

    if not base:
        base = [candidate.title]

    review = _dedupe([
        f"{query} systematic review meta-analysis" for query in base[:4]
    ] + [
        f"{query} systematic review" for query in base[:3]
    ])[:max_queries]

    registry = tuple(base[:max_queries])
    pipeline = tuple(base[:max_queries])
    return SearchPlan(tuple(base), tuple(review), registry, pipeline)


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
