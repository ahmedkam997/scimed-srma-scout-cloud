from __future__ import annotations

from scimed_scout.domain import SourceStatus
from .base import SearchRecord, SearchResult
from .http import JsonHttpClient


class CrossrefSource:
    name = "Crossref"
    endpoint = "https://api.crossref.org/works"

    def __init__(self, http: JsonHttpClient | None = None, mailto: str = ""):
        self.http = http or JsonHttpClient()
        self.mailto = mailto

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
            return SearchResult(self.name, query, SourceStatus.SEARCHED_POSITIVE, records, total)
        except Exception as exc:
            return SearchResult(self.name, query, SourceStatus.ACCESS_FAILED, message=str(exc))


def _crossref_year(row: dict) -> int | None:
    for key in ("published-print", "published-online", "issued", "created"):
        block = row.get(key) or {}
        parts = block.get("date-parts") if isinstance(block, dict) else None
        if isinstance(parts, list) and parts and isinstance(parts[0], list) and parts[0]:
            value = parts[0][0]
            if isinstance(value, int):
                return value
    return None
