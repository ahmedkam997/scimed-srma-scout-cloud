from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from scimed_scout.domain import SourceStatus


DEFINITIVE = {
    SourceStatus.SEARCHED_NEGATIVE,
    SourceStatus.SEARCHED_POSITIVE,
    SourceStatus.MANUAL_VERIFIED,
}


@dataclass(slots=True)
class SearchLogEntry:
    source: str
    query: str
    status: SourceStatus
    result_count: int | None = None
    searched_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    fallback_used: str = ""
    message: str = ""


@dataclass(slots=True)
class CoverageAudit:
    entries: list[SearchLogEntry] = field(default_factory=list)

    def source_status(self, source: str) -> SourceStatus:
        matches = [entry.status for entry in self.entries if entry.source == source]
        if not matches:
            return SourceStatus.NOT_SEARCHED
        if SourceStatus.PARTIAL in matches or SourceStatus.ACCESS_FAILED in matches:
            if any(status in DEFINITIVE for status in matches):
                return SourceStatus.PARTIAL
            if all(status == SourceStatus.ACCESS_FAILED for status in matches):
                return SourceStatus.ACCESS_FAILED
            return SourceStatus.PARTIAL
        if SourceStatus.SEARCHED_POSITIVE in matches:
            return SourceStatus.SEARCHED_POSITIVE
        if SourceStatus.MANUAL_VERIFIED in matches:
            return SourceStatus.MANUAL_VERIFIED
        if all(status == SourceStatus.SEARCHED_NEGATIVE for status in matches):
            return SourceStatus.SEARCHED_NEGATIVE
        return SourceStatus.PARTIAL

    def blockers(self, *, additional_protocol_source_required: bool = False) -> list[str]:
        blockers: list[str] = []
        literature_sources = ["PubMed", "Europe PMC", "OpenAlex", "Crossref", "Semantic Scholar"]
        complete_literature = sum(self.source_status(name) in DEFINITIVE for name in literature_sources)
        if complete_literature < 2:
            blockers.append("TYPE-A: fewer than two independent published-literature sources have complete search status")

        if self.source_status("PROSPERO") not in DEFINITIVE:
            blockers.append("TYPE-A: PROSPERO coverage is incomplete or unavailable")

        if self.source_status("OSF Registries") not in DEFINITIVE:
            blockers.append("TYPE-A: OSF registration coverage is incomplete or unavailable")

        if self.source_status("ClinicalTrials.gov") not in DEFINITIVE:
            blockers.append("TYPE-A: ClinicalTrials.gov coverage is incomplete or unavailable")

        if additional_protocol_source_required:
            extra = ["INPLASY", "Research Registry", "protocols.io", "Cochrane Protocols", "JBI"]
            if not any(self.source_status(name) in DEFINITIVE for name in extra):
                blockers.append("TYPE-A: no additional protocol source has complete status despite being required")

        return blockers

    def novelty_clearance(self, *, additional_protocol_source_required: bool = False) -> bool:
        return not self.blockers(additional_protocol_source_required=additional_protocol_source_required)
