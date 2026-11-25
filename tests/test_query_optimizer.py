from scimed_scout.storage import CandidateRecord,ProjectRecord,SQLiteLedger
from scimed_scout.discovery.query_optimizer import optimized_queries,sample_quality
from scimed_scout.verification.queries import build_search_plan
from scimed_scout.discovery.orchestrator import ReviewDiscoveryOrchestrator
from scimed_scout.sources.base import SearchResult,SearchRecord
from scimed_scout.domain import SourceStatus

def candidate(pop="Adults with recent myocardial infarction",intervention="Oral low-dose colchicine (0.5 mg daily)"):
    return CandidateRecord("C","P","Clinical topic","Cardiology",population=pop,
        intervention_exposure_index_test=intervention,search_terms=["colchicine","myocardial infarction"])

def test_compiler_keeps_pi_and_verified_mesh_within_budget():
    c=candidate();plan=build_search_plan(c)
    p=optimized_queries(c,"PubMed","PRIMARY",plan.primary_queries,max_queries=4)
    assert 1<=len(p)<=4
    assert '"Myocardial Infarction"[MeSH Terms]' in p[0] and '"Colchicine"[MeSH Terms]' in p[0]
    assert " AND " in p[0] and " OR " in p[0]
    e=optimized_queries(c,"Europe PMC","REVIEW",plan.review_queries,max_queries=3)
    assert "TITLE_ABS:" in e[0] and "PUB_TYPE:" in e[0] and "[MeSH" not in e[0]
    assert len(e)<=3

def test_subtype_and_named_drug_not_replaced_by_broad_class():
    c=candidate("Heart failure with preserved ejection fraction","Empagliflozin")
    p=optimized_queries(c,"PubMed","PRIMARY",("empagliflozin","heart failure"),max_queries=2)
    assert "HFpEF" in p[0] and "empagliflozin" in p[0]
    assert '"Heart Failure"[MeSH Terms]' not in p[0]
    assert "Sodium-Glucose Transporter 2 Inhibitors" not in p[0]

def test_unknown_or_negated_scope_preserves_legacy():
    c=candidate("Heart failure without diabetes","Empagliflozin or dapagliflozin")
    old=("original clinical search","second variant")
    assert optimized_queries(c,"PubMed","PRIMARY",old)==old
    assert optimized_queries(c,"OpenAlex","PRIMARY",old)==old

def test_sample_quality_does_not_infer_absence():
    empty=SearchResult("PubMed","q",SourceStatus.SEARCHED_NEGATIVE,[],0)
    assert sample_quality(empty)["sample_status"]=="ZERO_QUERY_HITS_NOT_ZERO_EVIDENCE"
    bad=SearchResult("PubMed","q",SourceStatus.SEARCHED_POSITIVE,[],30)
    assert sample_quality(bad)["sample_status"]=="METADATA_INCOMPLETE"
    assert not sample_quality(bad)["eligibility_verified"]

def test_production_plan_is_source_specific_and_logged(tmp_path):
    class Stub:
        def __init__(self,name):self.name=name;self.calls=[]
        def search(self,q,*,limit):
            self.calls.append(q)
            return SearchResult(self.name,q,SourceStatus.SEARCHED_NEGATIVE,[],0)
    a,b=Stub("PubMed"),Stub("Europe PMC")
    with SQLiteLedger(tmp_path/"query.sqlite") as ledger:
        ledger.upsert_project(ProjectRecord("P","Cardiology"))
        c=candidate();ledger.upsert_candidate(c)
        engine=ReviewDiscoveryOrchestrator(ledger,[a,b],optimize_literature_queries=True)
        engine._search_sources(c,("PubMed","Europe PMC"),("colchicine","myocardial infarction"),
            evidence_type="PRIMARY_STUDY",purpose="test",limit_per_query=4)
        assert len(a.calls)==len(b.calls)==2
        assert "[MeSH Terms]" in a.calls[0]
        assert "TITLE_ABS:" in b.calls[0]
        logs=ledger.list_search_log("C")
        assert len(logs)==4
        assert all("CLINICAL_QUERY_OPTIMIZER_V1" in x.message for x in logs)
