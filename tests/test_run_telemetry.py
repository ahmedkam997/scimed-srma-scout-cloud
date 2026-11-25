from scimed_scout.run_telemetry import aggregate, MeteredDiscoveryProvider, write_report
from scimed_scout.maintenance_notes import worker_findings, parse_worker_zip
from scimed_scout.ai.models import AIResponse
import json,io,zipfile

def sample():
    return aggregate({"run_summary":{"requested_candidates":10,"generated_candidates":4,"verified_candidates":3,
        "status_counts":{"PROVISIONAL_BACKUP":3},"candidate_audits":[
        {"title":"PRIVATE TITLE","pending":["TYPE-A: competing published reviews are not fully assessed"],
         "coverage_blockers":["PRIVATE QUERY"],"source_statuses":{"PROSPERO":"PARTIAL"},
         "pico_design_family_leads":2} for i in range(3)]}},elapsed_seconds=200,specialty="Cardiology",question_type="ALL")

def test_aggregate_contains_no_candidate_text_and_distinguishes_unknown():
    report=sample()
    assert "PRIVATE" not in json.dumps(report)
    assert report["reason_counts"]=={"SOURCE_COVERAGE":3,"COMPETITOR_REVIEW_PENDING":3}
    assert report["qualified"]==0 and report["verified"]==3
    assert report["eligible_independent_studies_confirmed"] is None
    assert report["pico_family_lead_counts_available"]==3
    assert report["candidates_at_minimum_pico_lead_signal"]==0

def test_single_zero_does_not_open_scientific_incident():
    assert worker_findings(sample())==[]
    assert worker_findings(sample(),[sample()])==[]
    assert set(worker_findings(sample(),[sample(),sample()]))=={
        "REPEATED_LOW_DISCOVERY_YIELD","REPEATED_GENERATION_SHORTFALL","REPEATED_SOURCE_COVERAGE"}
    assert worker_findings(sample(),[{**sample(),"scope":"radiology"},sample()])==[]

def test_runtime_and_quota_signals_separate():
    s={**sample(),"elapsed_seconds":2800,"ai":{"failure_categories":{"PROVIDER_LIMIT":1}}}
    assert set(worker_findings(s))=={"SLOW_DISCOVERY_RUN","AI_CAPACITY_PRESSURE"}
    assert worker_findings({"status":"FAILED","failure_code":"DATABASE_STATEMENT_TIMEOUT"})==["DATABASE_STATEMENT_TIMEOUT"]
    assert worker_findings({"status":"CANCELLED"})==[]

def test_meter_no_raw_data_and_optional_artifact(tmp_path,monkeypatch):
    class Provider:
        total_failover_count=1
        unavailable_free_providers=[]
        def complete(self,request):
            return AIResponse("PRIVATE","p","m",{"usage":{"total_tokens":55},"secret":"PRIVATE"})
    meter=MeteredDiscoveryProvider(Provider())
    meter.complete(None)
    report={**sample(),"ai":meter.snapshot()}
    assert report["ai"]["reported_total_tokens"]==55
    assert not report["ai"]["remaining_quota_known"]
    assert "PRIVATE" not in json.dumps(report)
    path=tmp_path/"scimed-worker-telemetry.json"
    monkeypatch.setenv("SCIMED_MONITOR_REPORT",str(path))
    write_report(report)
    b=io.BytesIO()
    with zipfile.ZipFile(b,"w") as z:
        z.writestr(path.name,path.read_text())
    assert parse_worker_zip(b.getvalue())==report
