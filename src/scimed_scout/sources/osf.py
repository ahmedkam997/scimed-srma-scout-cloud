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
    "oral", "low", "high", "dose", "doses", "daily", "weekly", "acute",
    "supplementation", "ingestion", "administration", "percutaneous",
}


def _focus_query(query: str) -> str:
    """Preserve Boolean PICO anchors in OSF Trove's documented query syntax.

    Trove supports '+' for AND and double quotes for phrases. The old
    tokenizer dropped the Boolean AND and took just the first four
    (often generic dose/route) words, leading to hundreds of unrelated
    registrations and a consistently unfinishable semantic queue.
    """
    raw = str(query or "")
    quoted = re.findall(r'"([^"]+)"', raw)
    if len(quoted) >= 2 and re.search(r"\bAND\b", raw, flags=re.I):
        groups = []
        for value, limit in ((quoted[0], 4), (quoted[1], 3)):
            words = re.findall(r"[a-z0-9\u0600-\u06ff]+", value.casefold())
            useful = [
                word for word in words
                if word not in STOP and (
                    len(word) > 2 or (len(word) == 2 and any(ch.isdigit() for ch in word))
                )
            ]
            groups.append(" ".join(useful[:limit]))
        if all(groups):
            return '+"' + groups[0] + '" +"' + groups[1] + '"'
    terms = re.findall(r"[a-z0-9\u0600-\u06ff]+", raw.casefold())
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
            result = self._search_trove(query, focus, limit)
            # Compare the same intervention scope in both indexes.
            anchor = re.match(r'^\+"([^"]+)"', focus)
            if (anchor and result.status == SourceStatus.PARTIAL
                    and result.records and "Index disagreement" in result.message):
                broad = '"' + anchor.group(1) + '"'
                try:
                    recovered = self._search_trove(query, broad, limit, confirm_zero=False)
                except (RuntimeError, ValueError, TypeError, KeyError, OSError):
                    return result
                v2_ids = {r.record_id for r in result.records}
                trove_ids = {r.record_id for r in recovered.records}
                merged = {r.record_id: r for r in result.records}
                merged.update({r.record_id: r for r in recovered.records})
                reconciled = (
                    recovered.status == SourceStatus.SEARCHED_POSITIVE
                    and "v2_pages_complete=True" in result.message
                    and v2_ids.issubset(trove_ids)
                )
                return SearchResult(
                    self.name, query,
                    SourceStatus.SEARCHED_POSITIVE if reconciled else SourceStatus.PARTIAL,
                    list(merged.values()), len(merged),
                    message=(result.message + f" Same-anchor Trove retry {broad}: "
                             f"{len(v2_ids & trove_ids)}/{len(v2_ids)} v2 IDs reconciled; "
                             f"scope_reconciled={reconciled}. "
                             + recovered.message
                             + " Scoped registration retrieval only; not novelty clearance."),
                )
            # Exact intervention+population phrases are often too narrow for
            # public OSF registration titles. A focused zero must never be
            # mistaken for proof that no competing review exists. Retry one
            # broader intervention anchor before returning a provisional audit.
            if (
                result.status in (
                    SourceStatus.PARTIAL, SourceStatus.SEARCHED_NEGATIVE,
                ) and not result.records
                and (
                    result.status == SourceStatus.SEARCHED_NEGATIVE
                    or "no indexed matches" in (result.message or "")
                )
                and (len(focus.split()) > 2 or focus.startswith('+"'))
            ):
                # Retain the high-sensitivity intervention-only fallback
                # for OSF titles that omit the disease. Extract the ACTUAL
                # intervention phrase, not the former "oral low" substring.
                anchor = re.match(r'^\+"([^"]+)"', focus)
                broad = anchor.group(1) if anchor else " ".join(focus.split()[:2])
                broad_result = self._search_trove(query, broad, limit)
                cap = max(12, min(30, int(limit)))
                records = list(broad_result.records)[:cap]
                # Truncating a broad source result never counts as complete.
                truncated = len(records) < len(broad_result.records)
                if broad_result.status in (
                    SourceStatus.SEARCHED_POSITIVE, SourceStatus.SEARCHED_NEGATIVE
                ):
                    return SearchResult(
                        self.name, query,
                        SourceStatus.PARTIAL if truncated else broad_result.status,
                        records, broad_result.total_count,
                        message=(
                            f"Focused phrase '{focus}' had no indexed matches; "
                            f"broader intervention search '{broad}' was "
                            f"{broad_result.status.value}. "
                            "The broader query is a scoped registration audit, "
                            "not independent PICO-overlap or novelty clearance. "
                            + ("Broad results truncated for a manual evidence queue; "
                               if truncated else "")
                            + broad_result.message
                        ),
                    )
                if broad_result.records:
                    return SearchResult(
                        self.name, query, SourceStatus.PARTIAL,
                        records, broad_result.total_count,
                        message=(
                            f"Focused phrase '{focus}' returned zero; "
                            f"broader '{broad}' found partial results. "
                            "The returned citations are an incomplete manual queue. "
                            + broad_result.message
                        ),
                    )
                return SearchResult(
                    self.name, query, SourceStatus.PARTIAL, [],
                    result.total_count,
                    message=(
                        f"Neither focused '{focus}' nor broad '{broad}' "
                        "had independently confirmed registration index coverage. "
                        "Do not infer a negative review-competition result."
                    ),
                )
            return result
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

    def _search_trove(self, original: str, focus: str, limit: int, *, confirm_zero: bool = True) -> SearchResult:
        # Registry verification needs complete matching pages, not a small
        # screening display limit. 50 per page reduces partials and API calls.
        size = 50
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
        retrieved_page_hits = 0
        malformed_hits = 0
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
            retrieved_page_hits += len(page_results)
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
                    malformed_hits += 1
                    continue
                title = _literal(metadata.get("title")).strip()
                if not title:
                    malformed_hits += 1
                    continue
                original_url = _literal(metadata.get("@id") or attrs.get("resourceIdentifier"))
                candidates = re.findall(r"https://osf\.io/([a-z0-9]+)/?", original_url, re.IGNORECASE)
                rid = candidates[0].lower() if candidates else str(card.get("id") or "")
                if not rid:
                    malformed_hits += 1
                    continue
                description = _literal(metadata.get("description"))[:2400]
                # Trove uses JSON-LD. These fields describe registration
                # metadata, not the last date the review searched literature.
                registered = _literal(
                    metadata.get("dateRegistered") or metadata.get("dateCreated")
                    or metadata.get("datePublished")
                ).strip()
                modified = _literal(metadata.get("dateModified")).strip()
                status = _literal(metadata.get("status")).strip()
                withdrawn = _literal(metadata.get("withdrawn")).strip()
                year = int(registered[:4]) if re.match(r"^(?:19|20)\d{2}", registered) else None
                records[rid] = SearchRecord(
                    self.name, rid, title=title,
                    url=f"https://osf.io/{rid}/" if candidates else "",
                    year=year,
                    metadata={
                        "abstract": description,
                        "trove_card_id": str(card.get("id") or ""),
                        "registry_search": "OSF Trove title+description",
                        "date_registered": registered,
                        "date_modified": modified,
                        "registry_status": status,
                        "withdrawn": withdrawn,
                    },
                )
            pages += 1
            next_link = (data.get("links") or {}).get("next")
            url = (next_link.get("href") if isinstance(next_link, dict) else next_link) or ""
            remaining = bool(url)
            if not remaining or (total is not None and len(records) >= total):
                break

        # A valid zero in Trove alone is not global registration clearance.
        # Ask OSF's separate v2 registration index for an explicit zero and
        # retain the narrower query scope in the audit.
        if not records:
            if confirm_zero and total == 0 and not remaining and malformed_hits == 0:
                try:
                    confirmation = self.http.get_json(self.endpoint, {
                        # OSF v2 title filter is plain text, not Trove's
                        # '+' Boolean syntax; use only the exact index
                        # intervention phrase for independent validation.
                        "filter[title]": (
                            re.search(r'^\+"([^"]+)"', focus).group(1)
                            if re.search(r'^\+"([^"]+)"', focus) else focus
                        ),
                        "page[size]": 20,
                    })
                    rows = confirmation.get("data")
                    meta = confirmation.get("meta") or {}
                    links = confirmation.get("links") or {}
                    # Live OSF APIv2 (verified against the public endpoint)
                    # returns meta={"version": "..."} without meta.total.
                    # A successful, empty data page with a recognized version
                    # and no next link is a completed *scoped* title search.
                    # Never assert that all possible registrations are absent.
                    versioned_zero = (
                        isinstance(meta, dict)
                        and isinstance(meta.get("version"), str)
                        and bool(meta["version"].strip())
                        and meta.get("total") is None
                    )
                    counted_zero = isinstance(meta, dict) and meta.get("total") == 0
                    if (
                        isinstance(rows, list) and not rows
                        and (versioned_zero or counted_zero)
                        and isinstance(links, dict)
                        and not links.get("next")
                    ):
                        return SearchResult(
                            self.name, original, SourceStatus.SEARCHED_NEGATIVE, [], 0,
                            message=(
                                f"OSF Trove metadata and independent OSF v2 title-filter "
                                f"completed zero-result queries for scoped query phrase '{focus}'. "
                                "The result is not global novelty clearance: synonyms, "
                                "other wording and unindexed registrations require "
                                "independent verification."
                            ),
                        )
                    if isinstance(rows, list) and rows:
                        # The indexes can disagree: Trove can return zero
                        # for exact Boolean phrases while the official OSF
                        # registration v2 title filter returns real records.
                        # Previously these real citations were DISCARDED.
                        # Preserve the records for manual checking; never
                        # declare complete registration search coverage.
                        v2_records, v2_complete = self._collect_v2_pages(confirmation)
                        return SearchResult(
                            self.name, original, SourceStatus.PARTIAL,
                            v2_records, len(v2_records),
                            message=(
                                f"OSF Trove returned zero for '{focus}' but v2 "
                                f"found {len(v2_records)} title-filter matches "
                                f"({len(v2_records)} parsed records). "
                                "Citations retained for manual verification. "
                                f"Index disagreement prevents full search clearance. v2_pages_complete={v2_complete}"
                            ),
                        )
                except (RuntimeError, ValueError, TypeError, KeyError, OSError):
                    pass
            return SearchResult(
                self.name, original, SourceStatus.PARTIAL, [], total,
                message=(
                    f"OSF Trove title/description query '{focus}': no indexed matches, "
                    "but independent OSF v2 zero confirmation is absent. "
                    "Manual broader check required."
                ),
            )
        complete = bool(
            total is not None
            and not remaining
            and retrieved_page_hits >= total
            and malformed_hits == 0
        )
        # The index may contain duplicate registration cards: unique count can
        # be below total even when the entire page traversal is exhausted.
        return SearchResult(
            self.name, original, SourceStatus.SEARCHED_POSITIVE if complete else SourceStatus.PARTIAL,
            list(records.values()), total,
            message=(
                f"OSF Trove query '{focus}': {len(records)} unique registrations, "
                f"{retrieved_page_hits}/{total} indexed hits, {pages} page(s), "
                f"unresolved_cards={malformed_hits}; "
                + ("all indexed query pages and cards processed"
                   if complete else "index scope incomplete; manual verification required")
            ),
        )


    def _v2_records(self, rows: list[dict]) -> list[SearchRecord]:
        """Parse actual registration citations from OSF v2 without inventing
        a full-text protocol, eligibility result or last search date.
        """
        records = []
        for item in rows:
            if not isinstance(item, dict):
                continue
            rid = str(item.get("id") or "")
            attrs = item.get("attributes") or {}
            if not rid:
                continue
            registered = str(attrs.get("date_registered") or "")
            year = int(registered[:4]) if re.match(r"^(?:19|20)\d{2}", registered) else None
            records.append(SearchRecord(
                self.name, rid, title=str(attrs.get("title") or ""),
                url=str((item.get("links") or {}).get("html") or f"https://osf.io/{rid}/"),
                year=year,
                metadata={
                    "abstract": str(attrs.get("description") or "")[:2000],
                    "registry_search": "OSF v2 title-only fallback",
                    "date_registered": registered,
                    "date_modified": str(attrs.get("date_modified") or ""),
                    "registry_status": str(attrs.get("reviews_state") or ""),
                    "withdrawn": bool(attrs.get("withdrawn", False)),
                },
            ))
        return records

    def _collect_v2_pages(self, first: dict) -> tuple[list[SearchRecord], bool]:
        """Exhaust bounded v2 pagination; retain earlier results on errors."""
        page = first
        records: dict[str, SearchRecord] = {}
        visited: set[str] = set()
        valid = True
        expected_total = None
        for index in range(self.max_pages):
            rows = page.get("data")
            links = page.get("links")
            if not isinstance(rows, list) or not isinstance(links, dict):
                return list(records.values()), False
            parsed = self._v2_records(rows)
            if len(parsed) != len(rows) or any(not r.title.strip() for r in parsed):
                valid = False
            records.update({r.record_id: r for r in parsed})
            meta = page.get("meta") or {}
            if isinstance(meta, dict) and isinstance(meta.get("total"), int):
                count = meta["total"]
                if expected_total is not None and count != expected_total:
                    valid = False
                expected_total = count
            nxt = links.get("next")
            if isinstance(nxt, dict):
                nxt = nxt.get("href")
            if not nxt:
                return list(records.values()), bool(
                    valid and (expected_total is None or expected_total == len(records))
                )
            if (index + 1 >= self.max_pages or not isinstance(nxt, str) or nxt in visited
                    or not _safe_next(nxt, "api.osf.io", "/v2/registrations/")):
                return list(records.values()), False
            visited.add(nxt)
            try:
                page = self.http.get_json(nxt)
            except (RuntimeError, ValueError, TypeError, KeyError, OSError):
                return list(records.values()), False
        return list(records.values()), False

    def _search_v2(self, original: str, focus: str, limit: int) -> SearchResult:
        size = min(max(1, int(limit)), 20)
        data = self.http.get_json(self.endpoint, {"filter[title]": focus, "page[size]": size})
        rows = data.get("data")
        if not isinstance(rows, list):
            raise ValueError("OSF v2 response missing data")
        records, complete = self._collect_v2_pages(data)
        return SearchResult(
            self.name, original, SourceStatus.PARTIAL, records, len(records),
            message=f"OSF v2 title-only query '{focus}', {len(records)} matches; "
                    + ("title-only scope; manual broader check required" if complete else "pagination not exhausted"),
        )
