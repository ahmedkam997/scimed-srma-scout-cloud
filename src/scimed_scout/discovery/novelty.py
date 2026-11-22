from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any

from scimed_scout.competitors import OverlapLevel, SemanticCompetitorAssessor
from scimed_scout.storage import SQLiteLedger


class DiscoveryNoveltyService:
    """Assess competing reviews/registrations without extracting primary-study data.

    Records are deterministically deduplicated and ranked for semantic relevance.
    AI assessment is batched to stay within a zero-cost inference budget.
    """

    def __init__(
        self,
        ledger: SQLiteLedger,
        assessor: SemanticCompetitorAssessor,
        *,
        max_reviews: int = 15,
        max_registrations: int = 5,
        batch_size: int = 10,
    ):
        self.ledger = ledger
        self.assessor = assessor
        self.max_reviews = max(1, int(max_reviews))
        self.max_registrations = max(1, int(max_registrations))
        self.batch_size = max(1, min(20, int(batch_size)))

    def assess_candidate(self, candidate_id: str, *, force: bool = False) -> dict[str, Any]:
        candidate = self.ledger.get_candidate(candidate_id)
        if candidate is None:
            raise ValueError(f"Candidate not found: {candidate_id}")

        all_reviews = self.ledger.list_external_evidence(candidate_id, "PUBLISHED_REVIEW")
        all_registrations = self.ledger.list_external_evidence(candidate_id, "REGISTRATION")

        review_records = _select_records(candidate, all_reviews, self.max_reviews)
        registration_records = _select_records(
            candidate,
            all_registrations,
            self.max_registrations,
        )

        review_assessments = self._assess_records(candidate, review_records, force=force)
        registration_assessments = self._assess_records(
            candidate,
            registration_records,
            force=force,
        )

        review_unresolved = sum(bool(item.get("unresolved")) for item in review_assessments)
        registration_unresolved = sum(bool(item.get("unresolved")) for item in registration_assessments)
        fatal_redundancy = any(bool(item.get("fatal_redundancy")) for item in review_assessments)
        material_registration_ids = [
            item.get("record_id", "")
            for item in registration_assessments
            if not item.get("unresolved")
            and item.get("overall_overlap") in {
                OverlapLevel.HIGH.value,
                OverlapLevel.ESSENTIALLY_IDENTICAL.value,
            }
        ]

        metadata = dict(candidate.metadata or {})
        metadata.update({
            "discovery_competitor_assessment_complete": review_unresolved == 0,
            "discovery_registration_assessment_complete": registration_unresolved == 0,
            "discovery_fatal_redundancy": fatal_redundancy,
            "discovery_material_registration_overlap_ids": material_registration_ids,
            "discovery_competitor_records_discovered": len(all_reviews),
            "discovery_competitor_records_semantically_assessed": len(review_records),
            "discovery_registration_records_discovered": len(all_registrations),
            "discovery_registration_records_semantically_assessed": len(registration_records),
            "discovery_semantic_scope_capped": (
                len(review_records) < len(_dedupe_records(all_reviews))
                or len(registration_records) < len(_dedupe_records(all_registrations))
            ),
        })
        candidate.metadata = metadata
        self.ledger.upsert_candidate(candidate)

        return {
            "published_reviews_discovered": len(all_reviews),
            "published_reviews_assessed": len(review_assessments),
            "published_reviews_unresolved": review_unresolved,
            "published_reviews_prefiltered_out": max(
                0,
                len(_dedupe_records(all_reviews)) - len(review_records),
            ),
            "registrations_discovered": len(all_registrations),
            "registrations_assessed": len(registration_assessments),
            "registrations_unresolved": registration_unresolved,
            "registrations_prefiltered_out": max(
                0,
                len(_dedupe_records(all_registrations)) - len(registration_records),
            ),
            "fatal_redundancy": fatal_redundancy,
            "material_registration_overlap_ids": material_registration_ids,
            "summary": _summary(review_assessments, registration_assessments),
        }

    def _assess_records(
        self,
        candidate,
        records: list[dict],
        *,
        force: bool,
    ) -> list[dict[str, Any]]:
        if not records:
            return []

        results_by_id: dict[str, dict[str, Any]] = {}
        pending: list[dict] = []

        for record in records:
            payload = dict(record.get("payload") or {})
            input_hash = _record_hash(record)
            existing = payload.get("discovery_semantic_assessment")
            if (
                not force
                and isinstance(existing, dict)
                and payload.get("discovery_semantic_assessment_input_hash") == input_hash
            ):
                results_by_id[_record_identity(record)] = existing
            else:
                pending.append(record)

        for start in range(0, len(pending), self.batch_size):
            batch = pending[start:start + self.batch_size]
            assessments = self.assessor.assess_many(candidate, batch)
            for record, assessment in zip(batch, assessments):
                serialized = _serialize_assessment(record, assessment)
                self._persist_assessment(
                    candidate.candidate_id,
                    record,
                    serialized,
                )
                results_by_id[_record_identity(record)] = serialized

        return [
            results_by_id[_record_identity(record)]
            for record in records
            if _record_identity(record) in results_by_id
        ]

    def _persist_assessment(
        self,
        candidate_id: str,
        record: dict,
        serialized: dict[str, Any],
    ) -> None:
        payload = dict(record.get("payload") or {})
        payload["discovery_semantic_assessment"] = serialized
        payload["discovery_semantic_assessment_input_hash"] = _record_hash(record)
        self.ledger.upsert_external_evidence(
            candidate_id,
            record["evidence_type"],
            record["source_record_id"],
            source=record.get("source", ""),
            title=record.get("title", ""),
            payload=payload,
        )


def _serialize_assessment(record: dict, assessment) -> dict[str, Any]:
    return {
        "record_id": record.get("source_record_id", ""),
        "source": record.get("source", ""),
        "title": record.get("title", ""),
        "overall_overlap": assessment.overall_overlap.value,
        "dimensions": [
            {
                "name": item.name,
                "level": item.level.value,
                "evidence": item.evidence,
                "rationale": item.rationale,
            }
            for item in assessment.dimensions
        ],
        "adequate_review": assessment.adequate_review,
        "recent_review": assessment.recent_review,
        "meaningful_new_information": assessment.meaningful_new_information,
        "confidence": assessment.confidence,
        "rationale": assessment.rationale,
        "reviewer": assessment.reviewer,
        "unresolved": assessment.unresolved,
        "fatal_redundancy": assessment.fatal_redundancy,
    }


def _select_records(candidate, records: list[dict], limit: int) -> list[dict]:
    unique = _dedupe_records(records)
    if len(unique) <= limit:
        return unique

    candidate_text = " ".join([
        str(candidate.title or ""),
        str(candidate.review_question or ""),
        str(candidate.population or ""),
        str(candidate.intervention_exposure_index_test or ""),
        str(candidate.comparator_reference or ""),
        " ".join(str(x) for x in (candidate.outcomes or [])),
    ])
    candidate_tokens = _tokens(candidate_text)
    current_year = datetime.now(timezone.utc).year

    scored: list[tuple[float, int, dict]] = []
    for index, record in enumerate(unique):
        record_text = _record_text(record)
        record_tokens = _tokens(record_text)
        overlap = (
            len(candidate_tokens & record_tokens) / max(1, len(candidate_tokens))
            if candidate_tokens
            else 0.0
        )
        year = _record_year(record)
        recency = 0.0
        if year is not None:
            if year >= current_year - 5:
                recency = 0.15
            elif year >= current_year - 10:
                recency = 0.05
        evidence_bonus = min(0.10, len(record_text) / 50000.0)
        score = overlap + recency + evidence_bonus
        scored.append((score, -index, record))

    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [record for _, _, record in scored[:limit]]


def _dedupe_records(records: list[dict]) -> list[dict]:
    best: dict[str, dict] = {}
    order: list[str] = []

    for record in records:
        key = _record_key(record)
        if key not in best:
            best[key] = record
            order.append(key)
            continue
        if len(_record_text(record)) > len(_record_text(best[key])):
            best[key] = record

    return [best[key] for key in order]


def _record_key(record: dict) -> str:
    payload = record.get("payload") or {}
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    doi = str(
        payload.get("doi")
        or metadata.get("doi")
        or _external_doi(metadata)
        or ""
    ).strip().casefold()
    doi = doi.removeprefix("https://doi.org/").removeprefix("http://doi.org/")
    if doi:
        return "doi:" + doi.rstrip(".")

    title = " ".join(
        re.sub(r"[^a-z0-9]+", " ", str(record.get("title") or "").casefold()).split()
    )
    if title:
        return "title:" + title

    return (
        "id:"
        + str(record.get("source") or "")
        + ":"
        + str(record.get("source_record_id") or "")
    )


def _record_identity(record: dict) -> str:
    return _record_key(record)


def _record_text(record: dict) -> str:
    payload = record.get("payload") or {}
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    parts = [
        record.get("title"),
        metadata.get("abstract"),
        metadata.get("summary"),
        metadata.get("description"),
        metadata.get("brief_summary"),
        payload.get("abstract"),
        payload.get("summary"),
    ]
    return " ".join(str(x).strip() for x in parts if x and str(x).strip())


def _record_year(record: dict) -> int | None:
    payload = record.get("payload") or {}
    value = payload.get("year")
    if isinstance(value, int):
        return value
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _external_doi(metadata: dict) -> str:
    external = metadata.get("externalIds")
    if isinstance(external, dict):
        return str(external.get("DOI") or external.get("doi") or "")
    article_ids = metadata.get("articleids") or metadata.get("articleIds")
    if isinstance(article_ids, list):
        for item in article_ids:
            if not isinstance(item, dict):
                continue
            if str(item.get("idtype") or item.get("idType") or "").casefold() == "doi":
                return str(item.get("value") or item.get("id") or "")
    return ""


def _tokens(text: str) -> set[str]:
    stop = {
        "the", "and", "for", "with", "from", "into", "among", "after", "before",
        "systematic", "review", "meta", "analysis", "study", "studies", "patients",
        "adults", "effect", "effects", "outcome", "outcomes",
    }
    return {
        token
        for token in re.findall(r"[a-z0-9]{3,}", str(text or "").casefold())
        if token not in stop
    }


def _record_hash(record: dict[str, Any]) -> str:
    payload = record.get("payload") or {}
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    basis = repr((
        record.get("source"),
        record.get("title"),
        payload.get("year"),
        payload.get("doi"),
        metadata,
    ))
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


def _summary(reviews: list[dict], registrations: list[dict]) -> str:
    rows = []
    for kind, items in (("published review", reviews), ("registration", registrations)):
        for item in items:
            rows.append(
                f"{kind}: {item.get('title', '')} | overlap={item.get('overall_overlap', 'UNRESOLVED')} "
                f"| unresolved={bool(item.get('unresolved'))} | fatal={bool(item.get('fatal_redundancy'))}"
            )
    return "\n".join(rows[:30])
