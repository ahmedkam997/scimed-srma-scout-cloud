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

    def search_recovery(self, query: str, *, limit: int = 20) -> SearchResult:
        return self._search(query,limit=limit,page_size=500)

    def search(self, query: str, *, limit: int = 20) -> SearchResult:
        return self._search(query,limit=limit,page_size=100)

    def _search(self, query: str, *, limit: int, page_size: int) -> SearchResult:
        # Unbalanced parentheses and truncated PICO fragments frequently cause
        # ClinicalTrials.gov search-expression HTTP 400 responses. Submit
        # plain search terms, preserving the original query in the audit log.
        safe_query = _plain_terms(query)
        if not safe_query:
            return SearchResult(
                self.name, query, SourceStatus.PARTIAL,
                message="No usable ClinicalTrials.gov search terms",
            )
        records: dict[str, SearchRecord] = {}
        total: int | None = None
        try:
            seen_tokens: set[str] = set()
            duplicate_count=0
            malformed_count=0
            token: str | None = None
            pages = 0
            exhausted = False
            for _ in range(3):
                params = {
                    "query.term": safe_query,
                    "pageSize": page_size,
                }
                # ClinicalTrials.gov v2 includes totalCount on the first
                # page when countTotal=true. Later pages may omit it.
                if not token:
                    params["countTotal"] = "true"
                if token:
                    if token in seen_tokens:
                        break
                    seen_tokens.add(token)
                    params["pageToken"] = token
                data = self.http.get_json(self.endpoint, params)
                if not isinstance(data, dict):
                    return SearchResult(
                        self.name, query, SourceStatus.PARTIAL,
                        list(records.values()), total,
                        message="ClinicalTrials.gov response is not a JSON object",
                    )
                if total is None and data.get("totalCount") is None:
                    return SearchResult(
                        self.name, query, SourceStatus.PARTIAL,
                        list(records.values()), total,
                        message="ClinicalTrials.gov first page missing totalCount",
                    )
                if data.get("totalCount") is not None:
                    current_total = int(data["totalCount"])
                    if current_total < 0:
                        raise ValueError("Negative ClinicalTrials.gov totalCount")
                    if total is None:
                        total = current_total
                    elif total != current_total:
                        return SearchResult(
                            self.name, query, SourceStatus.PARTIAL,
                            list(records.values()), max(total, current_total),
                            message="ClinicalTrials.gov result count changed while paginating",
                        )
                studies = data.get("studies")
                if not isinstance(studies, list):
                    return SearchResult(
                        self.name, query, SourceStatus.PARTIAL,
                        list(records.values()), total,
                        message="ClinicalTrials.gov response missing studies list",
                    )
                for study in studies:
                    if not isinstance(study, dict):
                        malformed_count+=1
                        continue
                    protocol = study.get("protocolSection") or {}
                    ident = protocol.get("identificationModule") or {}
                    nct = str(ident.get("nctId") or "").strip()
                    if not re.fullmatch(r"NCT\d{8}", nct):
                        malformed_count+=1
                        continue
                    if nct in records:
                        duplicate_count+=1
                        continue
                    records[nct] = SearchRecord(
                        self.name, nct, str(ident.get("briefTitle") or ident.get("officialTitle") or ""),
                        url=f"https://clinicaltrials.gov/study/{nct}", metadata=study,
                    )
                pages += 1
                token = data.get("nextPageToken")
                if not token:
                    exhausted = True
                    break
            if total == 0 and exhausted and not records and not malformed_count:
                return SearchResult(
                    self.name, query, SourceStatus.SEARCHED_NEGATIVE, total_count=0,
                    message="ClinicalTrials.gov verified zero matching studies for scoped query",
                )
            complete = (
                exhausted and total is not None and total > 0
                and len(records) == total and not malformed_count and not duplicate_count
            )
            return SearchResult(
                self.name, query,
                SourceStatus.SEARCHED_POSITIVE if complete else SourceStatus.PARTIAL,
                list(records.values()), total,
                message=(
                    f"ClinicalTrials.gov query: {safe_query}; retrieved={len(records)}; "
                    f"total={total}; pages={pages}; "
                    + ("all API pages retrieved" if complete else "additional pages or unresolved records remain")
                ),
            )
        except Exception as exc:
            return SearchResult(self.name, query, SourceStatus.PARTIAL if records else SourceStatus.ACCESS_FAILED, list(records.values()),total,message=str(exc))

def _plain_terms(value: str) -> str:
    """Avoid sending unbalanced or operator-like PICO punctuation to v2 search."""
    text = str(value or "").replace("‐", " ").replace("‑", " ").replace("–", " ").replace("—", " ")
    text = re.sub(r"[^\w\s-]", " ", text, flags=re.UNICODE)
    words = text.split()
    while words and words[-1].casefold() in {"or", "and", "not"}:
        words.pop()
    return " ".join(words)[:350].strip()
