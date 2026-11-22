from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class OverlapLevel(StrEnum):
    NONE = "NONE"
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    ESSENTIALLY_IDENTICAL = "ESSENTIALLY_IDENTICAL"
    UNRESOLVED = "UNRESOLVED"


@dataclass(frozen=True, slots=True)
class DimensionAssessment:
    name: str
    level: OverlapLevel
    rationale: str = ""
    evidence: str = ""


@dataclass(slots=True)
class CompetitorAssessment:
    record_id: str
    source: str
    title: str
    overall_overlap: OverlapLevel
    dimensions: list[DimensionAssessment] = field(default_factory=list)
    adequate_review: bool | None = None
    recent_review: bool | None = None
    meaningful_new_information: bool | None = None
    confidence: float = 0.0
    evidence_text_available: bool = False
    rationale: str = ""
    reviewer: str = "AI_PROVISIONAL"

    @property
    def unresolved(self) -> bool:
        return (
            self.overall_overlap == OverlapLevel.UNRESOLVED
            or self.confidence < 0.80
            or not self.evidence_text_available
        )

    @property
    def fatal_redundancy(self) -> bool:
        return (
            not self.unresolved
            and self.overall_overlap == OverlapLevel.ESSENTIALLY_IDENTICAL
            and self.adequate_review is True
            and self.recent_review is True
            and self.meaningful_new_information is False
        )
