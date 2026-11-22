from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class EvidenceScope(StrEnum):
    TITLE_ABSTRACT = "TITLE_ABSTRACT"
    FULL_TEXT = "FULL_TEXT"
    SUPPLEMENT = "SUPPLEMENT"
    MANUAL = "MANUAL"


@dataclass(slots=True)
class ExtractedOutcome:
    outcome_name: str
    outcome_type: str
    follow_up: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    signals: dict[str, Any] = field(default_factory=dict)
    overall_confidence: float = 0.0
    unresolved_fields: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class StudySynthesisExtraction:
    study_id: str
    source_record_id: str
    evidence_scope: EvidenceScope
    outcomes: list[ExtractedOutcome] = field(default_factory=list)
    no_data_reason: str = ""
    reviewer: str = "AI_PROVISIONAL"
