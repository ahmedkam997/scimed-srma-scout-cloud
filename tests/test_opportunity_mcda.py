import math
from scimed_scout.discovery.opportunity_mcda import WEIGHTS,SCENARIOS,weighted_assessment,compare_assessments,profile
from scimed_scout.storage import CandidateRecord
from scimed_scout.discovery.review_opportunity import date_bounds
from scimed_scout.discovery.rct_first import MIN_FAMILIES
def test_weights_and_unknown_bounds():
    assert sum(WEIGHTS.values())==100 and all(sum(w.values())==100 for w in SCENARIOS.values())
    a=weighted_assessment({"clinical_importance":{"rating":5,"status":"PRELIMINARY"}})
    assert a["publication_oriented_score"] is None and a["documented_score_bounds"]==[0,100]
    assert a["exploratory_score_bounds"]==[15,100]
    assert not a["qualification_granted"]
def test_malformed_and_unsubstantiated_ratings_are_unknown():
    for v in [True,float("nan"),float("inf"),6,-1,"5"]:
        a=weighted_assessment({"clinical_importance":{"rating":v,"status":"ADJUDICATED","source_urls":["https://example.org"],"rationale":"evidence"}})
        assert a["domains"]["clinical_importance"]["status"]=="UNKNOWN"
    assert weighted_assessment({"clinical_importance":{"rating":5,"status":"ADJUDICATED"}})["publication_oriented_score"] is None
def test_complete_and_sensitive_ordering_never_qualifies():
    def score(n):
        return weighted_assessment({k:{"rating":n,"status":"ADJUDICATED","source_urls":["https://example.org"],"rationale":"fixture"} for k in WEIGHTS})
    a,b=score(4),score(3)
    assert a["publication_oriented_score"]==80 and not a["qualification_granted"]
    assert compare_assessments([("a",a),("b",b)])["robust_winner"]=="a"
    assert compare_assessments([("a",weighted_assessment()),("b",b)])["robust_winner"] is None
def test_direct_comparison_gap_profile_and_no_clearance():
    p=("hypertension","renal denervation",(),())
    rows=[{"title":f"Renal denervation versus sham in hypertension: trial {i}","source":"PubMed","source_record_id":str(i),"payload":{"year":2025,"url":f"https://pubmed.ncbi.nlm.nih.gov/{i}/","metadata":{"trial_registration_ids":[f"NCT{i:08d}"],"abstractText":"Blood pressure was evaluated."}}} for i in range(1,8)]
    review={"title":"Renal denervation versus sham in hypertension: systematic review","source":"PubMed","source_record_id":"99","payload":{"year":2024,"url":"https://pubmed.ncbi.nlm.nih.gov/99/","metadata":{"pubtype":["Systematic Review"],"abstractText":"METHODS: We searched PubMed through March 15, 2023.\nCONCLUSIONS: Evidence is insufficient for blood pressure."}}}
    other={**review,"title":"Aspirin in diabetes: systematic review","source_record_id":"98"}
    c=CandidateRecord("c","p","Topic","Cardiology",population=p[0],intervention_exposure_index_test=p[1],comparator_reference="sham",outcomes=["blood pressure"],metadata={"rct_first":{"pair":p,"comparison_records":rows,"family_leads":7,"competing_review_preflight":{"status":"SEARCHED_POSITIVE","records":[review,other]}}})
    a=profile(c)
    assert a["priority_key"][0]==1
    assert len(a["direct_comparison_review_sample"])==1
    assert a["source_linked_gap_cues"] and a["outcome_specific_hypotheses"]
    assert a["post_cutoff_report_cues"] and "UPDATE_SIGNAL" in a["routes"]
    assert a["assessment"]["publication_oriented_score"] is None and a["confirmed_independent_eligible_trials"] is None
    assert date_bounds("March 15, 2023")[0].isoformat()=="2023-03-15"
def test_no_review_is_not_novelty():
    c=CandidateRecord("c","p","Topic","Cardiology",metadata={"rct_first":{"family_leads":30}})
    a=profile(c)
    assert a["routes"]==["EXPLORATORY_SYNTHESIS_UNCERTAIN"]
    assert a["assessment"]["domains"]["research_gap_novelty"]["status"]=="UNKNOWN"

def test_strict_rct_cues_do_not_turn_into_final_go(tmp_path):
    from scimed_scout.discovery.orchestrator import ReviewDiscoveryOrchestrator
    from scimed_scout.domain import CandidateStatus,SourceStatus
    from scimed_scout.storage import ProjectRecord,SQLiteLedger
    from scimed_scout.sources.base import SearchRecord,SearchResult
    pair=("hypertension","renal denervation",(),())
    c=CandidateRecord("C","P","Renal denervation versus sham in hypertension","Cardiology","EFFECTIVENESS",
        population=pair[0],intervention_exposure_index_test=pair[1],comparator_reference="sham",
        outcomes=["blood pressure"],eligible_designs=["Randomized controlled trial"],
        metadata={"rct_first":{"pair":pair},"discovery_gate_inputs":{"design_framework_defined":True,"meaningful_synthesis_plausible":True,"clinical_question_novelty":5,"overall_novelty":5,"question_framework_coherent":True,"feasibility":"HIGH","fatal_methodological_flaw":False,"clinical_importance":5,"publication_potential":5,"new_information_gain":5,"publication_oriented_score":100,"editorial_grade":"A"}})
    class Source:
        def __init__(self,name):self.name=name
        def search(self,q,*,limit):
            result=[] if self.name not in ("PubMed","Europe PMC") or "systematic review" in q.casefold() or "meta-analysis" in q.casefold() else [
                SearchRecord(self.name,str(i),f"Renal denervation versus sham in hypertension: randomized trial {i}",year=2025,doi=f"10.1234/{i}",metadata={"pubtype":["Randomized Controlled Trial"],"trial_registration_ids":[f"NCT{i:08d}"]}) for i in range(1,8)]
            return SearchResult(self.name,q,SourceStatus.SEARCHED_POSITIVE if result else SourceStatus.SEARCHED_NEGATIVE,result,len(result))
    names=["PubMed","Europe PMC","OpenAlex","Crossref","Semantic Scholar","PROSPERO","OSF Registries","ClinicalTrials.gov"]
    with SQLiteLedger(tmp_path/"rct.sqlite3") as ledger:
        ledger.upsert_project(ProjectRecord("P","Cardiology","EFFECTIVENESS"))
        ledger.upsert_candidate(c)
        result=ReviewDiscoveryOrchestrator(ledger,[Source(n) for n in names],require_pico_signals=True,strict_rct_minimum=7).verify_candidate("C")
        assert ledger.get_candidate("C").metadata["rct_first_final_audit"]["family_leads"]==7
        assert result.candidate_status==CandidateStatus.PROVISIONAL_BACKUP
        assert any("independent eligibility" in p for p in result.pending)
        assert result.final_gate_result is None

def test_primary_research_need_does_not_become_synthesis_gap():
    p=("hypertension","renal denervation",(),())
    rev={"title":"Renal denervation versus sham in hypertension: systematic review","source":"PubMed","source_record_id":"99","payload":{"year":2025,"url":"https://pubmed.ncbi.nlm.nih.gov/99/","metadata":{"pubtype":["Systematic Review"],"abstractText":"Further randomized trials are needed."}}}
    c=CandidateRecord("c","p","Topic","Cardiology",population=p[0],intervention_exposure_index_test=p[1],comparator_reference="sham",outcomes=["blood pressure"],metadata={"rct_first":{"pair":p,"family_leads":7}})
    result=profile(c,[rev])
    assert "PRIMARY_RESEARCH_NEED_CUE" in result["routes"]
    assert "REVIEW_GAP_SIGNAL" not in result["routes"]
    assert result["priority_key"][2]==0
