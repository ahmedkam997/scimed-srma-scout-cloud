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
