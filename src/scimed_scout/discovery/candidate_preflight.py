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
    # Reuse the clinical registry anchor normalization. The earlier
    # title-level preflight searched for literal "oral colchicine daily",
    # yielding zero despite the wider colchicine literature. This search
    # only prioritizes bibliographic leads, never estimates eligibility.
    from scimed_scout.verification.queries import _registry_anchor

    terms = _registry_anchor(candidate.intervention_exposure_index_test)
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
    intervention = " ".join(terms[:4]).replace('"', "")
    return (
        f'"{intervention}"[Title/Abstract] AND '
        f'("{year - 5}/01/01"[Date - Publication] : '
        f'"{year}/12/31"[Date - Publication])'
    )



def review_search_query(
    candidate: CandidateRecord, *, current_year: int | None = None,
) -> str:
    """A second FREE PubMed query for potential competing published reviews.

    Year range uses publication dates, NOT the last literature search date.
    Search results are risk cues, not a novelty-clearance certificate.
    """
    terms = _anchor(candidate)
    if not terms:
        return ""
    year = current_year or datetime.now(timezone.utc).year
    intervention = " ".join(terms[:3]).replace('"', "")
    return (
        f'"{intervention}"[Title/Abstract] AND '
        f'("systematic review"[Publication Type] OR '
        f'"meta-analysis"[Publication Type]) AND '
        f'("{year - 8}/01/01"[Date - Publication] : '
        f'"{year}/12/31"[Date - Publication])'
    )


def review_competitor_risk(
    candidate: CandidateRecord, result: Any, *, current_year: int | None = None,
) -> dict[str, Any]:
    """Title-level review overlap risk for RANKING, not scientific exclusion."""
    from scimed_scout.discovery.evidence_classification import classify_review_search_hit

    year = current_year or datetime.now(timezone.utc).year
    anchor = set(_anchor(candidate)[:2])
    population = set(_tokens(candidate.population)) - _GENERAL_POPULATION_TERMS
    outcomes = set(_tokens(" ".join(candidate.outcomes or [])))
    matches = []
    recent = 0
    old = 0
    for row in list(getattr(result, "records", []) or []):
        # PubMed publication type is present on most but not all indexed
        # citations. A true systematic-review cue is required.
        if classify_review_search_hit(row) != "CONFIRMED_REVIEW_CUE":
            continue
        words = set(_tokens(getattr(row, "title", "") or ""))
        if not words or not anchor or len(words & anchor) / len(anchor) < 0.5:
            continue
        relation = bool(words & (population | outcomes))
        pub_year = _year(getattr(row, "year", None))
        if not relation:
            continue
        if pub_year is not None and pub_year >= year - 2:
            recent += 1
        elif pub_year is not None and pub_year <= year - 4:
            old += 1
        if len(matches) < 8:
            matches.append({
                "title": getattr(row, "title", ""),
                "year": pub_year,
                "url": str(getattr(row, "url", "") or ""),
                "record_id": str(getattr(row, "record_id", "") or ""),
                "review_type_source": "PubMed publication type or title",
                "actual_last_literature_search_date": None,
                "pico_overlap": "NOT_VERIFIED",
            })
    status = getattr(getattr(result, "status", None), "value", "NOT_SEARCHED")
    # A recently published overlapping review warrants checking before
    # spending deep verification credits, but an old one may be updatable.
    # Never let review absence imply confirmed novelty.
    penalty = min(12, 5 * min(recent, 2))
    return {
        "review_preflight_status": status,
        "review_preflight_query": str(getattr(result, "query", "") or ""),
        "potential_competing_review_title_cues": matches,
        "recent_review_overlap_risk_cues": recent,
        "older_review_possible_update_cues": old,
        "review_overlap_priority_penalty": penalty,
        "last_search_dates_verified": False,
        "review_publication_date_is_not_search_date": True,
        "scientific_novelty_confirmed": False,
    }


_GENERAL_POPULATION_TERMS = {
    "adult", "adults", "patient", "patients", "aged", "age", "years",
    "year", "male", "female", "women", "men", "person", "people",
    "individuals", "human", "humans",
}
_NON_PRIMARY_TITLES = re.compile(
    r"\b(?:systematic review|meta.analysis|scoping review|umbrella review|"
    r"network meta.analysis|commentary|comment on|comments to|letter|"
    r"editorial|perspective|narrative review|study protocol|protocol for|"
    r"hypothesis.generating|case report|case series|in vitro|"
    r"animal model|mouse|mice|rat|rats|bibliometric|guideline)\b",
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
        review_risk_preflight: bool = False,
    ):
        self.source = source
        self.max_candidates = max(0, min(50, int(max_candidates)))
        self.per_query = max(1, min(20, int(per_query)))
        self.pause_seconds = max(0.0, min(2.0, float(pause_seconds)))
        self.review_risk_preflight = bool(review_risk_preflight)

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
                if self.review_risk_preflight:
                    # Separate review search adds a source-backed indication
                    # of heavily synthesized questions before deep checks.
                    # Respect the anonymous NCBI three-requests/sec budget.
                    if self.pause_seconds:
                        time.sleep(self.pause_seconds)
                    review_query = review_search_query(candidate)
                    try:
                        reviewed = self.source.search(
                            review_query, limit=self.per_query,
                        )
                        risk = review_competitor_risk(candidate, reviewed)
                        signal.update(risk)
                        if risk["review_preflight_status"] == SourceStatus.SEARCHED_POSITIVE.value:
                            signal["priority_signal"] = max(
                                0, signal["priority_signal"] -
                                risk["review_overlap_priority_penalty"]
                            )
                    except Exception as review_exc:
                        signal.update({
                            "review_preflight_status": SourceStatus.ACCESS_FAILED.value,
                            "review_preflight_query": review_query,
                            "review_preflight_error_type": type(review_exc).__name__,
                            "review_overlap_priority_penalty": 0,
                            "scientific_novelty_confirmed": False,
                        })
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
