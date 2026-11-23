"""Low-cost, source-linked bibliographic preflight for topic PRIORITIZATION.

This does not screen full texts, identify independent trials, test novelty,
or prove that absent title matches mean no eligible evidence exists.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Callable

from scimed_scout.domain import SourceStatus
from scimed_scout.storage import CandidateRecord, SQLiteLedger

_STOP = {
    "supplementation", "supplement", "treatment", "treatments", "therapy",
    "therapies", "intervention", "interventions", "effectiveness", "efficacy",
    "safety", "clinical", "standard", "care", "vs", "versus", "placebo",
    "high", "low", "dose", "doses", "and", "with", "without", "the",
    "use", "using", "added", "alone", "of", "in", "on", "for",
}


def _tokens(value: str) -> list[str]:
    words = re.findall(r"[a-z0-9]{3,}", str(value or "").replace("‑", "-").casefold())
    return list(dict.fromkeys(x for x in words if x not in _STOP))


def _anchor(candidate: CandidateRecord) -> list[str]:
    terms = _tokens(candidate.intervention_exposure_index_test)
    if not terms:
        terms = _tokens(candidate.title)
    return terms[:5]


def _year(value: Any) -> int | None:
    try:
        year = int(value)
        return year if 1900 <= year <= datetime.now(timezone.utc).year else None
    except (TypeError, ValueError):
        return None


def search_query(candidate: CandidateRecord, *, current_year: int | None = None) -> str:
    terms = _anchor(candidate)
    if not terms:
        return ""
    year = current_year or datetime.now(timezone.utc).year
    # Keep a broad intervention anchor for sensitivity. Population/comparator
    # overlap is assessed on retrieved titles, NOT required in the query.
    intervention = " ".join(terms[:3]).replace('"', "")
    return (
        f'"{intervention}"[Title/Abstract] AND '
        f'("{year - 5}/01/01"[Date - Publication] : '
        f'"{year}/12/31"[Date - Publication])'
    )


def evaluate_preflight(candidate: CandidateRecord, result: Any) -> dict[str, Any]:
    anchor = set(_anchor(candidate))
    population = set(_tokens(candidate.population))
    comparator = set(_tokens(candidate.comparator_reference))
    records = list(getattr(result, "records", []) or [])
    matched: list[dict[str, Any]] = []
    for row in records:
        title = str(getattr(row, "title", "") or "").strip()
        terms = set(_tokens(title))
        if not terms or not anchor:
            continue
        intervention_match = len(terms & anchor) / len(anchor)
        if intervention_match < (0.5 if len(anchor) > 1 else 1.0):
            continue
        population_match = round(len(terms & population) / max(1, len(population)), 2)
        comparator_match = round(len(terms & comparator) / max(1, len(comparator)), 2)
        matched.append({
            "title": title[:260],
            "source": "PubMed",
            "year": _year(getattr(row, "year", None)),
            "pmid": str(getattr(row, "record_id", "") or ""),
            "url": str(getattr(row, "url", "") or ""),
            "intervention_title_match": round(intervention_match, 2),
            "population_title_match": population_match,
            "comparator_title_match": comparator_match,
            "fulltext_eligibility": "NOT_CHECKED",
            "trial_family_independence": "NOT_CONFIRMED",
        })
    current_year = datetime.now(timezone.utc).year
    recent = sum(x["year"] is not None and x["year"] >= current_year - 3 for x in matched)
    relevant_population = sum(x["population_title_match"] > 0 for x in matched)
    relevant_comparator = sum(x["comparator_title_match"] > 0 for x in matched)
    # Title signals only. Their only effect is scheduling independent checks.
    priority = min(22, 3 * min(len(matched), 4) + 2 * min(recent, 3)
                   + 2 * min(relevant_population, 2)
                   + min(relevant_comparator, 2))
    status = getattr(getattr(result, "status", None), "value", "NOT_SEARCHED")
    return {
        "status": status,
        "query": str(getattr(result, "query", "") or ""),
        "reported_total_matching_query": getattr(result, "total_count", None),
        "records_sampled": len(records),
        "intervention_title_matches": len(matched),
        "recent_intervention_title_matches": recent,
        "population_title_matches": relevant_population,
        "comparator_title_matches": relevant_comparator,
        "priority_signal": priority,
        "evidence_leads": matched[:6],
        "eligible_independent_studies_confirmed": None,
        "novelty_confirmed": False,
        "interpretation": (
            "BIBLIOGRAPHIC_PRIORITY_ONLY: title terms are not full-text eligibility, "
            "independent trials, or evidence of novelty; zero title matches "
            "cannot exclude available evidence."
        ),
    }


class FocusedEvidencePreflight:
    def __init__(self, source: Any, *, max_candidates: int = 24, per_query: int = 12):
        self.source = source
        self.max_candidates = max(0, min(50, int(max_candidates)))
        self.per_query = max(1, min(20, int(per_query)))

    def annotate(
        self,
        ledger: SQLiteLedger,
        project_id: str,
        *,
        cancellation_check: Callable[[], None] | None = None,
    ) -> dict[str, int]:
        candidates = ledger.list_candidates(project_id)
        checked = 0
        with_signal = 0
        for candidate in candidates[:self.max_candidates]:
            if cancellation_check:
                cancellation_check()
            query = search_query(candidate)
            if not query:
                continue
            try:
                result = self.source.search(query, limit=self.per_query)
                signal = evaluate_preflight(candidate, result)
            except Exception as exc:
                # Connectivity failures are not zero-evidence conclusions.
                signal = {
                    "status": SourceStatus.ACCESS_FAILED.value,
                    "query": query,
                    "priority_signal": 0,
                    "intervention_title_matches": None,
                    "error_type": type(exc).__name__,
                    "novelty_confirmed": False,
                    "eligible_independent_studies_confirmed": None,
                }
            candidate.metadata = {**(candidate.metadata or {}), "evidence_preflight": signal}
            ledger.upsert_candidate(candidate)
            checked += 1
            if signal.get("priority_signal", 0) > 0:
                with_signal += 1
        return {"candidates_checked": checked, "topics_with_title_signals": with_signal}
