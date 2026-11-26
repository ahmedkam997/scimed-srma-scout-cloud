from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from scimed_scout.domain import SourceStatus


@dataclass(slots=True)
class SearchRecord:
    source: str
    record_id: str
    title: str
    url: str = ""
    year: int | None = None
    doi: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SearchResult:
    source: str
    query: str
    status: SourceStatus
    records: list[SearchRecord] = field(default_factory=list)
    total_count: int | None = None
    message: str = ""
    continuation: dict[str, Any] | None = None

    @property
    def safe_negative(self) -> bool:
        return self.status == SourceStatus.SEARCHED_NEGATIVE


class SourceClient(Protocol):
    name: str

    def search(self, query: str, *, limit: int = 20) -> SearchResult:
        ...
