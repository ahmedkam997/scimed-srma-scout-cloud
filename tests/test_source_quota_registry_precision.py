"""Regression tests for free scholarly API quota behavior and PICO registry precision.

No network calls in tests. Scientific qualification remains independent.
"""
import urllib.parse

from scimed_scout.domain import SourceStatus
from scimed_scout.sources.http import JsonHttpClient
from scimed_scout.sources.openalex import OpenAlexSource
from scimed_scout.sources.semantic_scholar import SemanticScholarSource
from scimed_scout.storage import CandidateRecord
from scimed_scout.verification.queries import build_search_plan


def test_openalex_keyless_live_request_is_explicitly_unavailable(monkeypatch):
    monkeypatch.delenv("OPENALEX_API_KEY",raising=False)
    def forbid_network(*a,**kw): raise AssertionError("Should never access a public API without key")
    import urllib.request
    monkeypatch.setattr(urllib.request,"urlopen",forbid_network)
    client=OpenAlexSource(JsonHttpClient(retries=0),api_key="")
    first=client.search("left main FFR")
    second=client.search("another PICO")
    assert first.status == SourceStatus.ACCESS_FAILED
    assert second.status == SourceStatus.ACCESS_FAILED
    assert "OPENALEX_API_KEY" in first.message
    assert "not executed" in first.message
    assert not first.records


def test_openalex_with_free_key_preserves_source_provenance():
    urls=[]
    def load(url):
        urls.append(url)
        return {"meta":{"count":1},"results":[
            {"id":"https://openalex.org/W42","title":"Index test report",
             "publication_year":2026,"doi":"https://doi.org/10.1000/42"}
        ]}
    src=OpenAlexSource(JsonHttpClient(loader=load),api_key="FREE-TEST-KEY")
    answer=src.search("left main FFR")
    assert answer.status==SourceStatus.SEARCHED_POSITIVE
    assert answer.records[0].doi=="10.1000/42"
    qs=urllib.parse.parse_qs(urllib.parse.urlsplit(urls[0]).query)
    assert qs["api_key"]==["FREE-TEST-KEY"]


def test_semanticscholar_keyless_live_client_only_makes_one_probe(monkeypatch):
    import urllib.request
    calls=[]
    class FakeResponse:
        def __enter__(self): return self
        def __exit__(self,*args): return False
        def read(self): return b'{"total":0,"data":[]}'
    def respond(request,timeout=None):
        calls.append(request.full_url)
        return FakeResponse()
    monkeypatch.setattr(urllib.request,"urlopen",respond)
    src=SemanticScholarSource(JsonHttpClient(retries=0),api_key="")
    a=src.search("ffr ct left main")
    b=src.search("unrelated broad search")
    assert a.status==SourceStatus.SEARCHED_NEGATIVE
    assert b.status==SourceStatus.PARTIAL
    assert "SEMANTIC_SCHOLAR_API_KEY" in b.message
    assert len(calls)==1


def test_semanticscholar_authenticated_requests_spaced_across_picos(monkeypatch):
    import scimed_scout.sources.semantic_scholar as mod
    observed_sleeps=[]
    clock=[100.0]
    monkeypatch.setattr(mod.time,"monotonic",lambda:clock[0])
    def advance(seconds):
        observed_sleeps.append(seconds)
        clock[0]+=seconds
    monkeypatch.setattr(mod.time,"sleep",advance)
    payload={"total":1,"data":[{"paperId":"P01","title":"Trial"}]}
    src=SemanticScholarSource(JsonHttpClient(loader=lambda url:payload),api_key="TEST")
    # Injected loader performs no remote I/O, so it must not be throttled.
    assert src.search("x").status==SourceStatus.SEARCHED_POSITIVE
    assert observed_sleeps==[]
    # Model actual network behavior without sending requests.
    src.http.loader=None
    import urllib.request
    class FakeResponse:
        def __enter__(self): return self
        def __exit__(self,*args): return False
        def read(self): return b'{"total":1,"data":[{"paperId":"P01","title":"Trial"}]}'
    monkeypatch.setattr(urllib.request,"urlopen",lambda request,timeout=None:FakeResponse())
    assert src.search("x1").status==SourceStatus.SEARCHED_POSITIVE
    assert src.search("x2").status==SourceStatus.SEARCHED_POSITIVE
    assert len(observed_sleeps)==1
    assert 1.09 <= observed_sleeps[0] <=1.11


def _topic(index, population, comparator, outcome):
    return CandidateRecord(
        candidate_id="T",project_id="P",title="Precise clinical PICO",
        specialty="Cardiology",question_type="DIAGNOSTIC_TEST_ACCURACY",
        intervention_exposure_index_test=index,population=population,
        comparator_reference=comparator,outcomes=[outcome],
        eligible_designs=["diagnostic cohort"],
    )


def test_left_main_registry_queries_keep_left_main_together():
    plan=build_search_plan(_topic(
        "Computed tomography fractional flow reserve",
        "Adults with intermediate left main coronary stenosis",
        "Invasive FFR","Sensitivity and specificity",
    ))
    assert 2 <= len(plan.registry_queries) <=3
    assert '"left main"' in plan.registry_queries[0]
    assert all(" AND " in x for x in plan.registry_queries)
    assert not any('"intermediate left"' in x for x in plan.registry_queries)


def test_stable_cad_registry_condition_not_generic_suspected_stable_fragment():
    plan=build_search_plan(_topic(
        "Coronary computed tomography angiography",
        "Adults with suspected stable coronary artery disease",
        "Invasive coronary angiography","Sensitivity"
    ))
    assert '"coronary artery disease"' in plan.registry_queries[0]
    assert not any('"suspected stable"' in x for x in plan.registry_queries)
    assert 2 <= len(plan.registry_queries) <=3
