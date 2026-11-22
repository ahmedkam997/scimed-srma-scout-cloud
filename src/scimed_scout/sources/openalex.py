from __future__ import annotations

from scimed_scout.domain import SourceStatus
from .base import SearchRecord, SearchResult
from .http import JsonHttpClient


class OpenAlexSource:
    name = "OpenAlex"
    endpoint = "https://api.openalex.org/works"

    def __init__(self, http: JsonHttpClient | None = None):
        self.http = http or JsonHttpClient()

    def search(self, query: str, *, limit: int = 20) -> SearchResult:
        try:
            data = self.http.get_json(self.endpoint, {"search": query, "per-page": min(max(1, limit), 100)})
            meta = data.get("meta") or {}
            count = meta.get("count")
            if count is None:
                return SearchResult(self.name, query, SourceStatus.PARTIAL, message="OpenAlex response missing meta.count")
            total = int(count)
            if total == 0:
                return SearchResult(self.name, query, SourceStatus.SEARCHED_NEGATIVE, total_count=0)
            records = []
            for row in data.get("results") or []:
                rid = str(row.get("id") or "")
                if not rid:
                    continue
                doi = str(row.get("doi") or "").removeprefix("https://doi.org/")
                records.append(SearchRecord(
                    self.name, rid, str(row.get("title") or ""), url=rid,
                    year=row.get("publication_year") if isinstance(row.get("publication_year"), int) else None,
                    doi=doi, metadata=row,
                ))
            return SearchResult(self.name, query, SourceStatus.SEARCHED_POSITIVE, records, total)
        except Exception as exc:
            return SearchResult(self.name, query, SourceStatus.ACCESS_FAILED, message=str(exc))
