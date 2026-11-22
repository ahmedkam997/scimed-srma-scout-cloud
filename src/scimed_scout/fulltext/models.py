from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class FullTextStatus(StrEnum):
    ACQUIRED = "ACQUIRED"
    ALREADY_PRESENT = "ALREADY_PRESENT"
    MANUAL_ATTACHED = "MANUAL_ATTACHED"
    NOT_AVAILABLE = "NOT_AVAILABLE"
    NO_PMCID = "NO_PMCID"
    ACCESS_FAILED = "ACCESS_FAILED"
    INVALID_CONTENT = "INVALID_CONTENT"


class FullTextPurpose(StrEnum):
    ELIGIBILITY = "ELIGIBILITY"
    SYNTHESIS = "SYNTHESIS"
    ALL = "ALL"


@dataclass(frozen=True, slots=True)
class FullTextChunk:
    chunk_id: str
    ordinal: int
    section: str
    text: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "ordinal": self.ordinal,
            "section": self.section,
            "text": self.text,
        }


@dataclass(slots=True)
class FullTextFetchResult:
    status: FullTextStatus
    pmcid: str = ""
    source: str = ""
    source_url: str = ""
    full_text: str = ""
    chunks: list[FullTextChunk] = field(default_factory=list)
    message: str = ""


@dataclass(frozen=True, slots=True)
class FullTextAcquisitionSummary:
    candidate_id: str
    purpose: str
    records_considered: int
    acquired: int
    already_present: int
    not_available: int
    no_pmcid: int
    access_failed: int
    invalid_content: int
