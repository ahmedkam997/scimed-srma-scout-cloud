import json
import subprocess

from scimed_scout.domain import SourceStatus
from scimed_scout.sources.crossref import CrossrefSource
from scimed_scout.sources.http import JsonHttpClient
from scimed_scout.sources.osf import OSFRegistrationsSource
from scimed_scout.sources.prospero import ProsperoCliSource
from scimed_scout.sources.semantic_scholar import SemanticScholarSource


def http(payload):
    return JsonHttpClient(loader=lambda _: payload, retries=0)


def test_crossref_positive_and_negative():
    positive = CrossrefSource(http({"message": {"total-results": 1, "items": [{"DOI": "10.1/x", "title": ["Review"]}]}})).search("x")
    assert positive.status == SourceStatus.SEARCHED_POSITIVE
    assert positive.records[0].doi == "10.1/x"

    negative = CrossrefSource(http({"message": {"total-results": 0, "items": []}})).search("x")
    assert negative.status == SourceStatus.SEARCHED_NEGATIVE


def test_semantic_scholar_positive():
    payload = {"total": 1, "data": [{"paperId": "P1", "title": "Review", "year": 2026, "externalIds": {"DOI": "10.2/y"}}]}
    result = SemanticScholarSource(http(payload), api_key="").search("x")
    assert result.status == SourceStatus.SEARCHED_POSITIVE
    assert result.records[0].record_id == "P1"


def test_osf_empty_metadata_search_is_partial_not_negative():
    result = OSFRegistrationsSource(http({"data": []})).search("x")
    assert result.status == SourceStatus.PARTIAL
    assert result.status != SourceStatus.SEARCHED_NEGATIVE


def test_prospero_cli_unavailable_is_access_failed():
    result = ProsperoCliSource(executable="definitely-not-installed-prospero").search("x")
    assert result.status == SourceStatus.ACCESS_FAILED


def test_prospero_cli_parses_machine_readable_search():
    payload = {
        "ok": True,
        "data": {
            "total_hits": 1,
            "hits": [{"record_id": "1", "accession_number": "CRD420260000001", "title": "Protocol", "year_first_published": 2026}],
        },
    }

    def runner(command):
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(payload), stderr="")

    result = ProsperoCliSource(runner=runner).search("x")
    assert result.status == SourceStatus.SEARCHED_POSITIVE
    assert result.records[0].record_id == "CRD420260000001"



def test_osf_trove_search_returns_real_registration_and_source_abstract():
    response = {
        "data": {
            "attributes": {"totalResultCount": 1},
            "relationships": {"searchResultPage": {
                "data": [{"id": "hit1", "type": "search-result"}],
                "links": {},
            }},
        },
        "included": [
            {"id": "hit1", "type": "search-result",
             "relationships": {"indexCard": {"data": {"id": "card1", "type": "index-card"}}}},
            {"id": "card1", "type": "index-card",
             "attributes": {"resourceMetadata": {
                 "@id": "https://osf.io/ab123/",
                 "title": [{"@value": "Review of heart failure treatments"}],
                 "description": [{"@value": "A registered review protocol concerning heart failure."}],
             }}},
        ],
    }
    urls = []
    def load(url):
        urls.append(url)
        return response
    result = OSFRegistrationsSource(JsonHttpClient(loader=load)).search("heart failure adults", limit=4)
    assert result.status == SourceStatus.SEARCHED_POSITIVE
    assert result.records[0].record_id == "ab123"
    assert result.records[0].metadata["abstract"].startswith("A registered")
    assert "cardSearchText" in urls[0]
    assert "resourceType" in urls[0]


def test_osf_trove_partial_pagination_keeps_records_instead_of_claiming_negative():
    response = {
        "data": {
            "attributes": {"totalResultCount": 35},
            "relationships": {"searchResultPage": {
                "data": [{"id": "hit1", "type": "search-result"}],
                "links": {"next": {"href": "https://evil.example/steal"}},
            }},
        },
        "included": [
            {"id": "hit1", "type": "search-result",
             "relationships": {"indexCard": {"data": {"id": "card1", "type": "index-card"}}}},
            {"id": "card1", "type": "index-card",
             "attributes": {"resourceMetadata": {
                 "@id": "https://osf.io/abc99/",
                 "title": [{"@value": "A valid source-backed protocol"}],
             }}},
        ],
    }
    result = OSFRegistrationsSource(JsonHttpClient(loader=lambda url: response)).search("heart failure", limit=3)
    assert result.status == SourceStatus.PARTIAL
    assert len(result.records) == 1
    assert "untrusted" in result.message.lower()


def test_osf_v2_title_filter_is_only_a_partial_fallback():
    def load(url):
        if "share.osf.io" in url:
            raise RuntimeError("Trove timeout")
        return {"data": [{"id": "osf11", "attributes": {"title": "Registered systematic review"}}], "links": {}}
    result = OSFRegistrationsSource(JsonHttpClient(loader=load)).search("TAVR versus surgery", limit=4)
    assert result.status == SourceStatus.PARTIAL
    assert result.records[0].record_id == "osf11"
    assert "Trove unavailable" in result.message


def test_prospero_multi_page_partial_does_not_infer_absence():
    payload = {"ok": True, "data": {
        "total_hits": 9,
        "hits": [{"record_id": "1", "accession_number": "CRD420261111111",
                  "title": "Registered review", "year_first_published": 2026}],
    }}
    commands = []
    def run(command):
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(payload), stderr="")
    res = ProsperoCliSource(runner=run, max_pages=2).search("heart failure", limit=1)
    assert res.status == SourceStatus.PARTIAL
    assert res.records[0].record_id == "CRD420261111111"
    assert commands[1][-4:-2] == ["--page", "2"]
    assert "additional matches" in res.message


def test_prospero_zero_hits_is_negative_only_for_valid_successful_envelope():
    def run(command):
        output = {"ok": True, "data": {"total_hits": 0, "hits": []}}
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(output), stderr="")
    res = ProsperoCliSource(runner=run).search("extremely specific uncommon combination")
    assert res.status == SourceStatus.SEARCHED_NEGATIVE
    def malformed(command):
        return subprocess.CompletedProcess(command, 0, stdout="{}", stderr="")
    assert ProsperoCliSource(runner=malformed).search("x").status == SourceStatus.PARTIAL


def test_prospero_node_entry_can_run_from_verified_worker_build(monkeypatch, tmp_path):
    script = tmp_path / "cli.js"
    script.write_text("// source-built CLI", encoding="utf8")
    monkeypatch.setenv("PROSPERO_CLI_JS", str(script))
    calls = []
    def run(command):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps({
            "ok": True, "data": {"total_hits": 0, "hits": []},
        }), stderr="")
    result = ProsperoCliSource(runner=run).search("x")
    assert result.status == SourceStatus.SEARCHED_NEGATIVE
    assert calls[0][0] == "prospero"  # mocked runner takes precedence


def test_prospero_count_drift_preserves_fetched_pages_without_false_clearance():
    import json
    import subprocess
    from scimed_scout.sources.prospero import ProsperoCliSource
    from scimed_scout.domain import SourceStatus

    calls=[]
    def inconsistent_index(command):
        calls.append(command)
        page=1 if len(calls)==1 else 2
        payload={"ok":True,"data":{"total_hits":8 if page==1 else 9,
            "hits":[{"record_id":str(page),"accession_number":f"CRD42026000000{page}",
                     "title":f"Registered review {page}"}]}}
        return subprocess.CompletedProcess(command,0,stdout=json.dumps(payload),stderr="")
    result=ProsperoCliSource(runner=inconsistent_index,max_pages=2).search("heart failure",limit=2)
    assert result.status==SourceStatus.PARTIAL
    assert len(result.records)==2
    assert "count_changed=True" in result.message


def test_osf_trove_three_pages_are_retrieved_and_verified_when_exhausted():
    calls = []
    def load(url):
        calls.append(url)
        number = len(calls)
        next_url = (
            f"https://share.osf.io/trove/index-card-search?page%5Bcursor%5D={number + 1}"
            if number < 3 else None
        )
        return {
            "data": {
                "attributes": {"totalResultCount": 3},
                "relationships": {"searchResultPage": {
                    "data": [{"id": f"hit{number}", "type": "search-result"}],
                    "links": {"next": {"href": next_url}} if next_url else {},
                }},
            },
            "included": [
                {"id": f"hit{number}", "type": "search-result",
                 "relationships": {"indexCard": {"data": {"id": f"card{number}", "type": "index-card"}}}},
                {"id": f"card{number}", "type": "index-card",
                 "attributes": {"resourceMetadata": {
                     "@id": f"https://osf.io/abc{number}/",
                     "title": [{"@value": f"Registration {number}"}],
                 }}},
            ],
        }

    result = OSFRegistrationsSource(JsonHttpClient(loader=load)).search(
        "heart failure ablation", limit=20
    )
    assert len(calls) == 3
    assert result.status == SourceStatus.SEARCHED_POSITIVE
    assert len(result.records) == 3
