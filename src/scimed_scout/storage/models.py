from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from scimed_scout.domain import CandidateStatus, SourceStatus


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class ProjectRecord:
    project_id: str
    specialty: str
    question_type: str = ""
    stage: str = "NEW"
    status: str = "ACTIVE"
    progress: int = 0
    message: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)


@dataclass(slots=True)
class CandidateRecord:
    candidate_id: str
    project_id: str
    title: str
    specialty: str
    question_type: str = ""
    review_question: str = ""
    population: str = ""
    intervention_exposure_index_test: str = ""
    comparator_reference: str = ""
    outcomes: list[str] = field(default_factory=list)
    eligible_designs: list[str] = field(default_factory=list)
    rationale: str = ""
    novelty_hypothesis: str = ""
    search_terms: list[str] = field(default_factory=list)
    status: CandidateStatus = CandidateStatus.DISCOVERED
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)


@dataclass(slots=True)
class SearchLogRecord:
    project_id: str
    candidate_id: str
    source: str
    query: str
    status: SourceStatus
    result_count: int | None = None
    searched_at: str = field(default_factory=utc_now)
    fallback_used: str = ""
    message: str = ""


@dataclass(slots=True)
class DecisionRecord:
    decision_id: str
    project_id: str
    candidate_id: str
    decision: str
    stage: str
    reason: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now)
