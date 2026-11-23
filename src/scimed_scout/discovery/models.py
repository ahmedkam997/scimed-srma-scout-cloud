from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from scimed_scout.domain import CandidateStatus
from scimed_scout.ranking import RankingResult
from scimed_scout.verification.coverage import VerificationCoverage


@dataclass(frozen=True, slots=True)
class DiscoveryEvidenceSnapshot:
    raw_primary_records: int
    unique_primary_study_candidates: int
    primary_sources_with_hits: int
    primary_source_names: tuple[str, ...]


@dataclass(slots=True)
class DiscoveryCandidateResult:
    candidate_id: str
    ranking_score: float
    coverage: VerificationCoverage
    evidence: DiscoveryEvidenceSnapshot
    pending: list[str] = field(default_factory=list)
    decision: str = "PENDING"
    candidate_status: CandidateStatus = CandidateStatus.DEEP_VERIFYING
    final_gate_result: dict[str, Any] | None = None


@dataclass(slots=True)
class DiscoveryRunResult:
    project_id: str
    ranked: list[RankingResult]
    verified: list[DiscoveryCandidateResult]
    final_option_candidate_ids: list[str] = field(default_factory=list)
    qualified_option_candidate_ids: list[str] = field(default_factory=list)
    desired_options: int = 3
    duplicate_topics_skipped: list[dict[str, str]] = field(default_factory=list)
    bibliographic_preflight_summary: dict[str, Any] = field(default_factory=dict)
    adaptive_deep_checks_used: int = 0
    adaptive_checks_skipped_reason: str = ""
