from scimed_scout.discovery.adaptive_search import citation_neighbors,collect
from scimed_scout.discovery.rct_first import collect as rct_collect
from scimed_scout.domain import SourceStatus
from scimed_scout.sources.base import SearchRecord,SearchResult
from scimed_scout.storage import CandidateRecord
import pytest

class Graph:
    name="Europe PMC"
    def __init__(self):
        self.http=self
        self.calls=[]
    def get_json(self,url,params):
        self.calls.append(url)
        key="reference" if url.endswith("/references") else "citation"
        ids=range(10,22) if key=="reference" else range(30,42)
        return {"hitCount":12,key+"List":{key:[{"source":"MED","id":str(i)} for i in ids]}}
    def search(self,q,*,limit):
        self.calls.append(q)
        if "EXT_ID:" not in q:return SearchResult(self.name,q,SourceStatus.SEARCHED_NEGATIVE,[],0)
        return SearchResult(self.name,q,SourceStatus.SEARCHED_POSITIVE,[
            SearchRecord(self.name,"10","Renal denervation versus sham in hypertension: randomized trial",year=2025,metadata={"source":"MED","pmid":"10","pubtype":["Randomized Controlled Trial"],"trial_registration_id":"NCT00000010"}),
            SearchRecord(self.name,"30","Renal denervation versus sham in hypertension: systematic review",year=2025,metadata={"source":"MED","pmid":"30"}),
            SearchRecord(self.name,"11","Conflicting PMID",metadata={"source":"MED","pmid":"999"}),
            SearchRecord(self.name,"999","Unexpected PMID",metadata={"source":"MED","pmid":"999"})],4)

def test_graph_balances_directions_and_rejects_wrong_identity():
    c=Graph()
    audit,records=citation_neighbors(c,["1","1"],[])
    assert audit["source_calls"]==3
    assert audit["hydration"]["requested_pmids"][:4]==["10","30","11","31"]
    assert {r.record_id for r in records}=={"10","30"}
    assert audit["status"]=="PARTIAL_LINK_SAMPLE"
    assert not audit["coverage_clearance_allowed"]
    assert records[1].metadata["supplementary_citation_link"]["edges"]==[{"seed_pmid":"1","direction":"FORWARD"}]

def test_cancel_propagates_and_stops_network():
    c=Graph()
    def cancel():raise RuntimeError("cancelled")
    with pytest.raises(RuntimeError,match="cancelled"):
        citation_neighbors(c,["1"],check=cancel)
    assert not c.calls

def test_rate_limit_is_not_negative_and_defers_other_calls():
    class Limited(Graph):
        def get_json(self,url,params):
            self.calls.append(url)
            raise RuntimeError("HTTP Error 429")
    c=Limited()
    audit,records=citation_neighbors(c,["1","2"],max_seeds=2)
    assert audit["source_calls"]==1 and not records
    assert audit["status"]=="PARTIAL_LINK_SAMPLE"
    assert audit["citation_search"][0]["rate_limited"]

def test_rct_seed_graph_preserves_trial_floor_and_competing_review():
    class Pub:
        name="PubMed"
        def search(self,q,*,limit):
            items=[] if "systematic review" in q.lower() or "meta-analysis" in q.lower() else [
                SearchRecord(self.name,str(i),f"Renal denervation versus sham in hypertension: randomized trial {i}",year=2025,
                    metadata={"pubtype":["Randomized Controlled Trial"],"trial_registration_id":f"NCT{i:08d}"}) for i in range(1,7)]
            return SearchResult(self.name,q,SourceStatus.SEARCHED_POSITIVE if items else SourceStatus.SEARCHED_NEGATIVE,items,len(items))
    report=rct_collect("Cardiology",pubmed=Pub(),europe=Graph(),year=2026,max_pairs=1,citation=True)
    assert report["citation_recovery"]["source_calls"]==3
    item=next(x for x in report["candidates"] if x["comparator_reference"]=="sham")
    info=item["metadata"]["rct_first"]
    assert info["family_leads"]==7 and info["shortlist_eligible"]
    assert info["confirmed_independent_eligible_trials"] is None
    assert any(x["source_record_id"]=="30" for x in info["competing_review_preflight"]["records"])
    assert not info["novelty_confirmed"]
    assert report["new_ai_requests"]==0
