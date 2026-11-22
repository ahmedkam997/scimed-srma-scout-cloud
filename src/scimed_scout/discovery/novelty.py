from __future__ import annotations

import hashlib
from typing import Any

from scimed_scout.competitors import OverlapLevel, SemanticCompetitorAssessor
from scimed_scout.storage import SQLiteLedger


class DiscoveryNoveltyService:
    """Assess only competing reviews/registrations. It never extracts primary-study data."""

    def __init__(self, ledger: SQLiteLedger, assessor: SemanticCompetitorAssessor):
        self.ledger = ledger
        self.assessor = assessor

    def assess_candidate(self, candidate_id: str, *, force: bool = False) -> dict[str, Any]:
        candidate = self.ledger.get_candidate(candidate_id)
        if candidate is None:
            raise ValueError(f"Candidate not found: {candidate_id}")

        review_assessments = [
            self._assess(candidate, record, force=force)
            for record in self.ledger.list_external_evidence(candidate_id, "PUBLISHED_REVIEW")
        ]
        registration_assessments = [
            self._assess(candidate, record, force=force)
            for record in self.ledger.list_external_evidence(candidate_id, "REGISTRATION")
        ]

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
        })
        candidate.metadata = metadata
        self.ledger.upsert_candidate(candidate)

        return {
            "published_reviews_assessed": len(review_assessments),
            "published_reviews_unresolved": review_unresolved,
            "registrations_assessed": len(registration_assessments),
            "registrations_unresolved": registration_unresolved,
            "fatal_redundancy": fatal_redundancy,
            "material_registration_overlap_ids": material_registration_ids,
            "summary": _summary(review_assessments, registration_assessments),
        }

    def _assess(self, candidate, record: dict, *, force: bool) -> dict[str, Any]:
        payload = dict(record.get("payload") or {})
        input_hash = _record_hash(record)
        existing = payload.get("discovery_semantic_assessment")
        if (
            not force
            and isinstance(existing, dict)
            and payload.get("discovery_semantic_assessment_input_hash") == input_hash
        ):
            return existing

        assessment = self.assessor.assess(candidate, record)
        serialized = {
            "record_id": record.get("source_record_id", ""),
            "source": record.get("source", ""),
            "title": record.get("title", ""),
            "overall_overlap": assessment.overall_overlap.value,
            "adequate_review": assessment.adequate_review,
            "recent_review": assessment.recent_review,
            "meaningful_new_information": assessment.meaningful_new_information,
            "confidence": assessment.confidence,
            "rationale": assessment.rationale,
            "reviewer": assessment.reviewer,
            "unresolved": assessment.unresolved,
            "fatal_redundancy": assessment.fatal_redundancy,
        }
        payload["discovery_semantic_assessment"] = serialized
        payload["discovery_semantic_assessment_input_hash"] = input_hash
        self.ledger.upsert_external_evidence(
            candidate.candidate_id,
            record["evidence_type"],
            record["source_record_id"],
            source=record.get("source", ""),
            title=record.get("title", ""),
            payload=payload,
        )
        return serialized


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
