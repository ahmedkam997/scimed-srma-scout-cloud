from __future__ import annotations

from scimed_scout.discovery.open_access_dates import (
    OpenAccessSearchDateResolver, extract_search_date,
)
from scimed_scout.discovery.novelty import DiscoveryNoveltyService
from scimed_scout.competitors import SemanticCompetitorAssessor
from scimed_scout.ai import StaticAIProvider
from scimed_scout.storage import CandidateRecord, ProjectRecord, SQLiteLedger


def review(pmcid="PMC1234567", year=2025):
    return {
        "source": "PubMed", "source_record_id": "12345678",
        "title": "Systematic review and meta-analysis of hypertension treatment",
        "evidence_type": "PUBLISHED_REVIEW",
        "payload": {
            "year": year,
            "metadata": {"articleids": [{"idtype": "pmc", "value": pmcid}]},
        },
    }


XML = b"""<?xml version="1.0"?>
<article><front><article-meta><title-group><article-title>A review</article-title></title-group></article-meta></front>
<body><sec><title>Methods and search strategy</title><p>We searched
MEDLINE, Embase and CENTRAL from inception through November 2022.
Two reviewers screened the records.</p></sec></body></article>"""


def test_extract_only_explicit_search_cutoff_not_publication_date():
    result = extract_search_date(
        "Published in 2025. Databases were searched from inception through November 2022."
    )
    assert result["date"] == "November 2022"
    assert "searched" in result["quote"]
    assert extract_search_date("A 2025 review included trials from 2010 to 2024.") is None


def test_open_access_methods_retrieval_provides_quote_and_url_without_eligibility():
    urls = []
    resolver = OpenAccessSearchDateResolver(
        fetcher=lambda url: urls.append(url) or XML
    )
    result = resolver.resolve(review())
    assert result["date"] == "November 2022"
    assert result["year"] == 2022
    assert result["source_url"].endswith("PMC1234567/fullTextXML")
    assert result["full_text_eligibility_verified"] is False
    assert len(urls) == 1


def test_no_pmcid_avoids_network_and_unrelated_date_is_rejected():
    calls = []
    resolver = OpenAccessSearchDateResolver(fetcher=lambda url: calls.append(url) or XML)
    assert resolver.resolve(review(pmcid="")) is None
    assert calls == []
    text = b"<article><body><sec><title>Background</title><p>We searched until 2022.</p></sec></body></article>"
    assert resolver.resolve(review()) is not None
    assert OpenAccessSearchDateResolver(fetcher=lambda _: text).resolve(review()) is None


def test_future_search_date_relative_to_publication_is_rejected():
    xml = b"<article><body><sec><title>Methods</title><p>Databases searched through 2026-01-02.</p></sec></body></article>"
    assert OpenAccessSearchDateResolver(fetcher=lambda _: xml).resolve(review(year=2020)) is None


def test_service_persists_source_backed_search_date_in_existing_review(tmp_path):
    resolver = OpenAccessSearchDateResolver(fetcher=lambda _: XML)
    with SQLiteLedger(tmp_path / "dates.sqlite3") as ledger:
        ledger.upsert_project(ProjectRecord("P1", "Cardiology"))
        ledger.upsert_candidate(CandidateRecord("C1", "P1", "Question", "Cardiology",
                                              question_type="EFFECTIVENESS",
                                              population="Adults with hypertension",
                                              intervention_exposure_index_test="Antihypertensive therapy"))
        item = review()
        ledger.upsert_external_evidence(
            "C1", "PUBLISHED_REVIEW", item["source_record_id"],
            source=item["source"], title=item["title"], payload=item["payload"],
        )
        service = DiscoveryNoveltyService(
            ledger, SemanticCompetitorAssessor(StaticAIProvider('{"assessments":[]}')),
            search_date_resolver=resolver,
        )
        saved = service._resolve_search_dates(
            "C1", ledger.list_external_evidence("C1", "PUBLISHED_REVIEW"),
        )
        assert saved[0]["date"] == "November 2022"
        stored = ledger.list_external_evidence("C1", "PUBLISHED_REVIEW")[0]["payload"]["metadata"]
        assert stored["last_search_date"] == "November 2022"
        assert stored["search_date_evidence_level"] == "EUROPE_PMC_OPEN_ACCESS_FULL_TEXT_METHODS"
        assert "MEDLINE" in stored["search_date_evidence_quote"]
