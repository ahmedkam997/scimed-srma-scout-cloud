"""Low-cost, source-linked bibliographic preflight for topic PRIORITIZATION.

This does not screen full texts, identify independent trials, test novelty,
or prove that absent title matches mean no eligible evidence exists.
"""
from __future__ import annotations

import re
import time
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


_GENERAL_POPULATION_TERMS = {
    "adult", "adults", "patient", "patients", "aged", "age", "years",
    "year", "male", "female", "women", "men", "person", "people",
    "individuals", "human", "humans",
}
_NON_PRIMARY_TITLES = re.compile(
    r"\\b(?:systematic review|meta.analysis|scoping review|umbrella review|"
    r"network meta.analysis|commentary|comment on|comments to|letter|"
    r"editorial|perspective|narrative review|study protocol|protocol for|"
    r"hypothesis.generating|case report|case series|in vitro|"
    r"animal model|mouse|mice|rat|rats|bibliometric|guideline)\\b",
    flags=re.IGNORECASE,
)


def evaluate_preflight(candidate: CandidateRecord, result: Any) -> dict[str, Any]:
    anchor = set(_anchor(candidate))
    population = set(_tokens(candidate.population)) - _GENERAL_POPULATION_TERMS
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
        suspected_nonprimary = bool(_NON_PRIMARY_TITLES.search(title))
        # This clinical preflight is deliberately conservative. Without at
        # least one population/condition term and an original-report-like
        # title, a raw intervention hit should not dominate topic selection.
        plausible_primary = bool(population_match > 0 and not suspected_nonprimary)
        matched.append({
            "title": title[:260],
            "source": "PubMed",
            "year": _year(getattr(row, "year", None)),
            "pmid": str(getattr(row, "record_id", "") or ""),
            "url": str(getattr(row, "url", "") or ""),
            "intervention_title_match": round(intervention_match, 2),
            "population_title_match": population_match,
            "comparator_title_match": comparator_match,
            "suspected_nonprimary_title": suspected_nonprimary,
            "plausible_original_report_title": plausible_primary,
            "fulltext_eligibility": "NOT_CHECKED",
            "trial_family_independence": "NOT_CONFIRMED",
        })
    current_year = datetime.now(timezone.utc).year
    recent = sum(x["year"] is not None and x["year"] >= current_year - 3 for x in matched)
    relevant_population = sum(x["population_title_match"] > 0 for x in matched)
    relevant_comparator = sum(x["comparator_title_match"] > 0 for x in matched)
    plausible = [item for item in matched if item["plausible_original_report_title"]]
    plausible_recent = sum(x["year"] is not None and x["year"] >= current_year - 3 for x in plausible)
    # Title-only original-report cues are NOT confirmed eligible studies.
    # Avoid ranking commentaries or studies of a different illness highly.
    priority = min(22, 3 * min(len(plausible), 4) + 2 * min(plausible_recent, 3)
                   + 2 * min(sum(x["population_title_match"] > 0 for x in plausible), 2)
                   + min(sum(x["comparator_title_match"] > 0 for x in plausible), 2))
    status = getattr(getattr(result, "status", None), "value", "NOT_SEARCHED")
    return {
        "status": status,
        "query": str(getattr(result, "query", "") or ""),
        "reported_total_matching_query": getattr(result, "total_count", None),
        "records_sampled": len(records),
        "intervention_title_matches": len(matched),
        "recent_intervention_title_matches": recent,
        "plausible_original_report_title_matches": len(plausible),
        "recent_plausible_original_report_title_matches": plausible_recent,
        "discarded_nonprimary_or_other_population_title_leads": len(matched) - len(plausible),
        "population_title_matches": relevant_population,
        "comparator_title_matches": relevant_comparator,
        "priority_signal": priority,
        "evidence_leads": matched[:6],
        "eligible_independent_studies_confirmed": None,
        "novelty_confirmed": False,
        "interpretation": (
            "BIBLIOGRAPHIC_PRIORITY_ONLY: condition-matched original-like title cues are not full-text eligibility, "
            "independent trials, or evidence of novelty; zero title matches "
            "cannot exclude available evidence."
        ),
    }


class FocusedEvidencePreflight:
    def __init__(
        self, source: Any, *, max_candidates: int = 24,
        per_query: int = 12, pause_seconds: float = 0.7,
    ):
        self.source = source
        self.max_candidates = max(0, min(50, int(max_candidates)))
        self.per_query = max(1, min(20, int(per_query)))
        self.pause_seconds = max(0.0, min(2.0, float(pause_seconds)))

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
            # A PubMed preflight calls eSearch and eSummary, often two
            # network requests. Space candidate requests to respect NCBI's
            # unauthenticated request-rate budget without introducing paid APIs.
            if checked and self.pause_seconds:
                time.sleep(self.pause_seconds)
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
