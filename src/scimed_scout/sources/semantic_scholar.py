from __future__ import annotations

import os
import time

from scimed_scout.domain import SourceStatus
from .base import SearchRecord, SearchResult
from .http import JsonHttpClient


class SemanticScholarSource:
    name = "Semantic Scholar"
    endpoint = "https://api.semanticscholar.org/graph/v1/paper/search"

    def __init__(self, http: JsonHttpClient | None = None, api_key: str | None = None, *, allow_keyless_probe: bool = True):
        self.http = http or JsonHttpClient()
        self.api_key = api_key if api_key is not None else os.getenv("SEMANTIC_SCHOLAR_API_KEY", "")
        self.allow_keyless_probe = allow_keyless_probe
        self._rate_limited = False
        self._last_request_started_at: float | None = None
        self._unauthenticated_probe_sent = False

    def search(self, query: str, *, limit: int = 20) -> SearchResult:
        if not self.api_key and not self.allow_keyless_probe:
            return SearchResult(
                self.name, query, SourceStatus.NOT_SEARCHED,
                message="Optional Semantic Scholar not searched: no personal API key; use independent literature sources. Not a negative result.",
            )
        if self._rate_limited:
            return SearchResult(
                self.name, query, SourceStatus.ACCESS_FAILED,
                message="Semantic Scholar 429 earlier in this job; remaining queries skipped to respect API quota",
            )
        # Anonymous requests share a crowded global quota. Limit a live,
        # unauthenticated worker to ONE exploratory probe per job. Subsequent
        # PICO queries are explicitly PARTIAL, never fabricated negatives.
        live_http = getattr(self.http,"loader",None) is None
        if live_http and not self.api_key and self._unauthenticated_probe_sent:
            return SearchResult(
                self.name, query, SourceStatus.PARTIAL,
                message="Semantic Scholar keyless shared quota: only one exploratory request per worker job. Configure SEMANTIC_SCHOLAR_API_KEY to run remaining queries.",
            )
        if live_http and self.api_key:
            # The published introductory personal-key limit is 1 request/s.
            # This instance persists across candidate verification in a job.
            if self._last_request_started_at is not None:
                pause = 1.1 - (time.monotonic() - self._last_request_started_at)
                if pause > 0:
                    time.sleep(pause)
            self._last_request_started_at = time.monotonic()
        if live_http and not self.api_key:
            self._unauthenticated_probe_sent = True
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
            description = str(exc)
            if self.api_key:
                description = description.replace(self.api_key, "[SECRET_REDACTED]")
            if "429" in description:
                description += "; shared quota or personal-key rate limit hit; requests halted for this worker job."
            return SearchResult(self.name, query, SourceStatus.ACCESS_FAILED, message=description)
