from scimed_scout.domain import SourceStatus
from scimed_scout.storage import SearchLogRecord
from scimed_scout.verification.coverage import evaluate_coverage
from scimed_scout.verification.policy import policy_for_question_type


def log(source, query, status):
    return SearchLogRecord("P", "C", source, query, status)


def test_latest_attempt_replaces_old_failure_for_same_source_query():
    policy = policy_for_question_type("DIAGNOSTIC_ACCURACY")
    logs = [
        log("PubMed", "q", SourceStatus.ACCESS_FAILED),
        log("PubMed", "q", SourceStatus.SEARCHED_NEGATIVE),
        log("Europe PMC", "q", SourceStatus.SEARCHED_NEGATIVE),
        log("PROSPERO", "q", SourceStatus.SEARCHED_NEGATIVE),
        log("OSF Registries", "q", SourceStatus.MANUAL_VERIFIED),
        log("ClinicalTrials.gov", "q", SourceStatus.ACCESS_FAILED),
    ]
    coverage = evaluate_coverage(logs, policy)
    assert coverage.source_statuses["PubMed"] == SourceStatus.SEARCHED_NEGATIVE
    assert coverage.complete
    assert coverage.warnings


def test_pipeline_source_is_required_for_effectiveness():
    policy = policy_for_question_type("EFFECTIVENESS")
    logs = [
        log("PubMed", "q", SourceStatus.SEARCHED_NEGATIVE),
        log("Europe PMC", "q", SourceStatus.SEARCHED_NEGATIVE),
        log("PROSPERO", "q", SourceStatus.SEARCHED_NEGATIVE),
        log("OSF Registries", "q", SourceStatus.MANUAL_VERIFIED),
        log("ClinicalTrials.gov", "q", SourceStatus.ACCESS_FAILED),
    ]
    coverage = evaluate_coverage(logs, policy)
    assert not coverage.complete
    assert any("pipeline" in blocker.lower() for blocker in coverage.blockers)
