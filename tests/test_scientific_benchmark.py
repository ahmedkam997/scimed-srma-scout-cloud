from scimed_scout.discovery.scientific_benchmark import paired_samples,sample_metrics,_candidate,exact_reference_audit
from scimed_scout.sources.base import SearchRecord,SearchResult
from scimed_scout.domain import SourceStatus

CASE={"id":"C","candidate":{"title":"Aspirin in primary prevention","specialty":"Cardiology","population":"Primary prevention","intervention_exposure_index_test":"Aspirin","eligible_designs":["RCT"],"search_terms":["aspirin","primary prevention"]},"primary":[{"pmid":"12345"}],"reviews":[{"pmid":"67890"}],"controls":[]}

class Stub:
    name="Europe PMC"
    def __init__(self):self.calls=[]
    def search(self,q,*,limit):
        self.calls.append(q)
        return SearchResult(self.name,q,SourceStatus.SEARCHED_POSITIVE,[SearchRecord(self.name,"12345","Aspirin primary prevention randomized trial",metadata={"source":"MED","pmid":"12345"})],1)

def test_reference_ids_are_not_discovery_inputs_and_budget_is_matched():
    c=Stub();r=paired_samples(_candidate(CASE),CASE,[c],cap=2,limit=8)
    assert all("12345" not in q and "67890" not in q for q in c.calls)
    assert r["LEGACY"]["primary"]["observed_reference_count"]==1
    assert all(a["queries_planned"]<=4 for a in r.values())
    assert r["OPTIMIZED"]["reviews"]["observed_reference_count"]==0

def test_incomplete_access_is_not_zero_recall():
    assert sample_metrics(["12345"],[],False)["sample_reference_retrieval_fraction"] is None
    assert sample_metrics(["12345"],[],True)["sample_reference_retrieval_fraction"]==0

def test_reference_lookup_is_independent_and_missing_labels_stay_unknown():
    r=exact_reference_audit(_candidate(CASE),CASE,Stub())
    assert r["retrieved_count"]==1
    assert r["items"][1]["citation_status"] is None
