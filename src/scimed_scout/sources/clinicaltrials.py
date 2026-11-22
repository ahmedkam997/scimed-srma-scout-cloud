from __future__ import annotations

from scimed_scout.domain import SourceStatus
from .base import SearchRecord, SearchResult
from .http import JsonHttpClient


class ClinicalTrialsGovSource:
    name = "ClinicalTrials.gov"
    endpoint = "https://clinicaltrials.gov/api/v2/studies"

    def __init__(self, http: JsonHttpClient | None = None):
        self.http = http or JsonHttpClient()

    def search(self, query: str, *, limit: int = 20) -> SearchResult:
        try:
            data = self.http.get_json(self.endpoint, {"query.term": query, "pageSize": min(max(1, limit), 100), "countTotal": "true"})
            total = data.get("totalCount")
            studies = data.get("studies") or []
            if total is None:
                return SearchResult(self.name, query, SourceStatus.PARTIAL, message="ClinicalTrials.gov response missing totalCount")
            total = int(total)
            if total == 0:
                return SearchResult(self.name, query, SourceStatus.SEARCHED_NEGATIVE, total_count=0)
            records = []
            for study in studies:
                protocol = study.get("protocolSection") or {}
                ident = protocol.get("identificationModule") or {}
                nct = str(ident.get("nctId") or "")
                if not nct:
                    continue
                records.append(SearchRecord(
                    self.name, nct, str(ident.get("briefTitle") or ident.get("officialTitle") or ""),
                    url=f"https://clinicaltrials.gov/study/{nct}", metadata=study,
                ))
            return SearchResult(self.name, query, SourceStatus.SEARCHED_POSITIVE, records, total)
        except Exception as exc:
            return SearchResult(self.name, query, SourceStatus.ACCESS_FAILED, message=str(exc))
