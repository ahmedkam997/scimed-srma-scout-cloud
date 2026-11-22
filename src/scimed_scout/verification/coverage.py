from __future__ import annotations

from dataclasses import dataclass, field

from scimed_scout.domain import SourceStatus
from scimed_scout.storage import SearchLogRecord

from .policy import VerificationPolicy


DEFINITIVE = {
    SourceStatus.SEARCHED_NEGATIVE,
    SourceStatus.SEARCHED_POSITIVE,
    SourceStatus.MANUAL_VERIFIED,
}


@dataclass(frozen=True, slots=True)
class VerificationCoverage:
    source_statuses: dict[str, SourceStatus]
    blockers: tuple[str, ...]
    warnings: tuple[str, ...] = ()

    @property
    def complete(self) -> bool:
        return not self.blockers


def evaluate_coverage(logs: list[SearchLogRecord], policy: VerificationPolicy) -> VerificationCoverage:
    statuses = {
        source: _aggregate([x.status for x in logs if x.source == source])
        for source in set(policy.literature_sources + policy.registry_sources + policy.pipeline_sources)
    }

    blockers: list[str] = []
    warnings: list[str] = []

    complete_literature = sum(statuses.get(name) in DEFINITIVE for name in policy.literature_sources)
    if complete_literature < policy.min_complete_literature_sources:
        blockers.append(
            f"TYPE-A: only {complete_literature} literature sources have conclusive search status; "
            f"{policy.min_complete_literature_sources} required"
        )

    if policy.require_prospero and statuses.get("PROSPERO") not in DEFINITIVE:
        blockers.append("TYPE-A: PROSPERO coverage is incomplete or unavailable")

    if policy.require_osf and statuses.get("OSF Registries") not in DEFINITIVE:
        blockers.append("TYPE-A: OSF registration coverage is incomplete or unavailable")

    pipeline_complete = any(statuses.get(name) in DEFINITIVE for name in policy.pipeline_sources)
    if policy.require_pipeline_source and not pipeline_complete:
        blockers.append("TYPE-A: required prospective/ongoing-study pipeline coverage is incomplete")
    elif not policy.require_pipeline_source and not pipeline_complete:
        warnings.append("Pipeline source coverage is incomplete, but this question type does not require it as a universal blocker")

    return VerificationCoverage(statuses, tuple(blockers), tuple(warnings))


def _aggregate(values: list[SourceStatus]) -> SourceStatus:
    if not values:
        return SourceStatus.NOT_SEARCHED
    if all(x == SourceStatus.ACCESS_FAILED for x in values):
        return SourceStatus.ACCESS_FAILED
    if any(x in {SourceStatus.ACCESS_FAILED, SourceStatus.PARTIAL, SourceStatus.NOT_SEARCHED} for x in values):
        return SourceStatus.PARTIAL
    if any(x == SourceStatus.SEARCHED_POSITIVE for x in values):
        return SourceStatus.SEARCHED_POSITIVE
    if any(x == SourceStatus.MANUAL_VERIFIED for x in values):
        return SourceStatus.MANUAL_VERIFIED
    if all(x == SourceStatus.SEARCHED_NEGATIVE for x in values):
        return SourceStatus.SEARCHED_NEGATIVE
    return SourceStatus.PARTIAL
