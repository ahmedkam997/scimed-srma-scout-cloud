from scimed_scout.domain import SourceStatus
from scimed_scout.sources.clinicaltrials import ClinicalTrialsGovSource
from scimed_scout.sources.europe_pmc import EuropePMCSource
from scimed_scout.sources.http import JsonHttpClient
from scimed_scout.sources.openalex import OpenAlexSource
from scimed_scout.sources.pubmed import PubMedSource


def http(payload):
    return JsonHttpClient(loader=lambda _: payload, retries=0)


def broken_http():
    def fail(_):
        raise RuntimeError("blocked")
    return JsonHttpClient(loader=fail, retries=0)


def test_pubmed_negative_and_fail_closed():
    neg = PubMedSource(http({"esearchresult": {"count": "0", "idlist": []}})).search("x")
    assert neg.status == SourceStatus.SEARCHED_NEGATIVE
    failed = PubMedSource(broken_http()).search("x")
    assert failed.status == SourceStatus.ACCESS_FAILED
    assert failed.status != SourceStatus.SEARCHED_NEGATIVE


def test_europe_pmc_positive():
    result = EuropePMCSource(http({"hitCount": 1, "resultList": {"result": [{"pmid": "123", "title": "Trial", "pubYear": "2025"}]}})).search("x")
    assert result.status == SourceStatus.SEARCHED_POSITIVE
    assert result.records[0].record_id == "123"


def test_openalex_positive():
    payload = {"meta": {"count": 1}, "results": [{"id": "https://openalex.org/W1", "title": "Trial", "publication_year": 2025}]}
    result = OpenAlexSource(http(payload)).search("x")
    assert result.status == SourceStatus.SEARCHED_POSITIVE
    assert result.records[0].record_id.endswith("W1")


def test_clinicaltrials_positive():
    payload = {"totalCount": 1, "studies": [{"protocolSection": {"identificationModule": {"nctId": "NCT00000001", "briefTitle": "Trial"}}}]}
    result = ClinicalTrialsGovSource(http(payload)).search("x")
    assert result.status == SourceStatus.SEARCHED_POSITIVE
    assert result.records[0].record_id == "NCT00000001"


def test_missing_required_count_is_partial_not_negative():
    assert PubMedSource(http({"esearchresult": {}})).search("x").status == SourceStatus.PARTIAL
    assert EuropePMCSource(http({})).search("x").status == SourceStatus.PARTIAL
    assert OpenAlexSource(http({})).search("x").status == SourceStatus.PARTIAL
    assert ClinicalTrialsGovSource(http({})).search("x").status == SourceStatus.PARTIAL
