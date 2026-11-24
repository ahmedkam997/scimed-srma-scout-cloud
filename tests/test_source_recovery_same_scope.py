"""Regression tests for same-scope registry reconciliation and optional S2."""
from urllib.parse import parse_qs, urlsplit

from scimed_scout.domain import SourceStatus
from scimed_scout.sources.http import JsonHttpClient
from scimed_scout.sources.osf import OSFRegistrationsSource
from scimed_scout.sources.factory import build_default_source_clients
from scimed_scout.sources.semantic_scholar import SemanticScholarSource


def trove(ids):
    return {
        "data": {"attributes": {"totalResultCount": len(ids)},
                 "relationships": {"searchResultPage": {"data": [
                     {"id": f"h{rid}"} for rid in ids], "links": {}}}},
        "included": [
            item for rid in ids for item in (
                {"id": f"h{rid}", "type": "search-result",
                 "relationships": {"indexCard": {"data": {"id": f"c{rid}"}}}},
                {"id": f"c{rid}", "type": "index-card", "attributes": {
                    "resourceMetadata": {"@id": f"https://osf.io/{rid}/",
                                         "title": f"Registered topic {rid}"}}},
            )
        ],
    }


def v2(ids, nxt=None):
    return {"meta": {"version": "2.0"}, "links": {"next": nxt}, "data": [
        {"id": rid, "attributes": {"title": f"Registered topic {rid}"}} for rid in ids]}


def run_recovery(broad_ids, next_url="https://api.osf.io/v2/registrations/?page=2"):
    def load(url):
        if "share.osf.io" in url:
            phrase = parse_qs(urlsplit(url).query)["cardSearchText[title,description]"][0]
            return trove(broad_ids if phrase == '"left atrial appendage occlusion"' else [])
        if "page=2" in url:
            return v2(["abc12"])
        return v2(["abc11"], next_url)
    return OSFRegistrationsSource(JsonHttpClient(loader=load)).search(
        '"left atrial appendage occlusion" AND "dialysis"')


def test_matching_scope_recovers_all_paginated_v2_ids():
    result = run_recovery(["abc11", "abc12", "abc13"])
    assert result.status == SourceStatus.SEARCHED_POSITIVE
    assert {r.record_id for r in result.records} == {"abc11", "abc12", "abc13"}
    assert "scope_reconciled=True" in result.message


def test_unmatched_v2_id_remains_partial_and_retained():
    result = run_recovery(["abc11", "abc13"])
    assert result.status == SourceStatus.PARTIAL
    assert {r.record_id for r in result.records} == {"abc11", "abc12", "abc13"}
    assert "scope_reconciled=False" in result.message


def test_untrusted_v2_pagination_cannot_be_cleared():
    result = run_recovery(["abc11"], "https://example.org/v2/registrations/?page=2")
    assert result.status == SourceStatus.PARTIAL
    assert "v2_pages_complete=False" in result.message


def test_production_keyless_s2_is_optional_and_sends_no_request(monkeypatch):
    monkeypatch.delenv("SEMANTIC_SCHOLAR_API_KEY", raising=False)
    s2 = next(s for s in build_default_source_clients() if s.name == "Semantic Scholar")
    def forbidden(*args):
        raise AssertionError("No anonymous production request")
    s2.http = JsonHttpClient(loader=forbidden)
    result = s2.search("cardiology")
    assert result.status == SourceStatus.NOT_SEARCHED
    assert not result.safe_negative


def test_explicit_health_probe_still_reports_actual_429():
    calls = []
    def blocked(url):
        calls.append(url)
        raise RuntimeError("HTTP Error 429: rate limit reached")
    s2 = SemanticScholarSource(JsonHttpClient(loader=blocked), api_key="",
                               allow_keyless_probe=True)
    assert s2.search("cardiology").status == SourceStatus.ACCESS_FAILED
    assert s2.search("second query").status == SourceStatus.ACCESS_FAILED
    assert len(calls) == 1
