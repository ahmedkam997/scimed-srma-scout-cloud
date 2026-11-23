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
            records: dict[str, SearchRecord] = {}
            seen_tokens: set[str] = set()
            total: int | None = None
            token: str | None = None
            pages = 0
            exhausted = False
            for _ in range(3):
                params = {
                    "query.term": safe_query,
                    "pageSize": 100,
                    "countTotal": "true",
                }
                if token:
                    if token in seen_tokens:
                        break
                    seen_tokens.add(token)
                    params["pageToken"] = token
                data = self.http.get_json(self.endpoint, params)
                if not isinstance(data, dict) or data.get("totalCount") is None:
                    return SearchResult(
                        self.name, query, SourceStatus.PARTIAL,
                        list(records.values()), total,
                        message="ClinicalTrials.gov response missing totalCount",
                    )
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
                        continue
                    protocol = study.get("protocolSection") or {}
                    ident = protocol.get("identificationModule") or {}
                    nct = str(ident.get("nctId") or "").strip()
                    if not re.fullmatch(r"NCT\d{8}", nct):
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
            if total == 0 and exhausted:
                return SearchResult(
                    self.name, query, SourceStatus.SEARCHED_NEGATIVE, total_count=0,
                    message="ClinicalTrials.gov verified zero matching studies for scoped query",
                )
            complete = (
                exhausted and total is not None and total > 0
                and len(records) >= total
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
            return SearchResult(self.name, query, SourceStatus.ACCESS_FAILED, message=str(exc))

def _plain_terms(value: str) -> str:
    """Avoid sending unbalanced or operator-like PICO punctuation to v2 search."""
    text = str(value or "").replace("‐", " ").replace("‑", " ").replace("–", " ").replace("—", " ")
    text = re.sub(r"[^\w\s-]", " ", text, flags=re.UNICODE)
    words = text.split()
    while words and words[-1].casefold() in {"or", "and", "not"}:
        words.pop()
    return " ".join(words)[:350].strip()
