from scimed_scout.diagnostics import classify_failure, comparison_diagnostic, exception_diagnostic
from scimed_scout.ai.providers import ProviderFailure

def test_503_is_dependency_not_scientific_failure():
    report={"status":"PILOT_INCONCLUSIVE","strict_generation_comparability":False,
            "arms":{"A":{"generation":{"calls":[{"status":"FAILED","http_status":503}]}},
                    "B":{"generation":{"calls":[{"status":"FAILED","http_status":503}]}}}}
    out=comparison_diagnostic(report)
    assert [x["code"] for x in out["findings"]]==["UPSTREAM_UNAVAILABLE","COMPARISON_INCONCLUSIVE"]
    assert not out["scientific_superiority_established"]
    assert not out["automatic_code_repair"]

def test_structured_incidents_never_include_secret_messages():
    e=ProviderFailure("provider",503,"PRIVATE-TEST-KEY")
    assert "PRIVATE-TEST-KEY" not in str(exception_diagnostic(e))
    assert classify_failure(429)["code"]=="PROVIDER_LIMIT"
    assert classify_failure(500,context="SQLSTATE 57014")["code"]=="DATABASE_STATEMENT_TIMEOUT"

def test_unknown_error_requires_review():
    assert classify_failure()["automatic_action"]=="NONE"

def test_scientific_pending_does_not_trigger_code_change():
    report={"status":"PILOT_FINISHED","strict_generation_comparability":True,
            "arms":{"A":{"deep_audit":{"status":"COMPLETED","candidate_status":"PROVISIONAL_BACKUP"}}}}
    out=comparison_diagnostic(report)
    assert out["findings"][0]["category"]=="SCIENTIFIC"
    assert out["findings"][0]["automatic_action"]=="NONE"
