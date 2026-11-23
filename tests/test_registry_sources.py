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
    page_flag = commands[1].index("--page")
    assert commands[1][page_flag:page_flag + 2] == ["--page", "2"]
    assert commands[1][-4:] == ["--sort", "accession", "--order", "asc"]
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


def test_prospero_focused_query_finishes_in_first_50_record_page():
    # The user-requested discovery limit is 20, but a focused PROSPERO
    # query with 35 matches should finish without a second page request.
    queries = []
    def fake(command):
        queries.append(command)
        n = 35
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps({
            "ok": True, "data": {
                "total_hits": n,
                "hits": [
                    {"record_id": str(i), "accession_number": f"CRD4202600{i:06d}",
                     "title": f"Protocol {i}"} for i in range(n)
                ],
            },
        }), stderr="")
    result = ProsperoCliSource(runner=fake).search("focused ablation question", limit=20)
    assert result.status == SourceStatus.SEARCHED_POSITIVE
    assert len(result.records) == 35
    assert len(queries) == 1
    assert queries[0][queries[0].index("--page-size") + 1] == "50"
    assert queries[0][-4:] == ["--sort", "accession", "--order", "asc"]


def test_prospero_cli_success_with_upstream_error_note_is_partial():
    def fake(command):
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps({
            "ok": True, "data": {"total_hits": 0, "hits": [],
                "raw_note": "Search backend unavailable"},
        }), stderr="")
    result = ProsperoCliSource(runner=fake).search("x")
    assert result.status == SourceStatus.PARTIAL
    assert result.status != SourceStatus.SEARCHED_NEGATIVE


def test_osf_requests_full_50_hit_pages_even_if_user_limit_is_twelve():
    seen = []
    def load(url):
        from urllib.parse import parse_qs, urlsplit
        seen.append(parse_qs(urlsplit(url).query))
        return {
            "data": {
                "attributes": {"totalResultCount": 1},
                "relationships": {"searchResultPage": {
                    "data": [{"id": "hit1", "type": "search-result"}],
                    "links": {},
                }},
            },
            "included": [
                {"id": "hit1", "type": "search-result", "relationships": {
                    "indexCard": {"data": {"id": "card1"}}}},
                {"id": "card1", "type": "index-card",
                 "attributes": {"resourceMetadata": {"title": "Registered topic",
                                                       "@id": "https://osf.io/abc12/"}}},
            ],
        }
    source = OSFRegistrationsSource(JsonHttpClient(loader=load))
    result = source.search("cardiac ablation", limit=12)
    assert result.status == SourceStatus.SEARCHED_POSITIVE
    assert seen[0]["page[size]"] == ["50"]


def test_osf_exhausted_indexed_pages_with_duplicate_cards_is_complete_positive():
    counter = [0]
    def load(url):
        counter[0] += 1
        page = counter[0]
        return {
            "data": {
                "attributes": {"totalResultCount": 2},
                "relationships": {"searchResultPage": {
                    "data": [{"id": f"hit{page}", "type": "search-result"}],
                    "links": {"next": {"href": "https://share.osf.io/trove/index-card-search?page=2"}}
                             if page == 1 else {},
                }},
            },
            "included": [
                {"id": f"hit{page}", "type": "search-result", "relationships": {
                    "indexCard": {"data": {"id": f"card{page}"}}}},
                {"id": f"card{page}", "type": "index-card",
                 "attributes": {"resourceMetadata": {"title": "Same registered topic",
                                                       "@id": "https://osf.io/abc12/"}}},
            ],
        }
    result = OSFRegistrationsSource(JsonHttpClient(loader=load)).search("heart failure")
    assert len(result.records) == 1
    assert result.status == SourceStatus.SEARCHED_POSITIVE
    assert "2/2 indexed hits" in result.message


def test_osf_two_independent_indexes_confirm_scoped_zero_only():
    calls = []
    def load(url):
        calls.append(url)
        if "share.osf.io" in url:
            return {
                "data": {
                    "attributes": {"totalResultCount": 0},
                    "relationships": {"searchResultPage": {"data": [], "links": {}}},
                },
                "included": [],
            }
        assert "api.osf.io" in url
        return {"data": [], "meta": {"total": 0}, "links": {"next": None}}
    result = OSFRegistrationsSource(JsonHttpClient(loader=load)).search("specific catheter ablation")
    assert result.status == SourceStatus.SEARCHED_NEGATIVE
    assert len(calls) == 2
    assert "scoped query" in result.message
    assert "unindexed registrations" in result.message


def test_osf_trove_zero_without_proven_v2_count_remains_partial():
    def load(url):
        if "share.osf.io" in url:
            return {
                "data": {
                    "attributes": {"totalResultCount": 0},
                    "relationships": {"searchResultPage": {"data": [], "links": {}}},
                },
                "included": [],
            }
        return {"data": [], "links": {}}
    result = OSFRegistrationsSource(JsonHttpClient(loader=load)).search("heart failure")
    assert result.status == SourceStatus.PARTIAL


def test_osf_discordant_v2_results_are_not_marked_negative():
    def load(url):
        if "share.osf.io" in url:
            return {
                "data": {
                    "attributes": {"totalResultCount": 0},
                    "relationships": {"searchResultPage": {"data": [], "links": {}}},
                },
                "included": [],
            }
        return {"data": [{"id": "abc123", "attributes": {"title": "Competing registered review"}}],
                "meta": {"total": 1}, "links": {}}
    result = OSFRegistrationsSource(JsonHttpClient(loader=load)).search("heart failure")
    assert result.status == SourceStatus.PARTIAL
    assert result.status != SourceStatus.SEARCHED_NEGATIVE


def test_prospero_capped_broad_search_recovers_title_hits_but_stays_partial():
    calls = []
    def run(command):
        calls.append(command)
        is_title = "--field" in command and command[command.index("--field") + 1] == "TI"
        page = int(command[command.index("--page") + 1])
        if is_title:
            hits = [{"record_id": "99", "accession_number": "CRD420260000099",
                     "title": "Specific cardiac intervention review"}]
            total = 1
        else:
            hits = [{"record_id": str(page), "accession_number": f"CRD4202600000{page:02d}",
                     "title": f"Broad search record {page}"}]
            total = 300
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps({
            "ok": True, "data": {"total_hits": total, "hits": hits},
        }), stderr="")
    result = ProsperoCliSource(runner=run, max_pages=2).search("cardiac intervention")
    assert len(result.records) == 3
    assert result.status == SourceStatus.PARTIAL
    assert "title_only_supplemental_records=1" in result.message
    assert result.records[-1].metadata["search_scope"] == "TITLE_ONLY_SUPPLEMENT"
    assert any("--field" in cmd for cmd in calls)
    assert result.status != SourceStatus.SEARCHED_NEGATIVE


def test_osf_trove_registration_year_is_parsed_for_age_based_update_audit():
    sample = {
        "data": {
            "attributes": {"totalResultCount": 1},
            "relationships": {"searchResultPage": {
                "data": [{"id": "h1", "type": "search-result"}],
                "links": {},
            }},
        },
        "included": [
            {"id": "h1", "type": "search-result",
             "relationships": {"indexCard": {"data": {"id": "c1"}}}},
            {"id": "c1", "type": "index-card",
             "attributes": {"resourceMetadata": {
                 "@id": "https://osf.io/abc12/",
                 "title": "Systematic review of ketone monoester",
                 "dateRegistered": "2019-04-21",
                 "dateModified": "2026-10-01",
             }}},
        ],
    }
    result = OSFRegistrationsSource(http(sample)).search("ketone monoester")
    assert result.status == SourceStatus.SEARCHED_POSITIVE
    assert result.records[0].year == 2019
    assert result.records[0].metadata["date_registered"] == "2019-04-21"
    assert result.records[0].metadata["date_modified"] == "2026-10-01"
