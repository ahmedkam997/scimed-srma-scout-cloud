from scimed_scout.domain import SourceAudit, SourceStatus

def test_access_failure_never_supports_negative_inference():
    x = SourceAudit("PROSPERO", SourceStatus.ACCESS_FAILED)
    assert x.supports_negative_inference is False

def test_successful_negative_search_supports_negative_inference():
    x = SourceAudit("OSF", SourceStatus.SEARCHED_NEGATIVE)
    assert x.supports_negative_inference is True
