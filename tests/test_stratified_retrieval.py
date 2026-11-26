from datetime import date
from scimed_scout.discovery.stratified_retrieval import windows,collect
from scimed_scout.discovery.registry_reference_suggestions import suggest
from scimed_scout.sources.base import SearchRecord,SearchResult
from scimed_scout.domain import SourceStatus

def test_stratified_budget_and_disjoint_dates():
    spans=windows(date(1800,1,1),date(2026,11,26))
    assert spans==[(date(2022,1,1),date(2026,11,26)),(date(2012,1,1),date(2021,12,31)),(date(1800,1,1),date(2011,12,31))]
    class Client:
        def search(self,q,*,limit):
            assert limit==20
            return SearchResult("PubMed",q,SourceStatus.SEARCHED_POSITIVE,[SearchRecord("PubMed","1","A")],100)
    audit,rows=collect(Client(),"a",end=date(2026,11,26))
    assert audit["source_calls"]==3 and len(rows)==1 and not audit["coverage_clearance_allowed"]

def test_rate_limit_stops_strata():
    class Client:
        def search(self,q,*,limit):
            return SearchResult("PubMed",q,SourceStatus.ACCESS_FAILED,message="429")
    audit,rows=collect(Client(),"a")
    assert audit["source_calls"]==1 and audit["status"]=="PARTIAL_SAMPLE" and not rows

def test_result_reference_is_suggestion_not_merge_and_ignores_background():
    a={"source":"PubMed","source_record_id":"1","payload":{"metadata":{"trial_registration_id":"NCT00000001"}}}
    b={"source":"PubMed","source_record_id":"2","payload":{"metadata":{}}}
    c={"source":"PubMed","source_record_id":"3","payload":{"metadata":{}}}
    def lookup(n):
        return {"protocolSection":{"identificationModule":{"nctId":n},"referencesModule":{"references":[{"pmid":"2","type":"RESULT"},{"pmid":"3","type":"BACKGROUND"}]}}}
    audit=suggest([a,b,c],lookup=lookup)
    assert audit["suggestions"][0]["pmid"]=="2" and len(audit["suggestions"])==1 and not audit["automatic_merge"]
    assert b["payload"]["metadata"]=={}
    assert not suggest([a,b],lookup=lambda n:lookup("NCT00000099"))["suggestions"]

def test_pubmed_exact_pmc_identity():
    from scimed_scout.sources.pubmed_abstracts import parse_efetch
    raw=b'<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>1</PMID><Article><ArticleTitle>A</ArticleTitle></Article></MedlineCitation><PubmedData><ArticleIdList><ArticleId IdType="pmc">PMC123456</ArticleId></ArticleIdList></PubmedData></PubmedArticle></PubmedArticleSet>'
    assert parse_efetch(raw,["1"])[0]["1"]["pmcid"]=="PMC123456"


def test_review_small_set_completion_preserves_first_and_bounds_second():
    from scimed_scout.discovery.rct_first import review_title_recovery
    class Client:
        name="PubMed"
        def __init__(self,total):self.total=total;self.calls=[]
        def search(self,q,*,limit):
            self.calls.append(limit)
            return SearchResult(self.name,q,SourceStatus.SEARCHED_POSITIVE,[SearchRecord(self.name,str(i+1),"Review") for i in range(min(self.total,limit))],self.total)
    pair=("atrial fibrillation","pulsed field ablation",(),())
    client=Client(43);audits=[]
    rows=review_title_recovery(client,pair,"thermal ablation",audits,None)
    assert client.calls==[30,43] and len(rows)==43
    client=Client(100)
    assert len(review_title_recovery(client,pair,"thermal ablation",[],None))==30
    assert client.calls==[30]
