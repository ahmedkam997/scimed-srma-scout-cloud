from __future__ import annotations
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

class SourceStatus(StrEnum):
    SEARCHED_NEGATIVE = "SEARCHED_NEGATIVE"
    SEARCHED_POSITIVE = "SEARCHED_POSITIVE"
    PARTIAL = "PARTIAL"
    ACCESS_FAILED = "ACCESS_FAILED"
    NOT_SEARCHED = "NOT_SEARCHED"
    MANUAL_VERIFIED = "MANUAL_VERIFIED"

class CandidateStatus(StrEnum):
    DISCOVERED = "DISCOVERED"
    SHORTLISTED = "SHORTLISTED"
    DEEP_VERIFYING = "DEEP_VERIFYING"
    PROVISIONAL_BACKUP = "PROVISIONAL_BACKUP"
    REJECTED = "REJECTED"
    QUALIFIED = "QUALIFIED"

@dataclass(slots=True)
class SourceAudit:
    source: str
    status: SourceStatus
    query: str = ""
    searched_at: str = ""
    result_count: int | None = None
    fallback_used: str = ""
    message: str = ""

    @property
    def supports_negative_inference(self) -> bool:
        return self.status in {SourceStatus.SEARCHED_NEGATIVE, SourceStatus.SEARCHED_POSITIVE, SourceStatus.MANUAL_VERIFIED}

@dataclass(slots=True)
class CandidateEvidence:
    candidate_id: str
    title: str
    specialty: str
    verified_independent_rcts: int = 0
    verified_usable_rcts: int = 0
    principal_outcome_rcts: int = 0
    unresolved_type_a: list[str] = field(default_factory=list)
    sources: list[SourceAudit] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
