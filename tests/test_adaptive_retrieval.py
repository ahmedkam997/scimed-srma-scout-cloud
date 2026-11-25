from scimed_scout.storage import CandidateRecord
from scimed_scout.sources.base import SearchRecord,SearchResult
from scimed_scout.domain import SourceStatus
from scimed_scout.discovery.focused_queries import focused_query
from scimed_scout.discovery.adaptive_retrieval import collect
from scimed_scout.sources.pubmed import PubMedSource
from scimed_scout.sources.http import JsonHttpClient

def candidate(pop="Adults with acute ischemic stroke due to large vessel occlusion",inter="Endovascular thrombectomy"):
    return CandidateRecord("C","P","topic","Neurology",population=pop,intervention_exposure_index_test=inter,eligible_designs=["RCT"])

def test_connector_fix_preserves_clinical_words():
    q=focused_query(candidate(),"PubMed","PRIMARY")
    assert '"due"[Title/Abstract]' not in q and '"to"[Title/Abstract]' not in q
    assert "large vessel occlusion" in q and "intraarterial treatment" in q
    q=focused_query(candidate("Chronic kidney disease","Early treatment"),"PubMed","PRIMARY")
    assert '"chronic"[Title/Abstract]' in q and '"early"[Title/Abstract]' in q

class Stub:
    name="PubMed"
    def __init__(self,fail=False,drift=False,total=200):
        self.calls=[];self.fail=fail;self.drift=drift;self.total=total
    def search(self,q,*,limit):
        self.calls.append(limit)
        if self.fail:return SearchResult(self.name,q,SourceStatus.ACCESS_FAILED,message="429")
        records=[SearchRecord(self.name,str(i),"Unclassified report") for i in range(min(limit,self.total))]
        return SearchResult(self.name,q,SourceStatus.SEARCHED_POSITIVE,records,self.total+(1 if self.drift and limit==50 else 0))

def test_adaptive_budget_and_dedup_no_clearance():
    stub=Stub();audit,records=collect(candidate(),"PRIMARY",("legacy",),[],stub)
    assert stub.calls==[25,50] and len(records)==50 and audit["source_calls"]==2
    assert not audit["coverage_clearance_allowed"] and not audit["eligibility_verified"]
    assert records[0].metadata["adaptive_pubmed"]["depth"]==25

def test_adaptive_stops_on_failure_small_count_and_ambiguity():
    for stub,access,expected in ((Stub(fail=True),True,[25]),(Stub(total=10),True,[25]),(Stub(),False,[])):
        audit,_=collect(candidate(),"PRIMARY",("legacy",),[],stub,base_access=access)
        assert stub.calls==expected
    stub=Stub();audit,_=collect(candidate("Stroke without diabetes"),"PRIMARY",("legacy",),[],stub)
    assert not stub.calls and audit["status"]=="NO_SAFE_QUERY"
    stub=Stub(drift=True);audit,records=collect(candidate(),"PRIMARY",("legacy",),[],stub)
    assert audit["status"]=="SUPPLEMENTARY_ACCESS_UNRESOLVED" and len(records)==50

def test_warning_zero_is_not_negative():
    bad={"esearchresult":{"count":"0","idlist":[],"warninglist":{"quotedphrasesnotfound":["due"]}}}
    c=PubMedSource(JsonHttpClient(loader=lambda _:bad,retries=0))
    assert c.search("x").status==SourceStatus.PARTIAL

def test_rank_drift_still_respects_hard_cap():
    class Drift(Stub):
        def search(self,q,*,limit):
            r=super().search(q,limit=limit)
            if limit==50:
                r.records=[SearchRecord(self.name,str(i),"Unclassified report") for i in range(1,51)]
            # return all 50 shifted records
            return r
    stub=Drift();audit,records=collect(candidate(),"PRIMARY",("legacy",),[],stub)
    assert len(records)==50
    assert audit["attempts"][-1]["rank_prefix_changed"]
    assert audit["attempts"][-1]["records_omitted_by_cap"]==1
    assert records[0].record_id=="0"

def test_broad_query_spends_remaining_slots_on_design_refinement():
    class Broad(Stub):
        def search(self,q,*,limit):
            self.calls.append((q,limit))
            start=100 if len(self.calls)>1 else 0
            return SearchResult(self.name,q,SourceStatus.SEARCHED_POSITIVE,[SearchRecord(self.name,str(i),"Unknown report") for i in range(start,start+limit)],200 if start else 3000)
    stub=Broad();audit,records=collect(candidate(),"PRIMARY",("legacy",),[],stub)
    assert len(records)==50 and len(stub.calls)==2
    assert stub.calls[1][1]==25 and "randomized controlled trial[pt]" in stub.calls[1][0]
    assert audit["attempts"][-1]["strategy"]=="DESIGN_PRIORITIZED"
