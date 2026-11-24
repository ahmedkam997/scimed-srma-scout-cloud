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

    # These searches find potential competing reviews, not all primary
    # reports. Require a named index intervention AND an additional PICO
    # concept before adding review terms. The old intervention-only
    # "meta-analysis" search returned unrelated animal/cancer reviews.
    review_anchor = " ".join(_registry_anchor(concept)) or concept
    review_condition = " ".join(_registry_focus(subject)[:3]) or subject
    review_outcome = " ".join(_registry_focus(outcome)[:3]) or outcome
    review_comparator = " ".join(_registry_focus(comparator)[:3])
    review = _dedupe([
        _join(review_anchor, review_condition, "systematic review"),
        _join(review_anchor, review_condition, "meta-analysis"),
        _join(review_anchor, review_outcome, "systematic review"),
        _join(review_anchor, review_condition, review_comparator, "meta-analysis")
        if review_comparator else "",
    ])[:max_queries]

    # Official PROSPERO search accepts quoted phrases combined using AND.
    # Long uncontrolled text such as intervention + dose + placebo returned
    # hundreds of unrelated hits and caused incomplete page traversal.
    # Keep each registry search tied to a clinical intervention AND a disease
    # or outcome concept. These are exploratory; not a validated search.
    anchor = _registry_anchor(concept)
    disease = _registry_focus(subject)
    comparator_focus = _registry_focus(comparator)
    outcome_focus = _registry_focus(outcome)
    # Keep registry searches focused rather than splitting the population
    # into unrelated generic fragments ("suspected stable" and "coronary
    # artery" separately). The old 4-variant plan flooded PROSPERO with
    # 100s of irrelevant records, often changing totals during pagination.
    # These are prioritized discovery queries, NOT an exhaustive registry
    # search or evidence that the PICO has no competing registration.
    condition_anchor = _registry_condition_anchor(disease)
    registry = _dedupe([
        _and_query(anchor, condition_anchor),
        _and_query(anchor, comparator_focus[:2]) if comparator_focus else "",
        _and_query(anchor, outcome_focus[:2]) if outcome_focus else "",
    ])[:max_queries]
    if not registry:
        registry = [_registry_phrase(anchor)] if anchor else list(primary[:1])
    registry_anchor = _registry_concept(concept)

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
    text = re.sub(r"\([^)]*\d[^)]*\)", " ", str(value or ""))
    text = text.replace("‑", " ").replace("–", " ").replace("—", " ")
    text = re.sub(r"[^\w\s-]", " ", text, flags=re.UNICODE)
    return " ".join(text.split()[:8])


_REGISTRY_NOISE = {
    "adult", "adults", "patients", "patient", "aged", "years",
    "year", "using", "receiving", "undergoing", "health",
    "intervention", "interventions", "therapy", "therapies",
    "treatment", "treatments", "with", "without", "during", "in",
    "of", "for", "and", "the", "study", "research",
    "ingestion", "administration", "supplementation", "supplement",
    "dose", "dosage", "volume", "weight", "body", "per",
    "matched", "placebo", "sham", "control", "standard", "care",
    "comparator", "followup", "follow", "time", "primary",
    "efficacy", "safety", "effects", "effect", "acute",
    "no", "or", "vs", "versus", "outcomes",
    "before", "after", "min", "minute", "minutes", "daily", "weekly",
    "monthly", "biannually", "at", "on", "high", "low", "inhibitor",
    "inhibitors", "agonist", "agonists", "receiving", "prior",
    "oral", "intravenous", "intramuscular", "percutaneous",
    "derived", "administered", "diagnosed", "suspected", "known",
    "newly", "treated", "implantation", "device", "devices",
}


def _registry_focus(value: str) -> list[str]:
    """Clinical terms, without dose/time and generic Boolean noise."""
    raw = re.sub(r"\([^)]*\)", " ", str(value or ""))
    raw = raw.replace("‑", "-").replace("–", "-").replace("—", "-")
    # Split lexical compounds (e.g. low-dose, sacubitril-valsartan)
    # while retaining hybrid medical codes such as DPP-4 and IL-6.
    # Previously "oral low-dose colchicine" yielded generic "oral low-dose"
    # and dropped the active drug name entirely.
    compounds = re.findall(r"[a-z0-9]+(?:-[a-z0-9]+)*", raw.casefold())
    tokens = []
    for compound in compounds:
        parts = compound.split("-")
        if len(parts) == 2 and (parts[0].isdigit() or parts[1].isdigit()):
            tokens.append(compound)
        else:
            tokens.extend(parts)
    return list(dict.fromkeys(
        token for token in tokens
        if token not in _REGISTRY_NOISE
        and (
            len(token) >= 3
            or (len(token) >= 2 and any(c.isdigit() for c in token)
                and any(c.isalpha() for c in token))
        )
        and not token.isdigit()
    ))


def _registry_condition_anchor(terms: list[str]) -> list[str]:
    """Prioritize a contiguous, clinically meaningful condition concept.

    Do not break a population into stray generic fragments. Specific paired
    concepts improve registry index precision without claiming exhaustive
    sensitivity or equivalence to a librarian-reviewed search strategy.
    """
    words = list(terms)
    priority_pairs = (
        ("left", "main"),
        ("atrial", "fibrillation"),
        ("heart", "failure"),
        ("myocardial", "infarction"),
        ("coronary", "artery"),
        ("renal", "failure"),
        ("kidney", "disease"),
        ("endurance", "athletes"),
    )
    for first, second in priority_pairs:
        for position in range(len(words) - 1):
            if words[position:position + 2] == [first, second]:
                # Coronary artery disease is a useful 3-token condition;
                # retaining 'disease' avoids mixing CAD with all arteries.
                if (first, second) == ("coronary", "artery") and position + 2 < len(words):
                    if words[position + 2] == "disease":
                        return ["coronary", "artery", "disease"]
                return [first, second]
    return words[:2]


def _registry_anchor(intervention: str) -> list[str]:
    terms = _registry_focus(intervention)
    # Four specific tokens retain such essential clinical entities as
    # "left atrial appendage occlusion" and "computed tomography angiography".
    return terms[:4]


def _registry_phrase(words: list[str]) -> str:
    if not words:
        return ""
    return '"' + " ".join(words[:4]).replace('"', "") + '"'


def _and_query(anchor: list[str], supplementary: list[str]) -> str:
    if not anchor or not supplementary:
        return ""
    return _registry_phrase(anchor) + " AND " + _registry_phrase(supplementary)
