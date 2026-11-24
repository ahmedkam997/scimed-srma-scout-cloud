from __future__ import annotations

from scimed_scout.domain import SourceStatus
from .base import SearchRecord, SearchResult
from .http import JsonHttpClient


class EuropePMCSource:
    name = "Europe PMC"
    endpoint = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"

    def __init__(self, http: JsonHttpClient | None = None):
        self.http = http or JsonHttpClient(timeout=28.0, retries=1, delay=2.0, service="europe_pmc", min_interval=0.5)

    def search(self, query: str, *, limit: int = 20) -> SearchResult:
        try:
            data = self.http.get_json(self.endpoint, {"query": query, "format": "json", "pageSize": max(1, limit), "resultType": "core"})
            hit_count = data.get("hitCount")
            if hit_count is None:
                return SearchResult(self.name, query, SourceStatus.PARTIAL, message="Europe PMC response missing hitCount")
            total = int(hit_count)
            if total == 0:
                return SearchResult(self.name, query, SourceStatus.SEARCHED_NEGATIVE, total_count=0)
            raw_records = ((data.get("resultList") or {}).get("result") or [])
            records = []
            for row in raw_records:
                rid = str(row.get("pmid") or row.get("pmcid") or row.get("id") or "")
                if not rid:
                    continue
                records.append(SearchRecord(
                    self.name, rid, str(row.get("title") or ""),
                    url=(f"https://europepmc.org/article/MED/{row['pmid']}" if row.get("pmid") else ""),
                    year=int(row["pubYear"]) if str(row.get("pubYear", "")).isdigit() else None,
                    doi=str(row.get("doi") or ""), metadata=row,
                ))
            status = SourceStatus.SEARCHED_POSITIVE if records or total > 0 else SourceStatus.PARTIAL
            return SearchResult(self.name, query, status, records, total)
        except Exception as exc:
            return SearchResult(self.name, query, SourceStatus.ACCESS_FAILED, message=str(exc))
