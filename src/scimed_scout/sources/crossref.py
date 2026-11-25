from __future__ import annotations

import os

from scimed_scout.domain import SourceStatus
from .base import SearchRecord, SearchResult
from .http import JsonHttpClient


class CrossrefSource:
    name = "Crossref"
    endpoint = "https://api.crossref.org/works"

    def __init__(self, http: JsonHttpClient | None = None, mailto: str = ""):
        self.mailto = mailto or os.getenv("SCIMED_CONTACT_EMAIL", "").strip()
        self.http = http or JsonHttpClient(
            service="crossref", min_interval=1.2 if not self.mailto else 0.5,
            retry_rate_limit=True, retries=2, delay=1.0,
        )

    def search(self, query: str, *, limit: int = 20) -> SearchResult:
        try:
            data = self.http.get_json(
                self.endpoint,
                {
                    "query.bibliographic": query,
                    "rows": min(max(1, limit), 100),
                    "mailto": self.mailto or None,
                },
            )
            message = data.get("message") or {}
            total = message.get("total-results")
            if total is None:
                return SearchResult(self.name, query, SourceStatus.PARTIAL, message="Crossref response missing total-results")
            total = int(total)
            if total == 0:
                return SearchResult(self.name, query, SourceStatus.SEARCHED_NEGATIVE, total_count=0)

            records: list[SearchRecord] = []
            for row in message.get("items") or []:
                doi = str(row.get("DOI") or "")
                title_value = row.get("title") or []
                title = str(title_value[0]) if isinstance(title_value, list) and title_value else str(title_value or "")
                rid = doi or str(row.get("URL") or title)
                if not rid:
                    continue
                year = _crossref_year(row)
                records.append(
                    SearchRecord(
                        self.name,
                        rid,
                        title,
                        url=str(row.get("URL") or (f"https://doi.org/{doi}" if doi else "")),
                        year=year,
                        doi=doi,
                        metadata=row,
                    )
                )
            return SearchResult(self.name, query, SourceStatus.SEARCHED_POSITIVE if records and all(r.title.strip() for r in records) and len(records)<=total else SourceStatus.PARTIAL, records, total)
        except Exception as exc:
            message = str(exc)
            if self.mailto:
                message = message.replace(self.mailto, "[CONTACT_REDACTED]")
            return SearchResult(self.name, query, SourceStatus.ACCESS_FAILED, message=message)


def _crossref_year(row: dict) -> int | None:
    for key in ("published-print", "published-online", "issued", "created"):
        block = row.get(key) or {}
        parts = block.get("date-parts") if isinstance(block, dict) else None
        if isinstance(parts, list) and parts and isinstance(parts[0], list) and parts[0]:
            value = parts[0][0]
            if isinstance(value, int):
                return value
    return None
