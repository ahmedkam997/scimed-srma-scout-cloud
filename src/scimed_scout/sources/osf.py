from __future__ import annotations

from scimed_scout.domain import SourceStatus
from .base import SearchRecord, SearchResult
from .http import JsonHttpClient


class OSFRegistrationsSource:
    name = "OSF Registries"
    endpoint = "https://api.osf.io/v2/registrations/"

    def __init__(self, http: JsonHttpClient | None = None):
        self.http = http or JsonHttpClient()

    def search(self, query: str, *, limit: int = 20) -> SearchResult:
        """Search public registration metadata by title.

        A zero-result API response is deliberately PARTIAL rather than negative.
        OSF's public search surface can expose content beyond this metadata filter,
        so an empty title-filter result cannot establish absence of a competitor.
        """
        try:
            data = self.http.get_json(
                self.endpoint,
                {"filter[title]": query, "page[size]": min(max(1, limit), 100)},
            )
            rows = data.get("data")
            if not isinstance(rows, list):
                return SearchResult(self.name, query, SourceStatus.PARTIAL, message="OSF response missing registration data list")

            records: list[SearchRecord] = []
            for row in rows:
                rid = str(row.get("id") or "")
                attrs = row.get("attributes") or {}
                if not rid:
                    continue
                records.append(
                    SearchRecord(
                        self.name,
                        rid,
                        str(attrs.get("title") or ""),
                        url=str(((row.get("links") or {}).get("html")) or f"https://osf.io/{rid}/"),
                        metadata=row,
                    )
                )

            if not records:
                return SearchResult(
                    self.name,
                    query,
                    SourceStatus.PARTIAL,
                    total_count=0,
                    message="No title-filter hits. Manual OSF Search or broader registration search remains required before a negative novelty inference.",
                )
            return SearchResult(self.name, query, SourceStatus.SEARCHED_POSITIVE, records, len(records))
        except Exception as exc:
            return SearchResult(self.name, query, SourceStatus.ACCESS_FAILED, message=str(exc))
