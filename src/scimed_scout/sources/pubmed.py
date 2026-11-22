from __future__ import annotations

from scimed_scout.domain import SourceStatus
from .base import SearchRecord, SearchResult
from .http import JsonHttpClient


class PubMedSource:
    name = "PubMed"
    base = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"

    def __init__(self, http: JsonHttpClient | None = None):
        self.http = http or JsonHttpClient()

    def search(self, query: str, *, limit: int = 20) -> SearchResult:
        try:
            data = self.http.get_json(self.base + "esearch.fcgi", {
                "db": "pubmed", "term": query, "retmode": "json", "retmax": max(0, limit), "sort": "pub date"
            })
            block = data.get("esearchresult") or {}
            if "count" not in block:
                return SearchResult(self.name, query, SourceStatus.PARTIAL, message="PubMed response missing count")
            total = int(block["count"])
            ids = [str(x) for x in block.get("idlist", [])]
            if total == 0:
                return SearchResult(self.name, query, SourceStatus.SEARCHED_NEGATIVE, total_count=0)
            records = [SearchRecord(self.name, pmid, title="", url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/") for pmid in ids]
            return SearchResult(self.name, query, SourceStatus.SEARCHED_POSITIVE, records, total)
        except Exception as exc:
            return SearchResult(self.name, query, SourceStatus.ACCESS_FAILED, message=str(exc))
