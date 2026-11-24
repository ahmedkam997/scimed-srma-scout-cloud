from __future__ import annotations

import os

from scimed_scout.domain import SourceStatus
from .base import SearchRecord, SearchResult
from .http import JsonHttpClient


class OpenAlexSource:
    name = "OpenAlex"
    endpoint = "https://api.openalex.org/works"

    def __init__(self, http: JsonHttpClient | None = None, api_key: str | None = None):
        self.http = http or JsonHttpClient()
        self.api_key = api_key if api_key is not None else os.getenv("OPENALEX_API_KEY", "")
        self._rate_limited = False

    def search(self, query: str, *, limit: int = 20) -> SearchResult:
        if self._rate_limited:
            return SearchResult(
                self.name, query, SourceStatus.ACCESS_FAILED,
                message="OpenAlex 429 earlier in this job; remaining queries skipped to respect API quota. Check OPENALEX_API_KEY quota.",
            )
        # OpenAlex's Nov 2026 API uses free personal keys to provide reliable
        # access. A worker without a key must not hammer the public endpoint
        # repeatedly, pretend the registry was searched or inflate latency.
        # Keep injected offline fixture clients usable for regression tests.
        if not self.api_key and self.http.loader is None:
            return SearchResult(
                self.name, query, SourceStatus.ACCESS_FAILED,
                message="OPENALEX_API_KEY is not configured for this worker; OpenAlex search not executed. Obtain the free key from openalex.org/settings/api. Other literature sources continue independently.",
            )
        try:
            data = self.http.get_json(
                self.endpoint, {
                    "search": query,
                    "per-page": min(max(1, limit), 100),
                    "api_key": self.api_key or None,
                },
            )
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
                metadata = dict(row)
                abstract = _abstract_from_inverted_index(row.get("abstract_inverted_index"))
                if abstract:
                    metadata["abstract"] = abstract
                records.append(SearchRecord(
                    self.name, rid, str(row.get("title") or ""), url=rid,
                    year=row.get("publication_year") if isinstance(row.get("publication_year"), int) else None,
                    doi=doi, metadata=metadata,
                ))
            return SearchResult(self.name, query, SourceStatus.SEARCHED_POSITIVE, records, total)
        except Exception as exc:
            if "429" in str(exc):
                self._rate_limited = True
            description=str(exc)
            if "429" in description:
                description += "; OpenAlex quota reached; no further requests will be made during this worker job."
            elif "401" in description or "403" in description:
                description += "; verify OPENALEX_API_KEY in GitHub Actions Secrets."
            return SearchResult(self.name, query, SourceStatus.ACCESS_FAILED, message=description)



def _abstract_from_inverted_index(index) -> str:
    if not isinstance(index, dict):
        return ""
    positions: list[tuple[int, str]] = []
    for word, raw_positions in index.items():
        if not isinstance(raw_positions, list):
            continue
        for pos in raw_positions:
            if isinstance(pos, int):
                positions.append((pos, str(word)))
    positions.sort(key=lambda item: item[0])
    return " ".join(word for _, word in positions)
