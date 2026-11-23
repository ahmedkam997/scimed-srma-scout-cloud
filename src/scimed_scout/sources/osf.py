from __future__ import annotations

import re
from urllib.parse import urlsplit

from scimed_scout.domain import SourceStatus
from .base import SearchRecord, SearchResult
from .http import JsonHttpClient


STOP = {
    "a", "an", "and", "or", "the", "of", "in", "to", "with", "for",
    "vs", "versus", "among", "on", "after", "before", "patients",
    "patient", "adult", "adults", "using", "effect", "effects", "study",
    "diagnostic", "accuracy", "systematic", "review", "meta", "analysis",
}


def _focus_query(query: str) -> str:
    """Reduce a long PICO sentence to a reproducible registry keyword query."""
    terms = re.findall(r"[a-z0-9\u0600-\u06ff]+", str(query or "").casefold())
    useful = [term for term in terms if len(term) > 2 and term not in STOP]
    return " ".join(useful[:4]) or " ".join(terms[:3])


def _safe_next(url: str, host: str, path_prefix: str) -> bool:
    try:
        value = urlsplit(url)
        return value.scheme == "https" and value.hostname == host and value.path.startswith(path_prefix)
    except (ValueError, TypeError):
        return False


def _literal(item: object) -> str:
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        return str(item.get("@value") or item.get("@id") or "")
    if isinstance(item, list):
        return " ".join(_literal(part) for part in item[:2] if part)
    return ""


class OSFRegistrationsSource:
    """Public OSF Trove full-metadata search with official OSF v2 API fallback.

    Trove searches both title and description, unlike OSF v2's title filter.
    Every incomplete page search stays PARTIAL and is never a negative result.
    """

    name = "OSF Registries"
    trove = "https://share.osf.io/trove/index-card-search"
    endpoint = "https://api.osf.io/v2/registrations/"

    def __init__(self, http: JsonHttpClient | None = None, *, max_pages: int = 4):
        self.http = http or JsonHttpClient()
        self.max_pages = max(1, min(5, int(max_pages)))

    def search(self, query: str, *, limit: int = 20) -> SearchResult:
        focus = _focus_query(query)
        if not focus:
            return SearchResult(self.name, query, SourceStatus.PARTIAL, message="No suitable OSF search terms")
        try:
            return self._search_trove(query, focus, limit)
        except (RuntimeError, ValueError, TypeError, KeyError) as exc:
            try:
                fallback = self._search_v2(query, focus, limit)
            except (RuntimeError, ValueError, TypeError, KeyError) as second:
                return SearchResult(
                    self.name, query, SourceStatus.ACCESS_FAILED,
                    message=(f"OSF Trove unavailable ({type(exc).__name__}); "
                             f"OSF v2 unavailable ({type(second).__name__}); no negative inference."),
                )
            return SearchResult(
                self.name, query,
                SourceStatus.PARTIAL, fallback.records, fallback.total_count,
                message=(f"Trove unavailable ({type(exc).__name__}); "
                         f"OSF v2 title-filter fallback. {fallback.message}"),
            )

    def _search_trove(self, original: str, focus: str, limit: int) -> SearchResult:
        size = min(50, max(1, int(limit)))
        params = {
            "cardSearchText[title,description]": focus,
            "cardSearchFilter[resourceType]": "Registration",
            "page[size]": size,
            "acceptMediatype": "application/vnd.api+json",
        }
        url = self.trove
        records: dict[str, SearchRecord] = {}
        total: int | None = None
        pages = 0
        remaining = True
        for page in range(self.max_pages):
            if page and not _safe_next(url, "share.osf.io", "/trove/index-card-search"):
                return SearchResult(
                    self.name, original, SourceStatus.PARTIAL, list(records.values()), total,
                    message="OSF Trove supplied an untrusted next-page URL; stopped safely with partial records.",
                )
            try:
                if page:
                    obj = self.http.get_json(url, headers={"Accept": "application/vnd.api+json"})
                else:
                    obj = self.http.get_json(url, params, headers={"Accept": "application/vnd.api+json"})
            except Exception:
                if records:
                    return SearchResult(
                        self.name, original, SourceStatus.PARTIAL, list(records.values()), total,
                        message=f"OSF Trove page {page + 1} could not be retrieved; kept prior pages.",
                    )
                raise
            root = obj.get("data")
            included = obj.get("included")
            if not isinstance(root, dict) or not isinstance(included, list):
                raise ValueError("OSF Trove JSON:API response has unexpected structure")
            data = (root.get("relationships") or {}).get("searchResultPage") or {}
            page_results = data.get("data")
            if not isinstance(page_results, list):
                raise ValueError("OSF Trove search result page is missing")
            raw_total = (root.get("attributes") or {}).get("totalResultCount")
            if isinstance(raw_total, int):
                total = raw_total
            index_cards = {
                str(item.get("id") or ""): item
                for item in included if isinstance(item, dict) and item.get("type") == "index-card"
            }
            search_results = {
                str(item.get("id") or ""): item
                for item in included if isinstance(item, dict) and item.get("type") == "search-result"
            }

            for entry in page_results:
                if not isinstance(entry, dict):
                    continue
                item = search_results.get(str(entry.get("id") or ""), entry)
                card_pointer = (((item.get("relationships") or {}).get("indexCard") or {}).get("data") or {})
                card = index_cards.get(str(card_pointer.get("id") or ""), {})
                attrs = card.get("attributes") or {}
                metadata = attrs.get("resourceMetadata") or {}
                if not isinstance(metadata, dict):
                    continue
                title = _literal(metadata.get("title")).strip()
                if not title:
                    continue
                original_url = _literal(metadata.get("@id") or attrs.get("resourceIdentifier"))
                candidates = re.findall(r"https://osf\.io/([a-z0-9]+)/?", original_url, re.IGNORECASE)
                rid = candidates[0].lower() if candidates else str(card.get("id") or "")
                if not rid:
                    continue
                description = _literal(metadata.get("description"))[:2400]
                records[rid] = SearchRecord(
                    self.name, rid, title=title,
                    url=f"https://osf.io/{rid}/" if candidates else "",
                    metadata={"abstract": description, "trove_card_id": str(card.get("id") or ""),
                              "registry_search": "OSF Trove title+description"},
                )
            pages += 1
            next_link = (data.get("links") or {}).get("next")
            url = (next_link.get("href") if isinstance(next_link, dict) else next_link) or ""
            remaining = bool(url)
            if not remaining or (total is not None and len(records) >= total):
                break

        # Trove's filtered, indexed metadata is not a guarantee of global
        # negative coverage, even if the index reports zero results.
        if not records:
            return SearchResult(
                self.name, original, SourceStatus.PARTIAL, [], total,
                message=f"OSF Trove title/description query '{focus}': no matches in indexed public registrations. Manual broader check required.",
            )
        complete = bool(total is not None and len(records) >= total and not remaining)
        return SearchResult(
            self.name, original, SourceStatus.SEARCHED_POSITIVE if complete else SourceStatus.PARTIAL,
            list(records.values()), total,
            message=f"OSF Trove query '{focus}': {len(records)} registration matches, {pages} page(s); "
                    + ("all indexed query matches retrieved" if complete else "more indexed matches remain; partial"),
        )

    def _search_v2(self, original: str, focus: str, limit: int) -> SearchResult:
        size = min(max(1, int(limit)), 20)
        data = self.http.get_json(self.endpoint, {"filter[title]": focus, "page[size]": size})
        rows = data.get("data")
        if not isinstance(rows, list):
            raise ValueError("OSF v2 response missing data")
        records = []
        for item in rows:
            if not isinstance(item, dict):
                continue
            rid = str(item.get("id") or "")
            attrs = item.get("attributes") or {}
            if not rid:
                continue
            records.append(SearchRecord(
                self.name, rid, title=str(attrs.get("title") or ""),
                url=str((item.get("links") or {}).get("html") or f"https://osf.io/{rid}/"),
                metadata={"abstract": str(attrs.get("description") or "")[:2000],
                          "registry_search": "OSF v2 title-only fallback"},
            ))
        next_link = (data.get("links") or {}).get("next")
        return SearchResult(
            self.name, original, SourceStatus.PARTIAL, records, len(records),
            message=f"OSF v2 title-only query '{focus}', {len(records)} matches; "
                    + ("pagination not exhausted" if next_link else "title-only scope; manual broader check required"),
        )
