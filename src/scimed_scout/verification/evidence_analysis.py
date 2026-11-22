from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from typing import Any

from scimed_scout.competitors import OverlapLevel, SemanticCompetitorAssessor
from scimed_scout.extraction import EligibilityStatus, StudyEligibilityExtractor
from scimed_scout.storage import SQLiteLedger


@dataclass(frozen=True, slots=True)
class EvidenceAnalysisSummary:
    candidate_id: str
    published_reviews_assessed: int
    published_reviews_unresolved: int
    fatal_redundancy: bool
    registrations_assessed: int
    registrations_unresolved: int
    material_registration_overlaps: tuple[str, ...]
    primary_studies_extracted: int
    auto_eligible_studies: int
    auto_ineligible_studies: int
    auto_uncertain_studies: int


class CandidateEvidenceAnalysisService:
    """AI-assisted evidence analysis with deterministic fail-closed outputs.

    AI assessments are stored with provenance and never directly create verified
    study counts. Final study-family and synthesis verification remain separate.
    """

    def __init__(
        self,
        ledger: SQLiteLedger,
        competitor_assessor: SemanticCompetitorAssessor,
        eligibility_extractor: StudyEligibilityExtractor,
    ):
        self.ledger = ledger
        self.competitor_assessor = competitor_assessor
        self.eligibility_extractor = eligibility_extractor

    def analyze_candidate(self, candidate_id: str, *, force: bool = False) -> EvidenceAnalysisSummary:
        candidate = self.ledger.get_candidate(candidate_id)
        if candidate is None:
            raise ValueError(f"Candidate not found: {candidate_id}")

        review_assessments = []
        review_unresolved = 0
        fatal_redundancy = False
        for record in self.ledger.list_external_evidence(candidate_id, "PUBLISHED_REVIEW"):
            assessment = self._assess_competitor(candidate, record, force=force)
            review_assessments.append(assessment)
            review_unresolved += int(assessment["unresolved"])
            fatal_redundancy = fatal_redundancy or bool(assessment["fatal_redundancy"])

        registration_assessments = []
        registration_unresolved = 0
        material_registration_overlaps: list[str] = []
        for record in self.ledger.list_external_evidence(candidate_id, "REGISTRATION"):
            assessment = self._assess_competitor(candidate, record, force=force)
            registration_assessments.append(assessment)
            registration_unresolved += int(assessment["unresolved"])
            if (
                not assessment["unresolved"]
                and assessment["overall_overlap"] in {
                    OverlapLevel.HIGH.value,
                    OverlapLevel.ESSENTIALLY_IDENTICAL.value,
                }
            ):
                material_registration_overlaps.append(record["source_record_id"])

        extracted = []
        for record in self.ledger.list_external_evidence(candidate_id, "PRIMARY_STUDY"):
            extracted.append(self._extract_study(candidate, record, force=force))

        auto_eligible = sum(item["eligibility"] == EligibilityStatus.ELIGIBLE.value for item in extracted)
        auto_ineligible = sum(item["eligibility"] == EligibilityStatus.INELIGIBLE.value for item in extracted)
        auto_uncertain = sum(item["eligibility"] == EligibilityStatus.UNCERTAIN.value for item in extracted)

        metadata = dict(candidate.metadata or {})
        metadata.update({
            "competitor_assessment_complete": review_unresolved == 0,
            "registration_assessment_complete": registration_unresolved == 0,
            "semantic_fatal_redundancy": fatal_redundancy,
            "material_registration_overlap_ids": material_registration_overlaps,
            "study_auto_extraction_complete": all(item["processed"] for item in extracted),
            "auto_eligible_studies": auto_eligible,
            "auto_ineligible_studies": auto_ineligible,
            "auto_uncertain_studies": auto_uncertain,
            "auto_extraction_is_verified_evidence": False,
        })
        candidate.metadata = metadata
        self.ledger.upsert_candidate(candidate)

        return EvidenceAnalysisSummary(
            candidate_id=candidate_id,
            published_reviews_assessed=len(review_assessments),
            published_reviews_unresolved=review_unresolved,
            fatal_redundancy=fatal_redundancy,
            registrations_assessed=len(registration_assessments),
            registrations_unresolved=registration_unresolved,
            material_registration_overlaps=tuple(material_registration_overlaps),
            primary_studies_extracted=len(extracted),
            auto_eligible_studies=auto_eligible,
            auto_ineligible_studies=auto_ineligible,
            auto_uncertain_studies=auto_uncertain,
        )

    def _assess_competitor(self, candidate, record: dict, *, force: bool) -> dict[str, Any]:
        payload = dict(record.get("payload") or {})
        input_hash = _record_hash(record)
        existing = payload.get("semantic_assessment")
        if (
            not force
            and isinstance(existing, dict)
            and payload.get("semantic_assessment_input_hash") == input_hash
        ):
            return _normalized_assessment(existing)

        assessment = self.competitor_assessor.assess(candidate, record)
        serialized = {
            "record_id": assessment.record_id,
            "source": assessment.source,
            "title": assessment.title,
            "overall_overlap": assessment.overall_overlap.value,
            "dimensions": [
                {
                    "name": item.name,
                    "level": item.level.value,
                    "rationale": item.rationale,
                    "evidence": item.evidence,
                }
                for item in assessment.dimensions
            ],
            "adequate_review": assessment.adequate_review,
            "recent_review": assessment.recent_review,
            "meaningful_new_information": assessment.meaningful_new_information,
            "confidence": assessment.confidence,
            "evidence_text_available": assessment.evidence_text_available,
            "rationale": assessment.rationale,
            "reviewer": assessment.reviewer,
            "unresolved": assessment.unresolved,
            "fatal_redundancy": assessment.fatal_redundancy,
        }
        payload["semantic_assessment"] = serialized
        payload["semantic_assessment_input_hash"] = input_hash
        payload["verification_status"] = (
            "SEMANTIC_UNRESOLVED" if assessment.unresolved else "SEMANTIC_ASSESSED"
        )
        self.ledger.upsert_external_evidence(
            candidate.candidate_id,
            record["evidence_type"],
            record["source_record_id"],
            source=record.get("source", ""),
            title=record.get("title", ""),
            payload=payload,
        )
        return serialized

    def _extract_study(self, candidate, record: dict, *, force: bool) -> dict[str, Any]:
        payload = dict(record.get("payload") or {})
        input_hash = _record_hash(record)
        existing = payload.get("study_eligibility_extraction")
        if (
            not force
            and isinstance(existing, dict)
            and payload.get("study_extraction_input_hash") == input_hash
        ):
            extraction_payload = existing
        else:
            extraction = self.eligibility_extractor.extract(candidate, record)
            extraction_payload = {
                **asdict(extraction),
                "eligibility": extraction.eligibility.value,
                "verification": extraction.verification.value,
                "ready_for_manual_verification": extraction.ready_for_manual_verification,
            }
            payload["study_eligibility_extraction"] = extraction_payload
            payload["study_extraction_input_hash"] = input_hash
            payload["verification_status"] = "AUTO_EXTRACTED"
            self.ledger.upsert_external_evidence(
                candidate.candidate_id,
                "PRIMARY_STUDY",
                record["source_record_id"],
                source=record.get("source", ""),
                title=record.get("title", ""),
                payload=payload,
            )

        study_payload = {
            "study_id": record["source_record_id"],
            "title": record.get("title", ""),
            "source": record.get("source", ""),
            "doi": payload.get("doi", ""),
            "verification_status": "AUTO_EXTRACTED",
            "eligibility_status": extraction_payload.get("eligibility", EligibilityStatus.UNCERTAIN.value),
            "eligibility_verified": False,
            "design_verified": False,
            "independence_verified": False,
            "extraction": extraction_payload,
            "source_provenance": {
                "source_record_id": record["source_record_id"],
                "source": record.get("source", ""),
                "url": payload.get("url", ""),
            },
        }
        self.ledger.upsert_payload(
            "studies",
            candidate.candidate_id,
            record["source_record_id"],
            study_payload,
        )
        return {
            "processed": True,
            "eligibility": study_payload["eligibility_status"],
            "study_id": record["source_record_id"],
        }


def _record_hash(record: dict) -> str:
    payload = record.get("payload") or {}
    metadata = payload.get("metadata") or {}
    full_text = str(payload.get("full_text") or "")
    full_text_hash = hashlib.sha256(full_text.encode("utf-8")).hexdigest() if full_text else ""
    chunks = payload.get("full_text_chunks") if isinstance(payload.get("full_text_chunks"), list) else []
    basis = repr((
        record.get("title"),
        record.get("source"),
        payload.get("year"),
        payload.get("doi"),
        metadata,
        full_text_hash,
        chunks,
    ))
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


def _normalized_assessment(value: dict[str, Any]) -> dict[str, Any]:
    return {
        **value,
        "overall_overlap": str(value.get("overall_overlap") or OverlapLevel.UNRESOLVED.value),
        "unresolved": bool(value.get("unresolved", True)),
        "fatal_redundancy": bool(value.get("fatal_redundancy", False)),
    }
