from scimed_scout.discovery.adaptive_search import harvest,refinement,direct_links,collect
from scimed_scout.discovery.query_optimizer import optimized_queries
from scimed_scout.storage import CandidateRecord
from scimed_scout.sources.base import SearchResult,SearchRecord
from scimed_scout.domain import SourceStatus

def candidate():
    return CandidateRecord("C","P","Empagliflozin HFpEF","Cardiology",
        population="Heart failure with preserved ejection fraction",
        intervention_exposure_index_test="Empagliflozin",eligible_designs=["RCT"])

def row(pmid,title,abstract="",kind="PUBLISHED_REVIEW"):
    return {"source":"Europe PMC","source_record_id":pmid,"evidence_type":kind,"title":title,
            "payload":{"metadata":{"pmid":pmid,"source":"MED","abstractText":abstract,
            "meshHeadingList":{"meshHeading":[{"descriptorName":"Diabetes Mellitus"}]}}}}

def test_emperor_preserved_article_phrase_is_retained():
    q=optimized_queries(candidate(),"PubMed","PRIMARY",("empagliflozin",))[0]
    assert '"heart failure with a preserved ejection fraction"[Title/Abstract]' in q
    assert '"Heart Failure"[MeSH Terms]' not in q

def test_mesh_harvest_is_provenance_not_an_automatic_synonym():
    rows=[row(str(i),"Empagliflozin in HFpEF") for i in (1,2)]
    audit=harvest(candidate(),rows)
    assert audit["mesh_observations"]==[{"heading":"Diabetes Mellitus","support_pmids":["1","2"],"synonym_verified":False}]
    assert harvest(candidate(),[rows[0],rows[0]])["mesh_observations"]==[]

def test_precision_refinement_keeps_both_anchors_and_no_eligibility_inference():
    q,reason,_=refinement(candidate(),[row(str(i),"Empagliflozin in HFpEF") for i in range(8)],{"pico_design_family_leads":0})
    assert reason=="TITLE_POPULATION_REFINEMENT"
    assert "TITLE:" in q and 'TITLE_ABS:"empagliflozin"' in q and " AND " in q
    assert refinement(candidate(),[],{"pico_design_family_leads":99})[0]==""

class Client:
    def __init__(self):
        self.http=self
        self.calls=[]
    def get_json(self,url,params):
        self.calls.append(url)
        key="reference" if url.endswith("/references") else "citation"
        return {"hitCount":3,key+"List":{key:[{"id":"10","source":"MED","title":"Potential related report"},
            {"id":"11","source":"MED","title":"Other report"},{"id":"77","source":"AGR","title":"Not PubMed"}]}}
    def search(self,q,*,limit):
        self.calls.append(q)
        return SearchResult("Europe PMC",q,SourceStatus.SEARCHED_POSITIVE,
            [SearchRecord("Europe PMC","10","Empagliflozin trial",metadata={"source":"MED","pmid":"10"}),
             SearchRecord("Europe PMC","999","Unexpected",metadata={"source":"MED","pmid":"999"})],2)

def test_direct_citation_search_bounded_and_exact_hydration():
    client=Client()
    review=row("1","Empagliflozin in HFpEF: systematic review")
    audit,results=collect(candidate(),[],[review],client)
    assert audit["source_calls"]==3
    assert not audit["coverage_clearance_allowed"]
    assert len(audit["citation_search"])==2
    assert audit["hydration"]["requested_pmids"]==["10","11"]
    assert audit["hydration"]["retrieved_pmids"]==["10"]
    assert results[0][2][0].metadata["supplementary_citation_link"]["directions"]==["BACKWARD","FORWARD"]

def test_unavailable_endpoint_not_treated_as_zero():
    class Broken:
        def __init__(self):self.http=self
        def get_json(self,*args):raise TimeoutError()
    r=direct_links(Broken(),"123","references")
    assert r["status"]=="ACCESS_UNRESOLVED" and r["reported_count"] is None


def test_new_abbreviation_requires_two_distinct_source_records():
    c=CandidateRecord("C","P","Colchicine in CAD","Cardiology",
        population="Coronary artery disease",intervention_exposure_index_test="Colchicine")
    rows=[row(str(x),"Colchicine in coronary artery disease (CAD)") for x in (1,2)]
    assert harvest(c,[rows[0],rows[0]])["abbreviations"]==[]
    q,reason,audit=refinement(c,rows,{"pico_design_family_leads":0})
    assert reason=="OBSERVED_ABBREVIATION_EXPANSION"
    assert 'TITLE_ABS:"CAD"' in q and 'TITLE_ABS:"colchicine"' in q
    assert audit["abbreviations"][0]["support_pmids"]==["1","2"]
