"""Regression tests for real-world OpenAlex/Semantic Scholar shared quotas.

No live requests or charged API use. A single '200' request proves only one
targeted query succeeded, not that all PICO search coverage is complete.
"""
from urllib.parse import parse_qs, urlsplit

from scimed_scout.domain import SourceStatus
from scimed_scout.sources.openalex import OpenAlexSource
from scimed_scout.sources.semantic_scholar import SemanticScholarSource
from scimed_scout.storage import CandidateRecord
from scimed_scout.verification.queries import build_search_plan


class LiveStubHttp:
    # loader=None intentionally exercises live-source quota controls but
    # replaces network with a deterministic local fake.
    loader = None

    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def get_json(self, endpoint, params=None, *, headers=None):
        self.calls.append((endpoint, params, headers))
        return self.payload


def test_openalex_without_key_performs_one_probe_not_endless_requests():
    stub = LiveStubHttp({"meta":{"count":1}, "results":[
        {"id":"https://openalex.org/W123","title":"Evidence lead"}]})
    source = OpenAlexSource(stub, api_key="")
    first = source.search("clinical PICO A")
    next_query = source.search("unrelated clinical PICO B")
    assert first.status == SourceStatus.SEARCHED_POSITIVE
    assert next_query.status == SourceStatus.PARTIAL
    assert "not executed" in next_query.message
    assert len(stub.calls) == 1
    assert "api_key" in stub.calls[0][1]
    assert stub.calls[0][1]["api_key"] is None
    assert not source._rate_limited


def test_openalex_with_key_allows_many_queries_without_leaking_key_in_status():
    stub = LiveStubHttp({"meta":{"count":0},"results":[]})
    source = OpenAlexSource(stub,api_key="FREE-PRIVATE-KEY")
    assert source.search("A").status == SourceStatus.SEARCHED_NEGATIVE
    assert source.search("B").status == SourceStatus.SEARCHED_NEGATIVE
    assert len(stub.calls)==2
    assert all(params.get("api_key")=="FREE-PRIVATE-KEY"
               for _,params,_ in stub.calls)


def test_semantic_scholar_shared_quota_one_probe_only():
    stub=LiveStubHttp({"total":1, "data":[{"paperId":"P1","title":"Trial"}]})
    source=SemanticScholarSource(stub,api_key="")
    assert source.search("A").status == SourceStatus.SEARCHED_POSITIVE
    rest=source.search("B")
    assert rest.status == SourceStatus.PARTIAL
    assert "SEMANTIC_SCHOLAR_API_KEY" in rest.message
    assert len(stub.calls)==1


def test_semantic_scholar_keyed_calls_are_paced(monkeypatch):
    stub=LiveStubHttp({"total":0, "data":[]})
    source=SemanticScholarSource(stub,api_key="FAKE-S2-KEY")
    sleeps=[]
    monkeypatch.setattr("scimed_scout.sources.semantic_scholar.time.sleep",
                        lambda duration: sleeps.append(duration))
    # Deterministic monotonic time, so a second request needs pacing.
    monkeypatch.setattr("scimed_scout.sources.semantic_scholar.time.monotonic",
                        lambda: 100.0)
    assert source.search("A").status == SourceStatus.SEARCHED_NEGATIVE
    assert source.search("B").status == SourceStatus.SEARCHED_NEGATIVE
    assert len(stub.calls)==2
    assert len(sleeps)==1 and 1.0 <= sleeps[0] <= 1.2
    assert stub.calls[0][2]=={"x-api-key":"FAKE-S2-KEY"}


def candidate(intervention, population, comparator, outcome):
    return CandidateRecord(
        candidate_id="C", project_id="P", title=intervention,
        specialty="Cardiology", question_type="EFFECTIVENESS",
        population=population,
        intervention_exposure_index_test=intervention,
        comparator_reference=comparator,
        outcomes=[outcome],
    )


def test_prospero_focus_uses_complete_heart_failure_condition_not_sliced_fragments():
    c=candidate("SGLT2 inhibitor therapy",
        "Adults with heart failure with preserved ejection fraction and type 2 diabetes",
        "DPP-4 inhibitor therapy","Cardiovascular hospitalization")
    queries=build_search_plan(c).registry_queries
    assert queries
    assert len(queries) <= 3
    assert any('"heart failure"' in q for q in queries)
    assert not any('"preserved ejection"' in q for q in queries)
    assert all(q.count(" AND ") == 1 for q in queries)
    assert all("sglt2" in q.casefold() for q in queries)


def test_prospero_focus_preserves_left_main_and_reference_standard():
    c=candidate("Computed tomography derived fractional flow reserve",
        "Adults with intermediate left main coronary artery stenosis",
        "Invasive fractional flow reserve","Sensitivity")
    queries=build_search_plan(c).registry_queries
    assert len(queries) <= 3
    assert any('"left main"' in q for q in queries)
    assert any('"invasive fractional"' in q for q in queries)
    assert all("fractional flow reserve" in q.casefold() for q in queries)


def test_prospero_registry_queries_are_precision_discovery_not_clearance():
    c=candidate("Ketone monoester ingestion (oral dose)",
        "Endurance athletes under heat stress",
        "Placebo","Post-exercise cardiac recovery indices")
    q=build_search_plan(c).registry_queries
    assert len(q)<=3
    assert all('"ketone monoester"' in item for item in q)
    assert any('"endurance athletes"' in item for item in q)
    assert all('"placebo"' not in item for item in q)
