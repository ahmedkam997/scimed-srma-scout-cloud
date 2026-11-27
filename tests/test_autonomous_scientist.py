import json
import pytest
from dataclasses import asdict
from scripts import scimed_autonomous_worker as v1, scimed_autonomous_worker_v2 as v2
from scripts import scimed_autonomous_scientist as s
from scripts.scimed_private_review import import_packet
from scripts.scimed_independent_evaluation import evaluate_frozen,wilson
from scimed_scout.domain import SourceStatus
from scimed_scout.sources.base import SearchRecord,SearchResult
from scimed_scout.discovery.scientific_verification_v2 import snapshot

CID="RCT-TEST"
def state():
    x=v1.initial()
    x["ledger"][CID]={"id":CID,"title":"Example comparison","population":"hypertension",
      "intervention":"renal denervation","comparator":"sham","family_leads":9,"shortlist_cue":True}
    j=v2.job_for(v2.extend(x),CID);j["trial_ids"]=["111"];j["review_ids"]=["222"]
    return x

def row(pid,title="Example randomized trial"):
    return {"source":"PubMed","source_record_id":pid,"title":title,"payload":{"url":"https://pubmed.ncbi.nlm.nih.gov/"+pid+"/","metadata":{}}}

def test_packet_roundtrip_and_no_qualification(tmp_path,monkeypatch):
    x=state()
    w=s.workspace(x,CID)
    s.log(w,"PubMed","bounded query",SourceStatus.SEARCHED_POSITIVE,100)
    def fetch(c,ids):return {p:row(p,"Example systematic review" if p=="222" else "Example randomized trial") for p in ids},{}
    def extract(rows,**kw):return {"reports":[],"source_calls":0}
    report,raw=s.prepare_packet(x,None,fetcher=fetch,fulltext=extract)
    assert report["primary_report_count"]==1 and report["competitor_count"]==1
    assert report["qualification_granted"] is False
    assert raw["search_log"][0]["status"]=="PARTIAL"
    db=tmp_path/"candidate.db"
    p=import_packet(json.loads(json.dumps(raw)),db)
    assert p["verification_v2"]["snapshot_sha256"]==report["snapshot_sha256"]
    monkeypatch.delenv("SCIMED_TRUSTED_ADJUDICATION_DIR",raising=False)
    monkeypatch.delenv("SCIMED_TRUSTED_REVIEWER_KEYS_FILE",raising=False)
    assert s.private_adjudicate(db,CID)["qualification_granted"] is False
    with pytest.raises(ValueError):import_packet(raw,db)
    raw["raw_source_rows"][0]["title"]="tampered"
    with pytest.raises(ValueError):import_packet(raw,tmp_path/"tampered.db")

def test_bounded_registry_not_negative_inference():
    x=state()
    class Registry:
        name="PROSPERO"
        def search(self,q,limit):
            return SearchResult(self.name,q,SourceStatus.SEARCHED_NEGATIVE,total_count=0)
    report,_=s.registry(x,{"PROSPERO":Registry()})
    assert report["qualification_granted"] is False
    assert list(s.workspace(x,CID)["logs"].values())[0]["status"]=="PARTIAL"

def test_ambiguous_competitor_retained_and_source_identity_preserved():
    x=state()
    s.ingest_recovery(x,{"candidate_id":CID,"task":"competitors"},
      {"search":{"query":"example","status":"SEARCHED_POSITIVE","rows":[row("222","Unclear article")]}})
    w=s.workspace(x,CID)
    assert len(w["rows"])==1 and next(iter(w["rows"].values()))["evidence_type"]=="OTHER"
    s.append_rows(w,[row("222","New title")],"PRIMARY_STUDY")
    assert len(w["rows"])==2
    assert list(w["logs"].values())[0]["status"]=="PARTIAL"

def test_missing_benchmark_blocks_independent_claim():
    m=json.loads(open("benchmarks/academy/benchmark.json").read())
    result=evaluate_frozen(m,{},[],{})
    assert result["status"]=="BENCHMARK_NOT_ADMITTED"
    assert result["independent_validation_passed"] is False
    assert wilson(0,30)[1]>0

def test_integrated_cycle_diagnostic_and_validation():
    x=state();x["cycles"]=10
    report,_=s.cycle(x,None,None,{})
    assert report["task"]=="diagnostic" and x["cycles"]==11
    report,_=s.cycle(x,None,None,{})
    assert report["task"]=="validation" and report["first_choice_count"]==0
    assert report["status"]=="AWAITING_INDEPENDENT_CASE_ADJUDICATION"
    assert x["cycles"]==12

def test_public_packet_definitive_status_refused(tmp_path):
    x=state();w=s.workspace(x,CID)
    s.log(w,"PubMed","sample",SourceStatus.SEARCHED_POSITIVE,1)
    p=snapshot(s.WorkspaceLedger(CID,w),s.candidate(CID,x["ledger"][CID]))
    log=asdict(s.WorkspaceLedger(CID,w).list_search_log(CID)[0]);log["status"]="SEARCHED_POSITIVE"
    raw={"candidate":asdict(s.candidate(CID,x["ledger"][CID])),"packet":p,"raw_source_rows":[],"search_log":[log]}
    with pytest.raises(ValueError):import_packet(raw,tmp_path/"refuse.db")

def test_private_update_gate_preserves_real_thresholds_synthetic_only(tmp_path,monkeypatch):
    # Reuse original isolated fixture; never store keys or approvals in a workflow artifact.
    from test_scientific_verification_v2 import make_ledger,make_submission,bundle,KEYS
    from scimed_scout.discovery.scientific_verification_v2 import snapshot
    db=tmp_path/"synthetic.sqlite"
    with make_ledger(db,competitor=True)[0] as ledger:
        c=ledger.get_candidate("c");p=snapshot(ledger,c);submission=make_submission(p,update=True)
    approvals=tmp_path/"private"/"p";approvals.mkdir(parents=True)
    (approvals/"c.json").write_text(json.dumps(bundle(submission)))
    keyfile=tmp_path/"keys.json";keyfile.write_text(json.dumps({r:k.hex() for r,k in KEYS.items()}))
    monkeypatch.setenv("SCIMED_TRUSTED_ADJUDICATION_DIR",str(approvals.parent))
    monkeypatch.setenv("SCIMED_TRUSTED_REVIEWER_KEYS_FILE",str(keyfile))
    passed=s.private_adjudicate(db,"c")
    assert passed["qualification_granted"] is True
    assert passed["confirmed_independent_rct_count"]==7
    assert passed["update_audits"][0]["descriptive_inverse_variance_ratio"]==pytest.approx(7/5)
    assert len(passed["gate_result"]["gates"])==15
    submission["update_or_correction_audits"][0]["minimum_important_effect_change"]=10
    (approvals/"c.json").write_text(json.dumps(bundle(submission)))
    assert s.private_adjudicate(db,"c")["qualification_granted"] is False

def test_frozen_scoring_and_tampered_predictions_synthetic_only():
    from test_academy_benchmark import case,signed,manifest,KEYS
    from scripts.academy_benchmark import model_observation
    from scimed_scout.discovery.scientific_verification_v2 import digest,signature
    m=manifest(*(signed(case(n,label=("UPDATE","NOVEL","NEGATIVE")[n%3])) for n in range(1,31)))
    predictions=[{"case_id":c["case_id"],"prediction":c["opportunity"]} for c in m["cases"]]
    # These are deliberately oracle-generated predictions for software tests only.
    predictions[0]["prediction"]="UNRESOLVED"
    payload={"schema":"SCIMED_FROZEN_EVALUATION_V1","manifest_sha256":digest(m),
      "observation_sha256":digest([model_observation(c) for c in m["cases"]]),
      "predictions_sha256":digest(predictions),"worker_commit":"1"*40,
      "predictions_frozen_before_unblinding":True,"test_data_not_used_for_training":True,
      "independent_extraction_and_screening_attested":True}
    frozen={"submission":payload,"approvals":[{"reviewer":r,"signature":signature(payload,r,k)} for r,k in KEYS.items()]}
    result=evaluate_frozen(m,KEYS,predictions,frozen)
    assert result["n"]==30 and result["true_positive"]==19 and result["abstained"]==1
    assert result["independent_validation_passed"] is False
    predictions[0]["prediction"]="NOVEL"
    with pytest.raises(ValueError):evaluate_frozen(m,KEYS,predictions,frozen)

def test_automatic_exact_id_recovery_rejects_wrong_identity():
    class EPMC:
        name="Europe PMC"
        def search(self,q,limit):
            pid=q.split(":")[1].split()[0]
            result=SearchRecord(self.name,pid if pid=="111" else "999","Known report",metadata={"source":"MED"})
            return SearchResult(self.name,q,SourceStatus.SEARCHED_POSITIVE,[result],1)
    found,audit=s.fetch_with_recovery(None,["111","222"],fetcher=lambda c,ids:({},{}),alternate=EPMC())
    assert set(found)=={"111"} and audit["missing_after_recovery"]==["222"]
    assert audit["alternate_attempts"][0]["exact_recovered"] is True
    assert audit["alternate_attempts"][1]["exact_recovered"] is False

def test_recover_private_uses_strict_existing_engine_and_never_signs(tmp_path,monkeypatch):
    from test_scientific_verification_v2 import make_ledger
    from scripts.scimed_private_review import recover_private
    from scimed_scout.discovery.orchestrator import ReviewDiscoveryOrchestrator
    db=tmp_path/"recover.sqlite"
    with make_ledger(db)[0]:pass
    observed={}
    def recover(self,cid,**kwargs):
        observed.update(minimum=self.strict_rct_minimum,verifier=self.scientific_verifier,**kwargs)
        raise TimeoutError()
    monkeypatch.setattr(ReviewDiscoveryOrchestrator,"verify_candidate",recover)
    result=recover_private(db,"c",30)
    assert result["recovery_status"]=="TIME_BUDGET_CHECKPOINT"
    assert observed=={"minimum":7,"verifier":None,"limit_per_query":40,"recover_only":True}
    assert result["qualification_granted"] is False
