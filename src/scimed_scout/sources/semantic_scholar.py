from __future__ import annotations

import os

from scimed_scout.domain import SourceStatus
from .base import SearchRecord, SearchResult
from .http import JsonHttpClient


class SemanticScholarSource:
    name = "Semantic Scholar"
    endpoint = "https://api.semanticscholar.org/graph/v1/paper/search"

    def __init__(self, http: JsonHttpClient | None = None, api_key: str | None = None):
        self.http = http or JsonHttpClient()
        self.api_key = api_key if api_key is not None else os.getenv("SEMANTIC_SCHOLAR_API_KEY", "")
        self._rate_limited = False

    def search(self, query: str, *, limit: int = 20) -> SearchResult:
        if self._rate_limited:
            return SearchResult(
                self.name, query, SourceStatus.ACCESS_FAILED,
                message="Semantic Scholar 429 earlier in this job; remaining queries skipped to respect API quota",
            )
        try:
            headers = {"x-api-key": self.api_key} if self.api_key else None
            data = self.http.get_json(
                self.endpoint,
                {
                    "query": query,
                    "limit": min(max(1, limit), 100),
                    "fields": "title,abstract,year,url,externalIds,publicationTypes,venue,authors",
                },
                headers=headers,
            )
            total = data.get("total")
            if total is None:
                return SearchResult(self.name, query, SourceStatus.PARTIAL, message="Semantic Scholar response missing total")
            total = int(total)
            if total == 0:
                return SearchResult(self.name, query, SourceStatus.SEARCHED_NEGATIVE, total_count=0)

            records: list[SearchRecord] = []
            for row in data.get("data") or []:
                paper_id = str(row.get("paperId") or "")
                if not paper_id:
                    continue
                external = row.get("externalIds") or {}
                doi = str(external.get("DOI") or "") if isinstance(external, dict) else ""
                records.append(
                    SearchRecord(
                        self.name,
                        paper_id,
                        str(row.get("title") or ""),
                        url=str(row.get("url") or f"https://www.semanticscholar.org/paper/{paper_id}"),
                        year=row.get("year") if isinstance(row.get("year"), int) else None,
                        doi=doi,
                        metadata=row,
                    )
                )
            return SearchResult(self.name, query, SourceStatus.SEARCHED_POSITIVE, records, total)
        except Exception as exc:
            if "429" in str(exc):
                self._rate_limited = True
            return SearchResult(self.name, query, SourceStatus.ACCESS_FAILED, message=str(exc))
