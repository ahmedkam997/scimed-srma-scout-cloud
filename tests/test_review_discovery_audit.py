from scimed_scout.sources.base import SearchRecord,SearchResult
from scimed_scout.domain import SourceStatus
from scimed_scout.storage import CandidateRecord,ProjectRecord,SQLiteLedger
from scimed_scout.discovery.evidence_classification import classify_review_search_hit,review_intervention_citation_signal
from scimed_scout.discovery.clinical_reranking import rank
from scimed_scout.discovery.orchestrator import ReviewDiscoveryOrchestrator
from scimed_scout.discovery.query_optimizer import _review_suffix
from scimed_scout.discovery.candidate_preflight import review_search_query

def candidate():
    return CandidateRecord("C","P","CGM for type 1 diabetes","Endocrinology",population="Adults with type 1 diabetes",intervention_exposure_index_test="Continuous glucose monitoring",eligible_designs=["RCT"])
def test_provider_shapes_and_false_reviews():
    for source,meta in (("PubMed",{"pubtype":["Meta-Analysis"]}),("Europe PMC",{"pubTypeList":{"pubType":["Systematic Review"]}}),("Semantic Scholar",{"publicationTypes":["MetaAnalysis","Review"]}),("Crossref",{"type":"journal-article"}),("OpenAlex",{"type":"review"})):
        title="Systematic review of diabetes" if source in ("Crossref","OpenAlex","Semantic Scholar") else "Diabetes evidence"
        assert classify_review_search_hit(SearchRecord(source,"1",title,metadata=meta))=="CONFIRMED_REVIEW_CUE"
    assert classify_review_search_hit(SearchRecord("Europe PMC","2","Diabetes evidence",metadata={"abstractText":"We systematically searched PubMed and Embase."}))=="CONFIRMED_REVIEW_CUE"
    for title,meta in (("Protocol for a systematic review",{}),("Systematic review: a protocol",{}),("Systematic review of diabetes",{"type":"peer-review"}),("Original diabetes study",{"abstractText":"A systematic review was previously published."})):
        assert classify_review_search_hit(SearchRecord("Europe PMC","2",title,metadata=meta))!="CONFIRMED_REVIEW_CUE"
    assert classify_review_search_hit(SearchRecord("OpenAlex","2","Diabetes care",metadata={"type":"review"}))=="NEEDS_BIBLIOGRAPHIC_CHECK"
def test_primary_search_recovers_competitor_and_alias():
    review=SearchRecord("PubMed","123","CGM in type 1 diabetes: systematic review")
    assert review_intervention_citation_signal(candidate(),review)=="INTERVENTION_IN_REVIEW_CITATION"
    class Stub:
        name="PubMed"
        def search(self,q,*,limit):return SearchResult(self.name,q,SourceStatus.SEARCHED_POSITIVE,[review],1)
    with SQLiteLedger(":memory:") as l:
        l.upsert_project(ProjectRecord("P","Endocrinology"));c=candidate();l.upsert_candidate(c)
        ReviewDiscoveryOrchestrator(l,[Stub()])._search_sources(c,("PubMed",),("q",),evidence_type="PRIMARY_STUDY",purpose="test",limit_per_query=12)
        assert len(l.list_external_evidence("C","PUBLISHED_REVIEW"))==1
        assert not l.list_external_evidence("C","PRIMARY_STUDY")
def test_rank_no_exclusion_deterministic_and_official_filter():
    rows=[{"title":"Green tea in hypertension: systematic review","source_record_id":"1"},{"title":"Continuous glucose monitoring in type 1 diabetes: systematic review","source_record_id":"2"},{"title":"","source_record_id":"3"}]
    ranked=rank(candidate(),rows)
    assert ranked[0]["record"]["source_record_id"]=="2"
    assert len(ranked)==len(rows) and rank(candidate(),rows)==ranked
    assert all(not x["eligibility_verified"] for x in ranked)
    assert rank(candidate(),[])==[]
    assert "systematic[sb]" in _review_suffix("PubMed") and "systematic[sb]" in review_search_query(candidate())

def test_correction_of_clinical_condition_not_erratum_and_camel_case():
    assert classify_review_search_hit(SearchRecord("PubMed","x","Surgical correction of scoliosis: systematic review"))=="CONFIRMED_REVIEW_CUE"
    assert classify_review_search_hit(SearchRecord("Semantic Scholar","x","Clinical evidence",metadata={"publicationTypes":["MetaAnalysis"]}))=="CONFIRMED_REVIEW_CUE"
    assert classify_review_search_hit(SearchRecord("PubMed","x","Correction: systematic review of treatment"))=="PRIMARY_OR_NONREVIEW"
