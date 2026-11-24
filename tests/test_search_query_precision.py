"""Regression coverage for source-query precision and fail-closed registry checks.

These tests use fake bibliographic sources only. They cannot establish a
scientifically eligible study or prove absence of a competing review.
"""
from urllib.parse import parse_qs, urlsplit

from scimed_scout.domain import SourceStatus
from scimed_scout.sources.base import SearchResult
from scimed_scout.sources.osf import OSFRegistrationsSource, _focus_query
from scimed_scout.sources.openalex import OpenAlexSource
from scimed_scout.sources.semantic_scholar import SemanticScholarSource
from scimed_scout.sources.http import JsonHttpClient
from scimed_scout.storage import CandidateRecord
from scimed_scout.verification.queries import build_search_plan, _registry_anchor
from scimed_scout.discovery.candidate_preflight import search_query, review_search_query


def make_candidate(intervention, population="Adults with recent myocardial infarction"):
    return CandidateRecord(
        candidate_id="C1", project_id="P1",
        title=f"{intervention} in post-MI care",
        specialty="Cardiology", question_type="EFFECTIVENESS",
        review_question=f"Does {intervention} improve cardiovascular outcomes?",
        population=population,
        intervention_exposure_index_test=intervention,
        comparator_reference="Usual care",
        outcomes=["Post-infarction pericarditis", "Hospitalization"],
        eligible_designs=["RCT"],
        search_terms=["colchicine", "myocardial infarction"],
    )


def test_registry_anchor_preserves_drug_not_dose_route():
    c = make_candidate("Oral low-dose colchicine (0.5 mg daily)")
    assert _registry_anchor(c.intervention_exposure_index_test) == ["colchicine"]
    plan = build_search_plan(c)
    assert plan.registry_queries
    assert all(query.startswith('"colchicine" AND "') for query in plan.registry_queries)
    assert all("oral low" not in query.casefold() for query in plan.registry_queries)
    assert all("colchicine" in query.casefold() for query in plan.review_queries)
    assert all("myocardial" in query.casefold() or "pericarditis" in query.casefold()
               for query in plan.review_queries)
    assert '"colchicine"[Title/Abstract]' in search_query(c, current_year=2026)
    assert '"colchicine"[Title/Abstract]' in review_search_query(c, current_year=2026)


def test_registry_anchor_preserves_multiword_interventions():
    assert _registry_anchor("Percutaneous left atrial appendage occlusion device implantation") == [
        "left", "atrial", "appendage", "occlusion",
    ]
    assert _registry_anchor("Coronary computed tomography angiography") == [
        "coronary", "computed", "tomography", "angiography",
    ]
    assert _registry_anchor("Vitamin D3 supplementation (2000 IU daily)") == [
        "vitamin", "d3",
    ]
    assert _registry_anchor("Sacubitril-valsartan therapy") == [
        "sacubitril", "valsartan",
    ]


def test_osf_trove_query_preserves_documented_boolean_and():
    assert _focus_query('"colchicine" AND "myocardial infarction"') == (
        '+"colchicine" +"myocardial infarction"'
    )
    assert _focus_query('"vitamin d3" AND "marathon"') == (
        '+"vitamin d3" +"marathon"'
    )
    assert _focus_query(
        '"left atrial appendage occlusion" AND "atrial fibrillation"'
    ) == '+"left atrial appendage occlusion" +"atrial fibrillation"'


def test_focused_osf_no_match_uses_specific_intervention_fallback_without_false_clearance():
    class RecordingOSF(OSFRegistrationsSource):
        def __init__(self):
            super().__init__(JsonHttpClient(loader=lambda _: {}))
            self.queries = []

        def _search_trove(self, original, focus, limit):
            self.queries.append(focus)
            return SearchResult(
                self.name, original, SourceStatus.PARTIAL, [],
                total_count=None,
                message="OSF Trove: no indexed matches, independent check pending",
            )

    osf = RecordingOSF()
    result = osf.search('"colchicine" AND "myocardial infarction"', limit=15)
    assert osf.queries == [
        '+"colchicine" +"myocardial infarction"',
        "colchicine",
    ]
    assert "oral" not in osf.queries[-1]
    assert result.status == SourceStatus.PARTIAL
    assert not result.records
    assert "Do not infer a negative" in result.message


def test_openalex_uses_optional_key_and_stops_after_http429():
    calls = []

    def exhausted(url):
        calls.append(url)
        raise RuntimeError("HTTP Error 429: Too Many Requests")

    source = OpenAlexSource(JsonHttpClient(loader=exhausted, retries=0), api_key="TEST-KEY")
    assert source.search("Colchicine MI").status == SourceStatus.ACCESS_FAILED
    assert source.search("Another topic").status == SourceStatus.ACCESS_FAILED
    assert len(calls) == 1
    params = parse_qs(urlsplit(calls[0]).query)
    assert params["api_key"] == ["TEST-KEY"]
    assert "429" in source.search("Again").message


def test_semantic_scholar_stops_after_http429():
    calls = []

    def exhausted(url):
        calls.append(url)
        raise RuntimeError("HTTP Error 429")

    source = SemanticScholarSource(JsonHttpClient(loader=exhausted, retries=0))
    assert source.search("Colchicine MI").status == SourceStatus.ACCESS_FAILED
    assert source.search("Another topic").status == SourceStatus.ACCESS_FAILED
    assert len(calls) == 1
