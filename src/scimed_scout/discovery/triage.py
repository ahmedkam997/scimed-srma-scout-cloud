"""Explanatory discovery triage, distinct from final protocol GO/NO-GO.

These labels recommend the NEXT ACTION; they never change scientific gates,
full-text eligibility, or evidence-independence checks.
"""
from __future__ import annotations

from typing import Any

from scimed_scout.domain import CandidateStatus


def discovery_triage(verification: Any, *, pico_fit: dict | None = None) -> dict:
    status = verification.candidate_status
    fit = pico_fit or {}
    if status == CandidateStatus.QUALIFIED:
        return {
            "label": "GO",
            "decision_scope": "DISCOVERY_ONLY_REQUIRES_INDEPENDENT_VALIDATION",
            "reason": "All configured discovery checks passed, but independent full-text verification is required.",
            "next_action": "Recheck source coverage, trial-family independence and extractable outcomes before protocol registration.",
        }
    if status == CandidateStatus.REJECTED:
        return {
            "label": "NO-GO",
            "decision_scope": "PRELIMINARY_DISCOVERY_NOT_FULL_TEXT_ADJUDICATION",
            "reason": verification.decision,
            "next_action": "Review the failed discovery gate and PICO before considering a different question.",
        }

    primary = verification.evidence.unique_primary_study_candidates
    both = int(fit.get("intervention_population_title_matches") or 0)
    intervention = int(fit.get("intervention_title_matches") or 0)
    # No title hits from a sufficiently large retrieved pool signals that
    # the PICO/search terms deserve refinement. This is not proof of no trials.
    if primary >= 15 and intervention == 0 and both == 0:
        return {
            "label": "REFINE",
            "decision_scope": "PICO_OR_SEARCH_STRATEGY_REFINEMENT_NOT_SCIENTIFIC_REJECTION",
            "reason": (
                "No intervention-title matches in a sizable unscreened bibliography sample. "
                "The source search may still miss eligible trials."
            ),
            "next_action": "Refine intervention synonyms and comparator/population, rerun sensitive database searches, then screen full texts.",
        }
    return {
        "label": "UNRESOLVED",
        "decision_scope": "PENDING_VERIFIED_EVIDENCE",
        "reason": (
            "; ".join(verification.coverage.blockers[:3])
            if verification.coverage.blockers
            else "Competing reviews, new independent studies or methodological suitability remain unverified."
        ),
        "next_action": (
            "Complete required registry/pipeline searches and verify overlapping reviews, "
            "published search dates and independent eligible studies."
        ),
    }
