"""Conservative within-run PICO diversity for review-topic discovery.

Pre-verification triage only. This heuristic prevents obviously near-identical
questions from consuming two full source audits. It does not assert equivalence
of clinical effects, trial families, or systematic-review protocols.
"""
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any

_STOP = frozenset({
    "a", "an", "and", "the", "in", "of", "to", "for", "with", "among",
    "by", "during", "versus", "vs", "patients", "patient", "effects",
    "effect", "impact", "effectiveness", "outcomes", "outcome", "on",
    "study", "studies", "review", "systematic", "meta", "analysis",
    "undergoing", "plus", "adjunctive",
})
_YOUNG = {"child", "children", "pediatric", "paediatric", "adolescent"}
_ADULT = {"adult", "adults", "elderly", "older", "geriatric"}


def _field(obj: Any, field: str) -> Any:
    return obj.get(field) if isinstance(obj, dict) else getattr(obj, field, "")


def _tokens(value: Any) -> set[str]:
    if isinstance(value, (tuple, list)):
        value = " ".join(str(v) for v in value)
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    text = text.replace("\u2011", "-").replace("\u2010", "-")
    words = re.findall(r"[a-z0-9\u0600-\u06ff]+", text)
    return {word for word in words if word not in _STOP}


def _containment(a: Any, b: Any) -> float:
    left, right = _tokens(a), _tokens(b)
    if not left or not right:
        return 0.0
    return len(left & right) / min(len(left), len(right))


def _name_similarity(a: Any, b: Any) -> float:
    left = " ".join(sorted(_tokens(a)))
    right = " ".join(sorted(_tokens(b)))
    return SequenceMatcher(None, left, right).ratio() if left and right else 0.0


def same_clinical_question(a: Any, b: Any) -> bool:
    """Match only highly similar, same-type PICOs with shared main outcomes.

    A contrasting population age, comparator, clinical outcome or question type
    is a reason to KEEP separate topics even if title wording overlaps.
    """
    if str(_field(a, "question_type") or "").strip().upper() != str(
        _field(b, "question_type") or ""
    ).strip().upper():
        return False
    population_a = _tokens(_field(a, "population"))
    population_b = _tokens(_field(b, "population"))
    if (population_a & _YOUNG and population_b & _ADULT) or (
        population_b & _YOUNG and population_a & _ADULT
    ):
        return False
    # Numeric PICO qualifiers (e.g. different age cutoffs, stages or target
    # disease identifiers) are clinically meaningful, not formatting noise.
    for dimension in ("population", "intervention_exposure_index_test", "comparator_reference"):
        a_nums = {x for x in _tokens(_field(a, dimension)) if x.isdigit()}
        b_nums = {x for x in _tokens(_field(b, dimension)) if x.isdigit()}
        if a_nums != b_nums:
            return False
    intervention = _containment(
        _field(a, "intervention_exposure_index_test"),
        _field(b, "intervention_exposure_index_test"),
    )
    population = _containment(_field(a, "population"), _field(b, "population"))
    comparator_a, comparator_b = _field(a, "comparator_reference"), _field(b, "comparator_reference")
    comparator = _containment(comparator_a, comparator_b)
    outcomes_a, outcomes_b = _field(a, "outcomes"), _field(b, "outcomes")
    outcomes = _containment(outcomes_a, outcomes_b)
    title = _name_similarity(_field(a, "title"), _field(b, "title"))

    return (
        intervention >= 0.85
        and population >= 0.60
        and comparator >= 0.70
        and outcomes >= 0.25
        and title >= 0.65
    )


def select_diverse_ranked(
    ranked: list[Any],
    by_id: dict[str, Any],
    *,
    limit: int,
) -> tuple[list[Any], list[dict[str, str]]]:
    """Select highest-ranked representative of each distinct question cluster."""
    kept: list[Any] = []
    skipped: list[dict[str, str]] = []
    for ranked_item in ranked:
        candidate = by_id.get(ranked_item.candidate_id)
        if candidate is None:
            continue
        matching = next(
            (chosen for chosen in kept
             if same_clinical_question(candidate, by_id[chosen.candidate_id])),
            None,
        )
        if matching is not None:
            skipped.append({
                "candidate_id": ranked_item.candidate_id,
                "title": str(_field(candidate, "title") or ""),
                "matched_candidate_id": matching.candidate_id,
                "matched_title": str(_field(by_id[matching.candidate_id], "title") or ""),
                "reason": "NEAR_DUPLICATE_PICO_WITHIN_RUN",
            })
            continue
        if len(kept) < max(0, limit):
            kept.append(ranked_item)
    return kept, skipped
