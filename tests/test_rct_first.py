from scimed_scout.discovery.rct_first import comparison_rows,family_summary,collect,strict_candidate_audit,should_route
from scimed_scout.cloud.rct_worker import BoundedProvider,process_rct_job
from scimed_scout.sources.base import SearchRecord,SearchResult
from scimed_scout.domain import SourceStatus
from scimed_scout.storage import CandidateRecord
from scimed_scout.ai.providers import ProviderFailure
import pytest

PAIR=("hypertension","renal denervation",(),())
def record(n,title=None,reg=None):
    return SearchRecord("PubMed",str(n),title or f"Renal denervation versus sham in hypertension: randomized trial {n}",year=2025,metadata={"pubtype":["Randomized Controlled Trial"],"trial_registration_id":reg or f"NCT{n:08d}"})
def rows(records):
    from scimed_scout.discovery.evidence_first import _record
    return [_record(r) for r in records]
def test_comparison_not_generic_rct_count():
    items=[record(i) for i in range(1,8)]+[record(8,"Renal denervation in hypertension: randomized trial"),record(9,"Renal denervation versus sham in hypertension: meta-analysis"),record(10,"Renal denervation versus sham in hypertension: secondary analysis"),record(11,reg="NCT00000001")]
    all_r,comp=comparison_rows(PAIR,rows(items))
    assert family_summary(comp["sham"])["family_leads"]==7
    assert family_summary(all_r)["family_leads"]==8
    assert family_summary(comp["sham"])["confirmed_independent_eligible_trials"] is None
def test_no_comparator_invented_and_exact_family_threshold():
    c=CandidateRecord("C","P","Trial","Cardiology",population="hypertension",intervention_exposure_index_test="renal denervation",comparator_reference="placebo",eligible_designs=["Randomized controlled trial"],metadata={"rct_first":{"pair":PAIR}})
    assert strict_candidate_audit(c,rows([record(i) for i in range(1,8)]))["family_leads"]==0
    c.comparator_reference="sham"
    assert strict_candidate_audit(c,rows([record(i) for i in range(1,8)]))["family_leads"]==7
def test_seed_bounded_and_rct_only():
    class Source:
        name="PubMed"
        def __init__(self):self.calls=[]
        def search(self,q,*,limit):
            self.calls.append(q)
            rr=[record(i) for i in range(1,9)] if "renal denervation" in q else []
            return SearchResult(self.name,q,SourceStatus.SEARCHED_POSITIVE if rr else SourceStatus.SEARCHED_NEGATIVE,rr,len(rr))
    p=Source();e=Source();e.name="Europe PMC"
    r=collect("Cardiology",pubmed=p,europe=e,year=2026)
    assert len(p.calls)<=9 and len(e.calls)<=2 and r["new_ai_requests"]==0
    assert r["candidates"] and all(c["eligible_designs"]==["Randomized controlled trial"] for c in r["candidates"])
    assert r["candidates"][0]["metadata"]["rct_first"]["shortlist_eligible"]
    assert should_route("Cardiology","ALL") and not should_route("Cardiology","DIAGNOSTIC_ACCURACY")
def test_budget_no_provider_calls_after_limit():
    class Provider:
        configured_free_route=["free"];unavailable_free_providers=[]
        def complete(self,r):return object()
        def routing_snapshot(self):return {}
    p=BoundedProvider(Provider(),limit=3,per_topic=2)
    p.begin("A");p.complete(None);p.complete(None)
    with pytest.raises(ProviderFailure):p.complete(None)
    p.begin("B");p.complete(None)
    with pytest.raises(ProviderFailure):p.complete(None)
    assert p.requests==3 and p.deferred==2
def test_no_evidence_no_ai_no_deep():
    from scimed_scout.cloud.supabase import DiscoveryJob
    class Store:
        def __init__(self):self.steps={}
        def ensure_active(self,i):pass
        def recent_completed_jobs(self,**kw):return []
        def load_step(self,i,k):return self.steps.get(k)
        def save_step(self,i,k,v):self.steps[k]=v
        def update_job(self,*a,**kw):pass
    store=Store()
    def empty(*a,**kw):return {"version":"RCT_FIRST_V1","status":"SAMPLED","queries":[],"cells":[],"candidates":[]}
    def no_ai():raise RuntimeError("No configured provider")
    job=DiscoveryJob("J","Cardiology","ALL")
    result=process_rct_job(job,store,collector=empty,clients=[],router_factory=no_ai)
    assert not result["package"]["options"] and result["run_summary"]["verified_candidates"]==0
    assert result["run_summary"]["ai_telemetry"]["logical_requests"]==0
    def forbidden(*a,**kw):raise AssertionError("seed search repeated")
    result=process_rct_job(job,store,collector=forbidden,clients=[],router_factory=no_ai)
    assert result["run_summary"]["mode"]=="RCT_FIRST_V1"

def test_comparator_requires_actual_comparison_not_background_medication():
    from scimed_scout.discovery.rct_first import explicit_comparison
    assert explicit_comparison("Renal denervation versus sham in hypertension: randomized trial",("renal denervation",),"sham")
    assert not explicit_comparison("Renal denervation versus sham in patients receiving aspirin",("renal denervation",),"aspirin")
    assert not explicit_comparison("Randomized trial of renal denervation in hypertension with aspirin use",("renal denervation",),"aspirin")
    assert explicit_comparison("We randomized patients to renal denervation or sham",("renal denervation",),"sham")
def test_unsupported_scope_does_not_fall_back_to_mixed_design():
    assert should_route("Dermatology","ALL")
    assert collect("Dermatology")["status"]=="UNSUPPORTED_SPECIALTY"

def test_efetch_identity_and_registry_data():
    from scimed_scout.sources.pubmed_abstracts import enrich_rows,parse_efetch
    xml=b'<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>1</PMID><Article><ArticleTitle>Original trial</ArticleTitle><Abstract><AbstractText Label="METHODS">We randomized patients with hypertension to renal denervation or sham.</AbstractText></Abstract><PublicationTypeList><PublicationType>Randomized Controlled Trial</PublicationType></PublicationTypeList><DataBankList><DataBank><DataBankName>ClinicalTrials.gov</DataBankName><AccessionNumberList><AccessionNumber>NCT00000001</AccessionNumber></AccessionNumberList></DataBank></DataBankList></Article></MedlineCitation></PubmedArticle></PubmedArticleSet>'
    original=rows([record(1,"Renal denervation in hypertension"),record(2)])
    out,audit=enrich_rows(None,original,fetcher=lambda ids:xml)
    assert audit["status"]=="PARTIAL" and audit["abstracts_retrieved"]==1 and audit["registry_id_records"]==1
    assert out[0]["payload"]["metadata"]["abstractText"].startswith("METHODS:")
    assert out[1]==original[1]
    _,buckets=comparison_rows(PAIR,out)
    assert family_summary(buckets["sham"])["family_leads"]==2
    wrong=xml.replace(b"<PMID>1</PMID>",b"<PMID>999</PMID>")
    out,audit=enrich_rows(None,original,fetcher=lambda ids:wrong)
    assert out==original and audit["unexpected_pmids"]==1
    with pytest.raises(ValueError):parse_efetch(b'<!DOCTYPE x [<!ENTITY y "bad">]><x/>',{"1"})


def test_comparison_recovery_and_exact_shortlist():
    class Source:
        name="PubMed"
        def search(self,q,*,limit):
            records=[]
            if "renal denervation" in q and "systematic[sb]" not in q:
                records=[record(i) for i in range(1,7)]
                records += [record(20,"Renal denervation in hypertension: randomized trial"),record(21,"Renal denervation in hypertension: randomized trial 21")]
                if '"sham"[tiab]' in q:records=[record(i) for i in range(1,8)]
            return SearchResult(self.name,q,SourceStatus.SEARCHED_POSITIVE if records else SourceStatus.SEARCHED_NEGATIVE,records,len(records))
    class Empty:
        name="Europe PMC"
        def search(self,q,*,limit):return SearchResult(self.name,q,SourceStatus.SEARCHED_NEGATIVE,[],0)
    report=collect("Cardiology",pubmed=Source(),europe=Empty(),year=2026,max_pairs=1)
    assert report["comparison_recovery"][0]["before_family_cues"]==6
    assert report["comparison_recovery"][0]["after_family_cues"]==7
    assert report["candidates"][0]["metadata"]["rct_first"]["shortlist_eligible"]
    class NoRecovery(Source):
        def search(self,q,*,limit):
            if '"sham"[tiab]' in q:return SearchResult(self.name,q,SourceStatus.SEARCHED_NEGATIVE,[],0)
            return super().search(q,limit=limit)
    report=collect("Cardiology",pubmed=NoRecovery(),europe=Empty(),year=2026,max_pairs=1)
    info=report["candidates"][0]["metadata"]["rct_first"]
    assert info["population_intervention_family_leads"]>=7 and info["family_leads"]==6
    assert not info["shortlist_eligible"]
