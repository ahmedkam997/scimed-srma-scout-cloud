from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class EligibilityStatus(StrEnum):
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"
    UNCERTAIN = "UNCERTAIN"


class ExtractionVerification(StrEnum):
    AUTO_EXTRACTED = "AUTO_EXTRACTED"
    MANUAL_VERIFIED = "MANUAL_VERIFIED"


@dataclass(frozen=True, slots=True)
class ProvenanceField:
    value: Any
    evidence: str = ""
    source_section: str = ""
    confidence: float = 0.0


@dataclass(slots=True)
class StudyEligibilityExtraction:
    study_id: str
    title: str
    eligibility: EligibilityStatus
    design_label: ProvenanceField
    population: ProvenanceField
    intervention_exposure_index_test: ProvenanceField
    comparator_reference: ProvenanceField
    outcomes: ProvenanceField
    sample_size: ProvenanceField
    registry_ids: ProvenanceField
    first_author: ProvenanceField
    year: ProvenanceField
    exclusion_reason: str = ""
    exclusion_evidence: str = ""
    overall_confidence: float = 0.0
    unresolved_fields: list[str] = field(default_factory=list)
    verification: ExtractionVerification = ExtractionVerification.AUTO_EXTRACTED
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def ready_for_manual_verification(self) -> bool:
        return self.eligibility != EligibilityStatus.UNCERTAIN and self.overall_confidence >= 0.80
