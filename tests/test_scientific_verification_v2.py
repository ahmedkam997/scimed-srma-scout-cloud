"""Independent synthetic controls, not real clinical studies.
No synthetic approval or test key is used in production.
"""
from copy import deepcopy
import pytest
from scimed_scout.discovery.scientific_verification_v2 import snapshot,evaluate,signature,pool,TrustedDirectory,digest,effect
from scimed_scout.discovery.orchestrator import ReviewDiscoveryOrchestrator
from scimed_scout.storage import SQLiteLedger,ProjectRecord,CandidateRecord,SearchLogRecord
from scimed_scout.domain import CandidateStatus,SourceStatus
from scimed_scout.verification.policy import policy_for_question_type
from scimed_scout.verification.coverage import evaluate_coverage
from scimed_scout.discovery.models import DiscoveryRunResult
from scimed_scout.discovery.review_package import build_discovery_review_package
import json

KEYS={"reviewer-a":b"a"*32,"reviewer-b":b"b"*32}
REVIEWERS=list(KEYS)
def e(url):return {"url":url,"locator":"Synthetic fixture table","excerpt":"Synthetic fixture only"}
def make_ledger(path,*,competitor=False):
    ledger=SQLiteLedger(path)
    ledger.upsert_project(ProjectRecord("p","Cardiology","EFFECTIVENESS"))
    c=CandidateRecord("c","p","Synthetic PICO","Cardiology",question_type="EFFECTIVENESS",population="Adults",intervention_exposure_index_test="Test treatment",comparator_reference="Placebo",outcomes=["death"],eligible_designs=["RCT"])
    ledger.upsert_candidate(c)
    for n in range(1,8):
        ledger.upsert_external_evidence("c","PRIMARY_STUDY",str(n),source="PubMed",title=f"Synthetic report {n}",payload={"url":f"https://pubmed.ncbi.nlm.nih.gov/{n}/","year":2025})
    if competitor:
        ledger.upsert_external_evidence("c","PUBLISHED_REVIEW","100",source="PubMed",title="Synthetic prior review",payload={"url":"https://pubmed.ncbi.nlm.nih.gov/100/","year":2024})
    for name in ("PubMed","Europe PMC","PROSPERO","OSF Registries","ClinicalTrials.gov"):
        ledger.append_search_log(SearchLogRecord("p","c",name,"synthetic query",SourceStatus.SEARCHED_POSITIVE,7))
    return ledger,c

def make_submission(packet,*,update=False):
    p=packet["verification_v2"];s=deepcopy(p["reviewer_submission_template"])
    for n in range(1,8):
        url=f"https://pubmed.ncbi.nlm.nih.gov/{n}/"
        s["studies"].append({"study_id":f"study-{n}","report_ids":[f"PubMed:{n}"],"registry_ids":[],"design":"RCT","population":"Adults","intervention_arm":"Test treatment","comparator_arm":"Placebo","independence_basis":"Distinct synthetic population","eligibility_evidence":e(url),"reviewers":REVIEWERS,"full_text_checked":True,"pico_eligible":True,"randomization_confirmed":True,"independent_population_confirmed":True,"first_report_date":"2025-01-01" if n>5 else "2023-01-01","first_report_date_evidence":e(url)})
        s["outcomes"].append({"study_id":f"study-{n}","report_id":f"PubMed:{n}","outcome":"death","definition":"all-cause","timepoint":"1 year","measure":"LOG_HR","effect":-0.05 if n<=5 else -0.9,"se":0.2,"evidence":e(url),"reviewers":REVIEWERS})
    fields={k:s["outcomes"][0][k] for k in ("outcome","definition","timepoint","measure")}
    s["synthesis_group"]={**fields,"compatibility_evidence":e("https://example.org/synthetic-method"),"method_and_heterogeneity_evidence":e("https://example.org/synthetic-analysis-plan"),"parallel_individual_randomization":True}
    s["ratings"]={k:5 for k in ("clinical_question_novelty","overall_novelty","new_information_gain","clinical_importance","publication_potential")}
    s["ratings"].update(design_framework_defined=True,meaningful_synthesis_plausible=True,question_framework_coherent=True,fatal_methodological_flaw=False,fatal_redundancy=False,feasibility="HIGH",editorial_grade="A")
    s["ratings_evidence"]={k:e("https://example.org/synthetic-rubric") for k in s["ratings"]}
    s["independent_extraction_and_screening_attested"]=True
    s["clinical_scope_evidence"]=e("https://example.org/synthetic-scope")
    s["search_scope_adjudication"]={"actual_search_methods_and_results_verified":True,"unresolved_material_search_limits":False,"evidence":e("https://example.org/synthetic-search-report"),"search_log_sha256":digest(p["search_log"])}
    if update:
        s["route"]="UPDATE";rid="REVIEW:PubMed:100";url="https://pubmed.ncbi.nlm.nih.gov/100/"
        s["competitor_decisions"]=[{"record_id":rid,"decision":"UPDATE_REQUIRED","full_text_checked":True,"last_search_date":"2024-01-01","included_study_ids":[f"study-{n}" for n in range(1,6)],"evidence":e(url),"reviewers":REVIEWERS}]
        s["update_or_correction_audits"]=[{"record_id":rid,"synthesis_group":fields,"baseline_evidence":e(url),"clinical_threshold_evidence":e("https://example.org/synthetic-threshold"),"impact_evidence":e("https://example.org/synthetic-impact"),"published_common_effect":{"effect":-0.05,"se":0.2/(5**0.5)},"minimum_important_effect_change":0.1}]
    return s
def bundle(s,keys=KEYS):return {"submission":s,"approvals":[{"reviewer":r,"signature":signature(s,r,k)} for r,k in keys.items()]}
def assess(ledger,c,s,*,keys=KEYS,packet=None):
    policy=policy_for_question_type(c.question_type);coverage=evaluate_coverage(ledger.list_search_log(c.candidate_id),policy)
    return evaluate(packet or snapshot(ledger,c),bundle(s,keys),keys,coverage,policy)

@pytest.mark.parametrize("update",[False,True])
def test_positive_control_reaches_all_fifteen_gates(tmp_path,update):
    with make_ledger(tmp_path/"p.sqlite",competitor=update)[0] as ledger:
        c=ledger.get_candidate("c");p=snapshot(ledger,c);s=make_submission(p,update=update)
        result=assess(ledger,c,s)
        assert result["qualification_granted"],result
        assert result["confirmed_independent_rct_count"]==7
        assert result["trials_with_extractable_outcomes"]==7
        assert len(result["gate_result"]["gates"])==15
        assert all(g["passed"] for g in result["gate_result"]["gates"])
        if update:assert result["update_audits"][0]["effect_change"]>0.1

@pytest.mark.parametrize("problem",["six_trials","duplicate","missing_outcome","unsigned","wrong_scope","wrong_snapshot","low_novelty","low_gain","low_importance","low_publication","bad_editorial","unverified_fulltext","bad_source","incompatible_outcome","nonindependent","incomplete_coverage","no_independent_approval","search_not_adjudicated","conflicting_registry","not_screened"])
def test_negative_controls_fail_closed(tmp_path,problem):
    with make_ledger(tmp_path/"n.sqlite")[0] as ledger:
        c=ledger.get_candidate("c");p=snapshot(ledger,c);s=make_submission(p);keys=KEYS
        if problem=="six_trials":s["studies"].pop();s["outcomes"].pop()
        elif problem=="duplicate":s["studies"][1]["report_ids"]=s["studies"][0]["report_ids"]
        elif problem=="missing_outcome":s["outcomes"].pop()
        elif problem=="unsigned":keys={"reviewer-a":KEYS["reviewer-a"]}
        elif problem=="wrong_scope":s["project_id"]="other"
        elif problem=="wrong_snapshot":s["snapshot_sha256"]="0"*64
        elif problem=="low_novelty":s["ratings"]["overall_novelty"]=2
        elif problem=="low_gain":s["ratings"]["new_information_gain"]=3
        elif problem=="low_importance":s["ratings"]["clinical_importance"]=3
        elif problem=="low_publication":s["ratings"]["publication_potential"]=3
        elif problem=="bad_editorial":s["ratings"]["editorial_grade"]="D"
        elif problem=="unverified_fulltext":s["studies"][0]["full_text_checked"]=False
        elif problem=="bad_source":s["outcomes"][0]["evidence"]=e("https://example.org/wrong-paper")
        elif problem=="incompatible_outcome":
            for n,o in enumerate(s["outcomes"]):o["timepoint"]=str(n)
        elif problem=="nonindependent":s["studies"][0]["independent_population_confirmed"]=False
        elif problem=="incomplete_coverage":ledger.append_search_log(SearchLogRecord("p","c","PROSPERO","synthetic query",SourceStatus.PARTIAL,7));s["snapshot_sha256"]=snapshot(ledger,c)["verification_v2"]["snapshot_sha256"];s["search_scope_adjudication"]["search_log_sha256"]=digest(snapshot(ledger,c)["verification_v2"]["search_log"])
        elif problem=="no_independent_approval":s["independent_extraction_and_screening_attested"]=False
        elif problem=="search_not_adjudicated":s["search_scope_adjudication"]={}
        elif problem=="conflicting_registry":s["studies"][0]["registry_ids"]=s["studies"][1]["registry_ids"]=["NCT00000001"]
        elif problem=="not_screened":
            ledger.upsert_external_evidence("c","PRIMARY_STUDY","8",source="PubMed",title="Unscreened",payload={"url":"https://pubmed.ncbi.nlm.nih.gov/8/"});s["snapshot_sha256"]=snapshot(ledger,c)["verification_v2"]["snapshot_sha256"]
        assert not assess(ledger,c,s,keys=keys)["qualification_granted"]

@pytest.mark.parametrize("problem",["no_new_trial","no_impact","baseline_mismatch","unresolved_competitor","correction_not_reconstructed","late_competitor"])
def test_update_negative_controls(tmp_path,problem):
    with make_ledger(tmp_path/"u.sqlite",competitor=True)[0] as ledger:
        c=ledger.get_candidate("c");p=snapshot(ledger,c);s=make_submission(p,update=True)
        if problem=="no_new_trial":s["studies"][-1]["first_report_date"]="2023-01-01"
        elif problem=="no_impact":s["update_or_correction_audits"][0]["minimum_important_effect_change"]=1.0
        elif problem=="baseline_mismatch":s["update_or_correction_audits"][0]["published_common_effect"]["effect"]=-0.9
        elif problem=="unresolved_competitor":s["competitor_decisions"]=[]
        elif problem=="correction_not_reconstructed":s["route"]="CORRECTIVE";s["competitor_decisions"][0]["decision"]="CORRECTION_REQUIRED"
        elif problem=="late_competitor":ledger.upsert_external_evidence("c","PUBLISHED_REVIEW","101",source="PubMed",title="New competitor",payload={"url":"https://pubmed.ncbi.nlm.nih.gov/101/"})
        assert not assess(ledger,c,s)["qualification_granted"]

def test_actual_orchestrator_and_export_reach_qualified_only_with_trusted_snapshot(tmp_path,monkeypatch):
    with make_ledger(tmp_path/"o.sqlite")[0] as ledger:
        c=ledger.get_candidate("c")
        # Already completed source retrieval, frozen synthetic fixture.
        monkeypatch.setattr(ReviewDiscoveryOrchestrator,"_search_sources",lambda *a,**kw:None)
        packet=snapshot(ledger,c);s=make_submission(packet)
        path=tmp_path/"trusted"/"p";path.mkdir(parents=True)
        (path/"c.json").write_text(json.dumps(bundle(s)))
        verifier=TrustedDirectory(path.parent,KEYS)
        engine=ReviewDiscoveryOrchestrator(ledger,[],strict_rct_minimum=7,scientific_verifier=verifier)
        r=engine.verify_candidate("c")
        assert r.candidate_status==CandidateStatus.QUALIFIED,(r.pending,r.decision)
        run=DiscoveryRunResult("p",[],[r],["c"],["c"])
        result=build_discovery_review_package(ledger,run)
        assert result["options"][0]["qualification_status"]=="FULLY_QUALIFIED"
        # Persisted metadata alone must not carry a prior qualification.
        r2=ReviewDiscoveryOrchestrator(ledger,[],strict_rct_minimum=7).verify_candidate("c")
        assert r2.candidate_status!=CandidateStatus.QUALIFIED

def test_signature_tamper_and_duplicate_keys_rejected(tmp_path):
    with make_ledger(tmp_path/"sig.sqlite")[0] as ledger:
        c=ledger.get_candidate("c");p=snapshot(ledger,c);s=make_submission(p)
        b=bundle(s);b["submission"]["ratings"]["overall_novelty"]=4
        policy=policy_for_question_type(c.question_type);coverage=evaluate_coverage(ledger.list_search_log("c"),policy)
        assert not evaluate(p,b,KEYS,coverage,policy)["qualification_granted"]
        assert not assess(ledger,c,s,keys={"reviewer-a":KEYS["reviewer-a"],"reviewer-b":KEYS["reviewer-a"]})["qualification_granted"]

def test_known_inverse_variance_result_and_sparse_fail_closed():
    rows=[{"measure":"LOG_HR","effect":0.1,"se":0.2},{"measure":"LOG_HR","effect":0.4,"se":0.4}]
    r=pool(rows)
    assert r["effect"]==pytest.approx(0.16) and r["se"]==pytest.approx((1/31.25)**0.5)
    with pytest.raises(ValueError):pool([{"measure":"RR","intervention_events":0,"comparator_events":2,"intervention_n":10,"comparator_n":10}]*2)


def corrective_submission(packet):
    s=make_submission(packet,update=True)
    s["route"]="CORRECTIVE";d=s["competitor_decisions"][0]
    d["decision"]="CORRECTION_REQUIRED";d["included_study_ids"]=[o["study_id"] for o in s["outcomes"]]
    a=s["update_or_correction_audits"][0]
    url=d["evidence"]["url"]
    a.update(correction_type="INCORRECT_EFFECT_OR_VARIANCE_EXTRACTION",verified_flaw_evidence=e(url),
        correction_method_evidence=e("https://example.org/synthetic-correction"),
        original_analysis_rows=[{**o,"effect":0.3,"evidence":e(url)} for o in s["outcomes"]])
    a["published_common_effect"]={"effect":0.3,"se":0.2/(7**0.5)}
    return s

@pytest.mark.parametrize("problem",[None,"no_discrepancy","wrong_original_row","unverified_flaw","wrong_baseline","different_trial_set"])
def test_corrective_route_reconstructs_published_error(tmp_path,problem):
    with make_ledger(tmp_path/"c.sqlite",competitor=True)[0] as ledger:
        c=ledger.get_candidate("c");p=snapshot(ledger,c);s=corrective_submission(p);a=s["update_or_correction_audits"][0]
        if problem=="no_discrepancy":a["original_analysis_rows"]=[{**o,"evidence":e("https://pubmed.ncbi.nlm.nih.gov/100/")} for o in s["outcomes"]]
        elif problem=="wrong_original_row":a["original_analysis_rows"][0]["study_id"]="fabricated"
        elif problem=="unverified_flaw":a.pop("verified_flaw_evidence")
        elif problem=="wrong_baseline":a["published_common_effect"]["effect"]=0.9
        elif problem=="different_trial_set":s["competitor_decisions"][0]["included_study_ids"].pop()
        result=assess(ledger,c,s)
        if problem is None:
            assert result["qualification_granted"],result
            assert len(result["update_audits"][0]["corrected_study_ids"])==7
        else:assert not result["qualification_granted"],result

def test_external_metafor_bcg_effects_and_q():
    # Source: CRAN metafor README, Colditz et al. BCG example. Published
    # arm counts, per-study log RR/variance and Q=152.2330, not a fabricated
    # RCT qualification case. Six allocation methods are not randomized.
    data=[
      (4,119,11,128,-.8893,.3256,True),(6,300,29,274,-1.5854,.1946,True),
      (3,228,11,209,-1.3481,.4154,True),(62,13536,248,12619,-1.4416,.0200,True),
      (33,5036,47,5761,-.2175,.0512,False),(180,1361,372,1079,-.7861,.0069,False),
      (8,2537,10,619,-1.6209,.2230,True),(505,87886,499,87892,.0120,.0040,True),
      (29,7470,45,7232,-.4694,.0564,True),(17,1699,65,1600,-1.3713,.0730,False),
      (186,50448,141,27197,-.3394,.0124,False),(5,2493,3,2338,.4459,.5325,False),
      (27,16886,29,17825,-.0173,.0714,False)]
    rows=[]
    for a,b,c,d,y,v,random in data:
        row={"measure":"RR","intervention_events":a,"comparator_events":c,"intervention_n":a+b,"comparator_n":c+d}
        yi,vi=effect(row);assert yi==pytest.approx(y,abs=.00006);assert vi==pytest.approx(v,abs=.00006)
        rows.append(row)
    assert pool(rows)["q"]==pytest.approx(152.2330,abs=.001)
    assert sum(x[-1] for x in data)==7
    # This external numerical fixture never supplies reviewer approval or GO.


def test_joint_cue_intersection_not_minimum_of_independent_counts():
    from scimed_scout.discovery.rct_first import joint_cue_audit
    c=CandidateRecord("c","p","Q","Cardiology",population="heart failure",intervention_exposure_index_test="drug A",comparator_reference="placebo",eligible_designs=["randomized controlled trials"])
    def r(i,title):
        return {"source":"PubMed","source_record_id":str(i),"title":title,"payload":{}}
    # Seven comparison-linked citations, seven other PICO/RCT citations;
    # no actual overlap. The old min(7,7) could falsely indicate readiness.
    comparison=[r(i,"Drug A versus placebo for kidney disease") for i in range(1,8)]
    pico=[r(i,"Randomized trial of drug A in heart failure "+str(i)) for i in range(8,15)]
    joint=joint_cue_audit(c,comparison+pico,comparison)
    assert joint["joint_comparison_pico_family_leads"]==0 and not joint["joint_cues_confirm_eligibility"]

def test_disagreement_resume_once_not_infinite():
    from scimed_scout.cloud.rct_worker import recovery_reasons
    from scimed_scout.discovery.models import DiscoveryCandidateResult,DiscoveryEvidenceSnapshot
    from scimed_scout.verification.coverage import VerificationCoverage
    r=DiscoveryCandidateResult("c",1,VerificationCoverage({},()),DiscoveryEvidenceSnapshot(14,14,2,("PubMed","Europe PMC"),pico_audit={"pico_design_family_leads":8}),["pending"],"pending",CandidateStatus.PROVISIONAL_BACKUP)
    meta={"rct_first_final_audit":{"family_leads":12,"joint_comparison_pico_family_leads":5}}
    assert recovery_reasons(r,meta)==["PICO_COMPARISON_DISAGREEMENT"]
    assert recovery_reasons(r,{**meta,"v2_disagreement_recovery_attempted":True})==[]
