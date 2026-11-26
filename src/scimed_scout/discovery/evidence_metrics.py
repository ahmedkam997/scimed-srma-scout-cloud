"""Exploratory, evidence-anchored topic discovery metrics.

These are transparent bibliographic proxies, NOT a validated novelty instrument,
Bayesian expected value of information, study-level eligibility assessment,
or a quantitative estimate of publication probability.

Methods are grounded in question overlap, surveillance for new evidence, and
multi-criteria priority setting. Scales/weights are explicitly local assumptions.
"""
from __future__ import annotations

import re
from typing import Any


VERSION = "SCIMED_DISCOVERY_MCDA_V1_EXPLORATORY"
OVERLAP_SEVERITY = {
    "NONE": 0.0,
    "LOW": 0.20,
    "MODERATE": 0.50,
    "HIGH": 0.80,
    "ESSENTIALLY_IDENTICAL": 1.0,
}
CRITERION_WEIGHTS = {
    "overall_novelty": 0.30,
    "new_information_gain": 0.25,
    "clinical_importance": 0.20,
    "feasibility": 0.15,
    "publication_potential": 0.10,
}
CLINICAL_DIMENSION_WEIGHTS = {
    "population": 0.20,
    "intervention_exposure_index_test": 0.25,
    "comparator_reference": 0.10,
    "outcomes": 0.20,
    "design_scope": 0.10,
    "clinical_decision": 0.15,
}
FEASIBILITY_VALUE = {
    "HIGH": 5.0,
    "STRONG MODERATE": 4.0,
    "MODERATE": 2.5,
    "LOW": 1.0,
}


def _year(value: Any) -> int | None:
    match = re.search(r"(?:19|20)\d{2}", str(value or ""))
    if match is None:
        return None
    number = int(match.group())
    return number if 1900 <= number <= 2100 else None


def _key(record: dict) -> str:
    payload = record.get("payload") or {}
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    doi = str(payload.get("doi") or metadata.get("doi") or "").casefold().strip()
    doi = doi.removeprefix("https://doi.org/").removeprefix("http://doi.org/").rstrip(".")
    if doi:
        return "doi:" + doi
    title = " ".join(re.findall(r"[a-z0-9]+", str(record.get("title") or "").casefold()))
    if title:
        return "title:" + title
    return "source:" + str(record.get("source_record_id") or "")


def _unique_records(records: list[dict]) -> list[dict]:
    from .pico_matching import _groups, _doi, _pmid
    from .review_opportunity import CUTOFF_FIELDS, _cutoff
    from .competitor_records import abstract
    unique=[]
    date_fields=(*CUTOFF_FIELDS,"search_date_evidence_quote","search_date_evidence_url","search_date_evidence_level")
    for group in _groups(records):
        variants=group["records"]
        preferred=max(variants,key=lambda r:(bool((r.get("payload") or {}).get("discovery_semantic_assessment")),len(abstract(r))))
        payload=dict(preferred.get("payload") or {})
        meta=dict(payload.get("metadata") or {})
        # Only exact bibliographic identity allows metadata transfer.
        exact=[r for r in variants if r is preferred or (_doi(preferred) and _doi(r)==_doi(preferred)) or (_pmid(preferred) and _pmid(r)==_pmid(preferred))]
        # Search-date provenance is atomic: never join a bare date with an
        # unrelated quote, URL or evidence level from a different variant.
        verified=[(r,_cutoff(r)) for r in exact if _cutoff(r)]
        if verified:
            best=max(verified,key=lambda x:x[1]["end"])[0]
            other=(best.get("payload") or {}).get("metadata") or {}
            for field in date_fields:meta.pop(field,None)
            for field in date_fields:
                if other.get(field):meta[field]=other[field]
        # Preserve earliest reported publication year when exact variants
        # disagree, so print publication cannot masquerade as new evidence.
        years=[_year((r.get("payload") or {}).get("year")) for r in exact]
        years=[v for v in years if v is not None]
        if years:payload["year"]=min(years)
        assessments=[(r.get("payload") or {}).get("discovery_semantic_assessment") for r in exact]
        assessments=[v for v in assessments if isinstance(v,dict)]
        if len({str(v.get("overall_overlap")) for v in assessments})>1 or any(v.get("unresolved") for v in assessments):
            assessment=dict(payload.get("discovery_semantic_assessment") or assessments[0]);assessment["unresolved"]=True;payload["discovery_semantic_assessment"]=assessment
        payload["metadata"]=meta
        unique.append({**preferred,"payload":payload})
    return unique


def _assessed(records: list[dict]) -> list[tuple[dict, dict]]:
    pairs = []
    for record in _unique_records(records):
        payload = record.get("payload") or {}
        assessment = payload.get("discovery_semantic_assessment")
        if isinstance(assessment, dict):
            pairs.append((record, assessment))
    return pairs


def _clinical_overlap(assessment: dict) -> float | None:
    dimensions = assessment.get("dimensions")
    if not isinstance(dimensions, list):
        return None
    observed = {}
    for row in dimensions:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "")
        level = str(row.get("level") or "")
        quote = str(row.get("evidence") or "").strip()
        if name in CLINICAL_DIMENSION_WEIGHTS and level in OVERLAP_SEVERITY and quote:
            observed[name] = OVERLAP_SEVERITY[level]
    # At least four clinical dimensions with traceable source quotes are required.
    if len(observed) < 4:
        return None
    total = sum(CLIM * observed[name] for name, CLIM in CLINICAL_DIMENSION_WEIGHTS.items() if name in observed)
    weight = sum(CLIM for name, CLIM in CLINICAL_DIMENSION_WEIGHTS.items() if name in observed)
    return total / weight if weight else None


def evidence_metrics(
    reviews: list[dict],
    registrations: list[dict],
    primary_records: list[dict],
    *,
    semantically_capped: bool = False,
) -> dict[str, Any]:
    """Evaluate supported overlap signals and new-evidence bibliographic proxy.

    Not finding a competitor is never proof that none exists. Source coverage
    remains an independent hard gate elsewhere in the discovery engine.
    """
    review_pairs = _assessed(reviews)
    registration_pairs = _assessed(registrations)
    assessed = review_pairs + registration_pairs
    unique_reviews = _unique_records(reviews)
    unique_regs = _unique_records(registrations)
    unresolved = (
        semantically_capped
        or len(review_pairs) < len(unique_reviews)
        or len(registration_pairs) < len(unique_regs)
        or any(
            bool(item.get("unresolved"))
            or str(item.get("overall_overlap")) not in OVERLAP_SEVERITY
            or float(item.get("confidence") or 0.0) < 0.8
            or _clinical_overlap(item) is None
            for _, item in assessed
        )
    )
    scope_note = "Unresolved or unassessed competitor records" if unresolved else "All selected competitor records assessed"
    worst = max((OVERLAP_SEVERITY[a["overall_overlap"]] for _, a in assessed if a.get("overall_overlap") in OVERLAP_SEVERITY), default=None)
    if unresolved:
        novelty = 0.0
        clinical_novelty = 0.0
        novelty_status = "NOT_ESTIMABLE"
    elif worst is None:
        novelty = 4.0
        clinical_novelty = 4.0
        novelty_status = "NO_COMPETITOR_FOUND_PROVISIONAL"
    else:
        novelty = round(5.0 * (1.0 - worst), 2)
        clinical_overlaps = [
            value for _, item in assessed
            if (value := _clinical_overlap(item)) is not None
        ]
        clinical_novelty = round(5.0 * (1.0 - max(clinical_overlaps)), 2) if clinical_overlaps else novelty
        novelty_status = "EVIDENCE_ANCHORED_ORDINAL_PROXY"

    # This calculates a bibliographic incremental-evidence signal, not
    # information gain in the Bayesian/decision-theoretic sense.
    related_reviews = [
        record for record, assessment in review_pairs
        if not assessment.get("unresolved")
        and assessment.get("overall_overlap") in ("HIGH", "ESSENTIALLY_IDENTICAL")
    ]
    dated_primary = [
        (_key(record), _year((record.get("payload") or {}).get("year")))
        for record in _unique_records(primary_records)
    ]
    dated_primary = [(key, year) for key, year in dated_primary if year is not None]
    distinct_primary_count = len(_unique_records(primary_records))
    date_coverage = len(dated_primary) / distinct_primary_count if distinct_primary_count else 0.0
    new_since = None
    baseline_year = None
    review_pub_years = [
        _year((record.get("payload") or {}).get("year"))
        for record in related_reviews
    ]
    latest_review_pub_year = max((y for y in review_pub_years if y), default=None)
    post_pub = sum(year > latest_review_pub_year for _, year in dated_primary) if latest_review_pub_year else None
    if unresolved:
        gain = 0.0
        gain_status = "NOT_ESTIMABLE_COMPETITOR_SCOPE"
    elif not related_reviews:
        # This is only a bibliographic lead until full-text and source
        # coverage confirm that there are no newer competing syntheses.
        gain = 4.0 if distinct_primary_count >= 4 else 0.0
        gain_status = "NO_MATCHING_EXISTING_SYNTHESIS_PROVISIONAL"
    else:
        search_dates = []
        for record in related_reviews:
            payload = record.get("payload") or {}
            metadata = payload.get("metadata") or {}
            if not isinstance(metadata, dict):
                metadata = {}
            explicit_cutoff = next((
                metadata.get(key)
                for key in (
                    "last_search_date", "date_last_searched", "search_end_date",
                    "date_of_last_search", "search_cutoff",
                )
                if metadata.get(key)
            ), None)
            search_dates.append(_year(explicit_cutoff))
        if not search_dates or any(y is None for y in search_dates):
            gain = 0.0
            gain_status = "NOT_ESTIMABLE_REVIEW_SEARCH_DATE"
        elif date_coverage < 0.8:
            gain = 0.0
            gain_status = "NOT_ESTIMABLE_PRIMARY_DATES"
        else:
            baseline_year = max(y for y in search_dates if y is not None)
            new_since = sum(year > baseline_year for _, year in dated_primary)
            gain = round(5.0 * new_since / max(1, distinct_primary_count), 2)
            gain_status = "POST_DOCUMENTED_SEARCH_CUTOFF_BIBLIOGRAPHIC_PROXY"

    refs = [
        {
            "source": str(record.get("source") or ""),
            "title": str(record.get("title") or ""),
            "record_id": str(record.get("source_record_id") or ""),
            "doi": str((record.get("payload") or {}).get("doi") or ""),
            "url": str((record.get("payload") or {}).get("url") or ""),
            "overlap": str(a.get("overall_overlap") or ""),
            "confidence": float(a.get("confidence") or 0.0),
        }
        for record, a in assessed
    ]
    return {
        "method_version": VERSION,
        "validated_instrument": False,
        "scope_assessment": scope_note,
        "novelty_status": novelty_status,
        "clinical_question_novelty": clinical_novelty,
        "overall_novelty": novelty,
        "new_information_gain": gain,
        "information_gain_status": gain_status,
        "information_gain_is_formal_voi": False,
        "study_count_discovered_not_eligible": distinct_primary_count,
        "dated_primary_records": len(dated_primary),
        "primary_date_completeness": round(date_coverage, 3),
        "latest_related_review_publication_year": latest_review_pub_year,
        "latest_related_review_search_year": baseline_year,
        "primary_records_newer_than_publication": post_pub,
        "primary_records_newer_than_review_search": new_since,
        "competing_reviews_assessed": len(review_pairs),
        "registrations_assessed": len(registration_pairs),
        "overlap_evidence": refs[:25],
        "limitations": [
            "Title/abstract retrieval does not establish full-text eligibility or study-family independence.",
            "Publication-year comparisons do not replace manual verification of each review's last search date.",
            "The 0–5 scales are exploratory prioritization proxies, not externally validated clinical measurements.",
            "CCA requires included-primary-study citation matrices and is not computable from this discovery corpus.",
            "Formal Bayesian value of information requires uncertainty and decision utility, unavailable here.",
        ],
    }


def composite_score(
    *,
    novelty: float,
    information_gain: float,
    clinical_importance: float,
    feasibility: str,
    publication_potential: float,
) -> dict[str, Any]:
    values = {
        "overall_novelty": float(novelty),
        "new_information_gain": float(information_gain),
        "clinical_importance": float(clinical_importance),
        "feasibility": FEASIBILITY_VALUE.get(str(feasibility).strip().upper(), 0.0),
        "publication_potential": float(publication_potential),
    }
    total = sum(CRITERION_WEIGHTS[key] * max(0.0, min(5.0, values[key])) for key in CRITERION_WEIGHTS)
    score = round(total * 20.0, 2)
    # Nonvalidated illustrative sensitivity check: move 10 percentage points
    # from novelty to clinical relevance, and vice versa.
    alternative_scores = []
    for novelty_weight, importance_weight in ((0.20, 0.30), (0.40, 0.10)):
        weights = {
            **CRITERION_WEIGHTS,
            "overall_novelty": novelty_weight,
            "clinical_importance": importance_weight,
        }
        alternative_scores.append(round(20.0 * sum(weights[k] * max(0.0, min(5.0, values[k])) for k in weights), 2))
    return {
        "publication_oriented_score": score,
        "criteria_values": values,
        "criteria_weights": dict(CRITERION_WEIGHTS),
        "sensitivity_score_range": [min([score, *alternative_scores]), max([score, *alternative_scores])],
        "score_role": "UNVALIDATED_EXPLORATORY_MCDA_PRIORITY_INDEX_NOT_PUBLICATION_PROBABILITY",
    }
