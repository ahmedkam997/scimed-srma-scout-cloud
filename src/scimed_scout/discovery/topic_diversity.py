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


_FAMILY_STOP = frozenset({
    "adult", "adults", "patient", "patients", "year", "years",
    "aged", "age", "therapy", "therapies", "intervention",
    "treatment", "treatments", "inhibitor", "inhibitors", "standard",
    "usual", "routine", "care", "oral", "administration", "ingestion",
    "supplement", "supplements", "supplementation", "medicine",
    "clinical", "women", "men", "male", "female", "people", "human",
    "no", "sham", "versus", "alone", "and", "the", "not",
})


def _clinical_focus(value: Any) -> set[str]:
    return {word for word in _tokens(value)
            if word not in _FAMILY_STOP and not word.isdigit() and len(word) >= 2}


def same_discovery_family(a: Any, b: Any) -> bool:
    """Group high-overlap clinical opportunity families for source-audit budgets.

    This is strictly a scheduling rule. Differing subgroups, outcomes and
    designs stay in the generated drafts and remain distinct scientific PICOs.
    Do not use this to assert full clinical equivalence or manuscript redundancy.
    """
    if str(_field(a, "question_type") or "").upper() != str(
        _field(b, "question_type") or ""
    ).upper():
        return False
    pa, pb = _tokens(_field(a, "population")), _tokens(_field(b, "population"))
    if (pa & _YOUNG and pb & _ADULT) or (pb & _YOUNG and pa & _ADULT):
        return False
    # Keep genuinely different dose or device variants as independent
    # opportunities rather than merging clinically meaningful interventions.
    ia, ib = _field(a, "intervention_exposure_index_test"), _field(
        b, "intervention_exposure_index_test"
    )
    ia_nums = {x for x in _tokens(ia) if x.isdigit()}
    ib_nums = {x for x in _tokens(ib) if x.isdigit()}
    if ia_nums != ib_nums:
        return False
    ia_terms, ib_terms = _clinical_focus(ia), _clinical_focus(ib)
    pa_terms, pb_terms = _clinical_focus(_field(a, "population")), _clinical_focus(
        _field(b, "population")
    )
    ca_terms, cb_terms = _clinical_focus(_field(a, "comparator_reference")), _clinical_focus(
        _field(b, "comparator_reference")
    )
    if not ia_terms or not ib_terms or not pa_terms or not pb_terms:
        return False
    intervention = len(ia_terms & ib_terms) / min(len(ia_terms), len(ib_terms))
    population_shared = bool(pa_terms & pb_terms)
    comparator_match = (
        (not ca_terms and not cb_terms)
        or (bool(ca_terms and cb_terms)
            and len(ca_terms & cb_terms) / min(len(ca_terms), len(cb_terms)) >= 0.5)
    )
    return intervention >= 0.75 and population_shared and comparator_match


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
             if same_clinical_question(candidate, by_id[chosen.candidate_id])
             or same_discovery_family(candidate, by_id[chosen.candidate_id])),
            None,
        )
        if matching is not None:
            skipped.append({
                "candidate_id": ranked_item.candidate_id,
                "title": str(_field(candidate, "title") or ""),
                "matched_candidate_id": matching.candidate_id,
                "matched_title": str(_field(by_id[matching.candidate_id], "title") or ""),
                "reason": (
                    "NEAR_DUPLICATE_PICO_WITHIN_RUN"
                    if same_clinical_question(candidate, by_id[matching.candidate_id])
                    else "SAME_CLINICAL_DISCOVERY_FAMILY_BUDGET_ONLY"
                ),
            })
            continue
        if len(kept) < max(0, limit):
            kept.append(ranked_item)
    return kept, skipped
