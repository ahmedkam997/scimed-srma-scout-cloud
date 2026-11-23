from __future__ import annotations

import re

from scimed_scout.domain import SourceStatus
from .base import SearchRecord, SearchResult
from .http import JsonHttpClient


class ClinicalTrialsGovSource:
    name = "ClinicalTrials.gov"
    endpoint = "https://clinicaltrials.gov/api/v2/studies"

    def __init__(self, http: JsonHttpClient | None = None):
        self.http = http or JsonHttpClient()

    def search(self, query: str, *, limit: int = 20) -> SearchResult:
        # Unbalanced parentheses and truncated PICO fragments frequently cause
        # ClinicalTrials.gov search-expression HTTP 400 responses. Submit
        # plain search terms, preserving the original query in the audit log.
        safe_query = _plain_terms(query)
        if not safe_query:
            return SearchResult(
                self.name, query, SourceStatus.PARTIAL,
                message="No usable ClinicalTrials.gov search terms",
            )
        try:
            data = self.http.get_json(self.endpoint, {
                "query.term": safe_query,
                "pageSize": min(max(1, int(limit)), 100),
                "countTotal": "true",
            })
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
            # A returned first page is not a fully searched registry when
            # the API reports more studies than we retrieved.
            complete = len(records) >= total
            return SearchResult(
                self.name, query,
                SourceStatus.SEARCHED_POSITIVE if complete else SourceStatus.PARTIAL,
                records, total,
                message=(
                    f"ClinicalTrials.gov query: {safe_query}; retrieved={len(records)}; "
                    f"total={total}; "
                    + ("complete query page" if complete else "additional pages remain")
                ),
            )
        except Exception as exc:
            return SearchResult(self.name, query, SourceStatus.ACCESS_FAILED, message=str(exc))

def _plain_terms(value: str) -> str:
    """Avoid sending unbalanced or operator-like PICO punctuation to v2 search."""
    text = str(value or "").replace("‐", " ").replace("‑", " ").replace("–", " ").replace("—", " ")
    text = re.sub(r"[^\\w\\s-]", " ", text, flags=re.UNICODE)
    words = text.split()
    while words and words[-1].casefold() in {"or", "and", "not"}:
        words.pop()
    return " ".join(words)[:350].strip()
