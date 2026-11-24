import copy
from types import SimpleNamespace

import pytest

from scimed_scout.cloud.source_recheck import (
    recheck_saved_topic, saved_topic, candidate_from_saved,
    source_statuses, query_plan_for_source, run_once,
)
from scimed_scout.domain import SourceStatus
from scimed_scout.sources.base import SearchRecord, SearchResult
from scimed_scout.verification.queries import build_search_plan


def parent_job():
    topic={
        "candidate_id":"CAND-ESRD-1",
        "title":"LAAO versus DOACs in dialysis-dependent ESRD",
        "question_type":"EFFECTIVENESS",
        "research_dossier":{
            "scientific_question":{
                "review_question":"Does percutaneous LAAO reduce stroke versus DOACs in ESRD?",
                "population":"Adults with atrial fibrillation and end-stage renal disease on dialysis",
                "intervention_exposure_index_test":"Left atrial appendage occlusion",
                "comparator_reference":"Direct oral anticoagulants",
                "outcomes":["Stroke","Major bleeding"],
            },
            "verification_and_quality":{
                "source_statuses":{
                    "PubMed":"SEARCHED_POSITIVE",
                    "OpenAlex":"ACCESS_FAILED",
                    "PROSPERO":"PARTIAL",
                    "Europe PMC":"PARTIAL",
                    "OSF Registries":"SEARCHED_POSITIVE",
                    "Semantic Scholar":"ACCESS_FAILED",
                },
            },
        },
    }
    return {
        "id":"JOB-1","client_token_hash":"c"*64,"status":"COMPLETED",
        "specialty":"Cardiology","question_type":"ALL",
        "result_json":{"package":{"provisional_options":[topic],"options":[]}},
    }


class MockSource:
    def __init__(self,name,status=SourceStatus.SEARCHED_POSITIVE,limit=1):
        self.name=name
        self.status=status
        self.calls=[]
        self.limit=limit

    def search(self,query,*,limit=20):
        self.calls.append((query,limit))
        if self.status==SourceStatus.ACCESS_FAILED:
            return SearchResult(self.name,query,self.status,[],None,"HTTP 429")
        return SearchResult(self.name,query,self.status,[
            SearchRecord(self.name,"ID-1","Bibliographic lead, eligibility unconfirmed",
                         url="https://doi.org/10.1000/example",doi="10.1000/example",year=2025),
        ],100 if self.status==SourceStatus.PARTIAL else 1,
        "partial pagination" if self.status==SourceStatus.PARTIAL else "")


def test_recheck_uses_exact_saved_pico_and_only_its_failed_sources():
    parent=parent_job()
    original=copy.deepcopy(parent)
    sources=[
        MockSource("OpenAlex"),MockSource("PROSPERO",SourceStatus.PARTIAL),
        MockSource("Europe PMC"),MockSource("Semantic Scholar",SourceStatus.ACCESS_FAILED),
        MockSource("PubMed"),
    ]
    result=recheck_saved_topic(parent,"CAND-ESRD-1",source_clients=sources)
    assert result["targeted_sources"]==[
        "OpenAlex","PROSPERO","Europe PMC","Semantic Scholar",
    ]
    assert sources[-1].calls==[]
    assert sources[0].calls
    assert all("occlusion" in query.lower() or "appendage" in query.lower()
               for query,_ in sources[0].calls)
    assert result["qualification_status_unchanged"] is True
    assert result["source_search_exhaustiveness"]=="NOT_ESTABLISHED"
    assert result["independent_eligible_primary_studies"]=="NOT_VERIFIED"
    assert all(x["targeted_search_status"] in {
        "TARGETED_QUERIES_COMPLETED_NOT_FULL_SEARCH_CLEARANCE",
        "TARGETED_QUERIES_INCOMPLETE",
    } for x in result["source_reports"])
    assert parent==original


def test_no_failed_sources_means_no_research_queries_or_new_clearance():
    parent=parent_job()
    topic=saved_topic(parent,"CAND-ESRD-1")
    statuses=topic["research_dossier"]["verification_and_quality"]["source_statuses"]
    for key in statuses: statuses[key]="SEARCHED_POSITIVE"
    result=recheck_saved_topic(parent,"CAND-ESRD-1",source_clients=[])
    assert result["targeted_sources"]==[]
    assert result["source_reports"]==[]
    assert result["qualification_status_unchanged"] is True


def test_missing_original_topic_never_runs_an_unscoped_search():
    parent=parent_job()
    with pytest.raises(ValueError,match="absent"):
        recheck_saved_topic(parent,"DIFFERENT-CANDIDATE",source_clients=[])


def test_failed_source_response_does_not_clear_its_original_status():
    parent=parent_job()
    sources=[MockSource("OpenAlex",SourceStatus.ACCESS_FAILED)]
    report=recheck_saved_topic(parent,"CAND-ESRD-1",
                               source_clients=sources,max_sources=1)
    assert report["targeted_sources"]==["OpenAlex"]
    assert report["source_reports"][0]["targeted_search_status"]=="TARGETED_QUERIES_INCOMPLETE"
    assert report["original_source_statuses"]["OpenAlex"]=="ACCESS_FAILED"
    assert report["source_reports"][0]["unrun_query_variants"]>0
    assert len(sources[0].calls)==1
    assert "PROSPERO" in report["remaining_originally_failed_sources_not_attempted"]


def test_worker_rejects_cross_browser_request_before_network_recheck():
    parent=parent_job()
    class FakeStore:
        def __init__(self):
            self.done=[]
        def claim_recheck(self):
            return {"id":"RECHECK-1","job_id":"JOB-1","candidate_id":"CAND-ESRD-1",
                    "client_token_hash":"other-device-hash"}
        def parent_job(self,job_id):
            assert job_id=="JOB-1"
            return parent
        def finish_recheck(self,id,result,*,error=""):
            self.done.append((id,result,error))
    store=FakeStore()
    assert run_once(store,source_clients=[])==1
    assert "owner does not match" in store.done[0][2]
    assert not store.done[0][1]


def test_question_scope_preserves_original_intervention_and_comparator():
    parent=parent_job()
    topic=saved_topic(parent,"CAND-ESRD-1")
    candidate=candidate_from_saved(parent,topic)
    plan=build_search_plan(candidate)
    assert query_plan_for_source("PROSPERO",plan)
    assert all(kind=="REGISTRATION" for kind,_ in query_plan_for_source("PROSPERO",plan))
    assert any("appendage" in query.casefold()
               for _,query in query_plan_for_source("Europe PMC",plan))
    assert candidate.comparator_reference=="Direct oral anticoagulants"
