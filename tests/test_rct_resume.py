from scimed_scout.cloud.rct_worker import recovery_reasons
from scimed_scout.discovery.models import DiscoveryCandidateResult, DiscoveryEvidenceSnapshot
from scimed_scout.verification.coverage import VerificationCoverage
from scimed_scout.domain import CandidateStatus

def result(*,coverage=True,n=7,pending=None,status=CandidateStatus.PROVISIONAL_BACKUP):
    return DiscoveryCandidateResult("c",7,VerificationCoverage({},() if coverage else ("mandatory source unavailable",)),
        DiscoveryEvidenceSnapshot(7,7,1,("PubMed",),pico_audit={"pico_design_family_leads":n}),
        pending or [],"PROVISIONAL",status)

def test_manual_only_and_low_evidence_do_not_trigger_retry():
    meta={"rct_first_final_audit":{"family_leads":7},"discovery_gate_inputs":{"score":4}}
    assert recovery_reasons(result(pending=["independent eligibility requires human adjudication"]),meta)==[]
    assert recovery_reasons(result(n=6),{})==[]
    assert recovery_reasons(result(status=CandidateStatus.QUALIFIED),{})==[]

def test_recoverable_blockers_only():
    assert recovery_reasons(result(coverage=False),{})==["MANDATORY_SOURCE_COVERAGE"]
    m={"rct_first_final_audit":{"family_leads":7}}
    assert recovery_reasons(result(pending=["TYPE-A: competing published reviews are not fully assessed"]),m)==["COMPETITOR_BACKLOG","SCORING_UNFINISHED"]

def test_resume_sql_is_invoker_and_preserves_report():
    from pathlib import Path
    s=Path("sql/2026-11-26_rct_resume.sql").read_text()
    assert "security invoker set search_path=''" in s
    assert "and d.client_token_hash=v_hash" in s
    assert "result_json #> '{run_summary,resume_eligible}'='true'::jsonb" in s
    branch=s.split("elsif old.status='COMPLETED'")[1].split("elsif old.status='QUEUED'")[0]
    assert "new := old" in branch and "new.result_json" not in branch
    assert "result_json='{}'::jsonb" in s
