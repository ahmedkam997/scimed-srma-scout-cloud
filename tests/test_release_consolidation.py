import json
from scimed_scout.domain import SourceStatus
from scimed_scout.sources.base import SearchRecord,SearchResult
from scimed_scout.sources.http import JsonHttpClient
from scimed_scout.sources.clinicaltrials import ClinicalTrialsGovSource
from scimed_scout.sources.europe_pmc import EuropePMCSource
from scimed_scout.sources.openalex import OpenAlexSource
from scimed_scout.sources.crossref import CrossrefSource
from scimed_scout.sources.semantic_scholar import SemanticScholarSource
from scimed_scout.storage import CandidateRecord,ProjectRecord,SQLiteLedger
from scimed_scout.discovery.orchestrator import ReviewDiscoveryOrchestrator
from scimed_scout.discovery.adaptive_retrieval import collect
from scimed_scout.discovery.open_access_dates import OpenAccessSearchDateResolver,extract_search_date

def candidate():
    return CandidateRecord("C","P","CGM for diabetes","Endocrinology",population="Type 1 diabetes",intervention_exposure_index_test="Continuous glucose monitoring")
class Stub:
    name="PubMed"
    def __init__(self):self.calls=[]
    def search(self,q,*,limit):
        self.calls.append(limit)
        return SearchResult(self.name,q,SourceStatus.SEARCHED_POSITIVE,[SearchRecord("PubMed","123","Pump or sensor first? A meta-analysis",metadata={"pubtype":["Meta-Analysis"]})],1)
def test_missing_lexical_signal_does_not_discard_biomedical_review():
    with SQLiteLedger(":memory:") as l:
        c=candidate();l.upsert_project(ProjectRecord("P","Endocrinology"));l.upsert_candidate(c)
        engine=ReviewDiscoveryOrchestrator(l,[Stub()])
        engine._search_sources(c,("PubMed",),("q",),evidence_type="PUBLISHED_REVIEW",purpose="test",limit_per_query=12)
        assert len(l.list_external_evidence("C","PUBLISHED_REVIEW"))==1
def test_review_count_no_longer_suppresses_supplemental_search():
    client=Stub();baseline=[{"source_record_id":str(i),"payload":{}} for i in range(20)]
    report,rows=collect(candidate(),"REVIEW",("q",),baseline,client)
    assert client.calls==[25] and len(rows)==1 and report["source_calls"]==1
    assert not report["coverage_clearance_allowed"]
def test_partial_later_page_keeps_registry_records():
    def load(url):
        if "pageToken=" in url:raise RuntimeError("timeout")
        return {"totalCount":2,"studies":[{"protocolSection":{"identificationModule":{"nctId":"NCT00000001","briefTitle":"Trial"}}}],"nextPageToken":"NEXT"}
    r=ClinicalTrialsGovSource(JsonHttpClient(loader=load,retries=0)).search("q")
    assert r.status==SourceStatus.PARTIAL and len(r.records)==1
def test_empty_positive_samples_not_conclusive():
    for cls,raw in [(EuropePMCSource,{"hitCount":3,"resultList":{"result":[]}}),(OpenAlexSource,{"meta":{"count":3},"results":[]}),(CrossrefSource,{"message":{"total-results":3,"items":[]}}),(SemanticScholarSource,{"total":3,"data":[]})]:
        assert cls(JsonHttpClient(loader=lambda _:raw,retries=0)).search("q").status==SourceStatus.PARTIAL
def test_date_identity_and_bioc_fallback():
    review={"source":"PubMed","source_record_id":"123","payload":{"year":2025,"metadata":{"pmcid":"PMC1234567"}}}
    wrong=b'<article><front><article-meta><article-id pub-id-type="pmid">999</article-id></article-meta></front><body><sec><title>Methods</title><p>We searched through January 2024.</p></sec></body></article>'
    bioc=json.dumps([{"documents":[{"id":"1234567","passages":[{"infons":{"section_type":"METHODS","article-id_pmid":"123"},"text":"The last search was conducted on 15 March 2023."},{"infons":{"section_type":"DISCUSS"},"text":"We searched through January 2025."}]}]}]).encode()
    def fetch(url):return bioc if "BioC_json" in url else wrong
    r=OpenAccessSearchDateResolver(fetcher=fetch).resolve(review)
    assert r["date"]=="15 March 2023" and r["source_type"].startswith("NCBI_BIOC")
    assert OpenAccessSearchDateResolver(fetcher=lambda _:wrong).resolve(review) is None
    assert extract_search_date("We searched through 12/03/2024.") is None
    assert extract_search_date("We searched through February 2024. We searched through January 2024.")["date"]=="February 2024"
