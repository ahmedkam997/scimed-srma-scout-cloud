"""Source-safe broad OSF retry for highly specific clinical phrases."""
from urllib.parse import urlsplit, parse_qs

from scimed_scout.domain import SourceStatus
from scimed_scout.sources.http import JsonHttpClient
from scimed_scout.sources.osf import OSFRegistrationsSource


def trove_page(title=None):
    if title is None:
        return {
            "data": {"attributes": {"totalResultCount": 0},
                     "relationships": {"searchResultPage": {"data": [], "links": {}}}},
            "included": [],
        }
    return {
        "data": {"attributes": {"totalResultCount": 1},
                 "relationships": {"searchResultPage": {
                     "data": [{"id": "hit1", "type": "search-result"}], "links": {},
                 }}},
        "included": [
            {"id": "hit1", "type": "search-result",
             "relationships": {"indexCard": {"data": {"id": "card1"}}}},
            {"id": "card1", "type": "index-card",
             "attributes": {"resourceMetadata": {
                 "@id": "https://osf.io/abc12/", "title": title,
                 "dateRegistered": "2018-02-01",
             }}},
        ],
    }


def test_osf_specific_zero_retries_broader_intervention_and_recovers_registry():
    requested = []
    def load(url):
        requested.append(url)
        if "api.osf.io" in url:
            return {"data": [], "links": {}}
        focus = parse_qs(urlsplit(url).query)["cardSearchText[title,description]"][0]
        return trove_page("Systematic review of ketone monoester") if focus == "ketone monoester" else trove_page()

    result = OSFRegistrationsSource(JsonHttpClient(loader=load)).search(
        '"ketone monoester" AND "heart failure"'
    )
    assert result.status == SourceStatus.SEARCHED_POSITIVE
    assert len(result.records) == 1
    assert result.records[0].year == 2018
    assert "broader intervention" in result.message
    assert "not independent PICO-overlap" in result.message
    assert sum("share.osf.io" in url for url in requested) == 2
    assert all("ketone" in url for url in requested if "share.osf.io" in url)


def test_osf_specific_and_broad_zero_without_v2_confirmation_stays_partial():
    seen = []
    def load(url):
        seen.append(url)
        return {"data": [], "links": {}} if "api.osf.io" in url else trove_page()
    result = OSFRegistrationsSource(JsonHttpClient(loader=load)).search(
        '"ketone monoester" AND "heart failure"'
    )
    assert result.status == SourceStatus.PARTIAL
    assert result.records == []
    assert "Do not infer a negative" in result.message
    assert sum("share.osf.io" in url for url in seen) == 2


def test_osf_single_short_phrase_does_not_retry_identical_broad_search():
    seen = []
    def load(url):
        seen.append(url)
        return {"data": [], "links": {}} if "api.osf.io" in url else trove_page()
    result = OSFRegistrationsSource(JsonHttpClient(loader=load)).search("heart failure")
    assert result.status == SourceStatus.PARTIAL
    assert sum("share.osf.io" in url for url in seen) == 1
