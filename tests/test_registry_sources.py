import json
import subprocess

from scimed_scout.domain import SourceStatus
from scimed_scout.sources.crossref import CrossrefSource
from scimed_scout.sources.http import JsonHttpClient
from scimed_scout.sources.osf import OSFRegistrationsSource
from scimed_scout.sources.prospero import ProsperoCliSource
from scimed_scout.sources.semantic_scholar import SemanticScholarSource


def http(payload):
    return JsonHttpClient(loader=lambda _: payload, retries=0)


def test_crossref_positive_and_negative():
    positive = CrossrefSource(http({"message": {"total-results": 1, "items": [{"DOI": "10.1/x", "title": ["Review"]}]}})).search("x")
    assert positive.status == SourceStatus.SEARCHED_POSITIVE
    assert positive.records[0].doi == "10.1/x"

    negative = CrossrefSource(http({"message": {"total-results": 0, "items": []}})).search("x")
    assert negative.status == SourceStatus.SEARCHED_NEGATIVE


def test_semantic_scholar_positive():
    payload = {"total": 1, "data": [{"paperId": "P1", "title": "Review", "year": 2026, "externalIds": {"DOI": "10.2/y"}}]}
    result = SemanticScholarSource(http(payload), api_key="").search("x")
    assert result.status == SourceStatus.SEARCHED_POSITIVE
    assert result.records[0].record_id == "P1"


def test_osf_empty_metadata_search_is_partial_not_negative():
    result = OSFRegistrationsSource(http({"data": []})).search("x")
    assert result.status == SourceStatus.PARTIAL
    assert result.status != SourceStatus.SEARCHED_NEGATIVE


def test_prospero_cli_unavailable_is_access_failed():
    result = ProsperoCliSource(executable="definitely-not-installed-prospero").search("x")
    assert result.status == SourceStatus.ACCESS_FAILED


def test_prospero_cli_parses_machine_readable_search():
    payload = {
        "ok": True,
        "data": {
            "total_hits": 1,
            "hits": [{"record_id": "1", "accession_number": "CRD420260000001", "title": "Protocol", "year_first_published": 2026}],
        },
    }

    def runner(command):
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(payload), stderr="")

    result = ProsperoCliSource(runner=runner).search("x")
    assert result.status == SourceStatus.SEARCHED_POSITIVE
    assert result.records[0].record_id == "CRD420260000001"
