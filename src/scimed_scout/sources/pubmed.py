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

            summary_rows = {}
            if ids:
                try:
                    summary = self.http.get_json(self.base + "esummary.fcgi", {
                        "db": "pubmed",
                        "id": ",".join(ids),
                        "retmode": "json",
                    })
                    result = summary.get("result") or {}
                    summary_rows = {
                        pmid: row for pmid, row in result.items()
                        if pmid != "uids" and isinstance(row, dict)
                    }
                except Exception:
                    summary_rows = {}

            records: list[SearchRecord] = []
            for pmid in ids:
                row = summary_rows.get(pmid, {})
                title = str(row.get("title") or "")
                pubdate = str(row.get("pubdate") or "")
                year = int(pubdate[:4]) if len(pubdate) >= 4 and pubdate[:4].isdigit() else None
                article_ids = row.get("articleids") or []
                doi = ""
                if isinstance(article_ids, list):
                    for item in article_ids:
                        if isinstance(item, dict) and str(item.get("idtype") or "").lower() == "doi":
                            doi = str(item.get("value") or "")
                            break
                records.append(
                    SearchRecord(
                        self.name,
                        pmid,
                        title=title,
                        url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                        year=year,
                        doi=doi,
                        metadata=row,
                    )
                )
            status = SourceStatus.SEARCHED_POSITIVE if records or total > 0 else SourceStatus.PARTIAL
            return SearchResult(self.name, query, status, records, total)
        except Exception as exc:
            return SearchResult(self.name, query, SourceStatus.ACCESS_FAILED, message=str(exc))
