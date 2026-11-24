from datetime import datetime, timezone

from scimed_scout.discovery.evidence_seed import cue_prompt, recent_pubmed_cues
from scimed_scout.domain import SourceStatus
from scimed_scout.sources.base import SearchRecord, SearchResult


class FakePubMed:
    def __init__(self, status=SourceStatus.SEARCHED_POSITIVE):
        self.status = status
        self.queries = []

    def search(self, query, *, limit=20):
        self.queries.append((query, limit))
        return SearchResult(
            "PubMed", query, self.status,
            records=[
                SearchRecord("PubMed", "101", title="Recent randomized testing in a clinical subgroup", year=2026, url="https://pubmed.ncbi.nlm.nih.gov/101/"),
                SearchRecord("PubMed", "102", title="Recent randomized testing in a clinical subgroup", year=2026),
                SearchRecord("PubMed", "103", title="New diagnostic threshold study in heart failure", year=2025),
            ] if self.status == SourceStatus.SEARCHED_POSITIVE else [],
            total_count=3,
        )


def test_recent_evidence_cues_are_real_identifiers_and_not_verified_studies():
    client = FakePubMed()
    cues = recent_pubmed_cues("Cardiology", "EFFECTIVENESS", client=client, now=datetime(2026, 11, 23, tzinfo=timezone.utc))
    assert len(cues) == 2
    assert cues[0]["pmid"] == "101"
    assert cues[0]["verified_inclusion"] is False
    assert "2024/01/01" in client.queries[0][0]
    assert "2026/12/31" in client.queries[0][0]
    assert "do NOT prove novelty" in cue_prompt(cues)


def test_cues_fail_closed_without_fabricating_evidence():
    assert recent_pubmed_cues("ALL", "ALL", client=FakePubMed()) == []
    assert recent_pubmed_cues("Cardiology", "ALL", client=FakePubMed(SourceStatus.ACCESS_FAILED)) == []
    assert cue_prompt([]) == ""


def test_cardiology_pubmed_seed_query_rotates_between_subspecialties():
    client = FakePubMed()
    recent_pubmed_cues(
        "Cardiology", "ALL", client=client,
        rotation_index=0, now=datetime(2026, 11, 23, tzinfo=timezone.utc),
    )
    recent_pubmed_cues(
        "Cardiology", "ALL", client=client,
        rotation_index=1, now=datetime(2026, 11, 23, tzinfo=timezone.utc),
    )
    first, second = client.queries[0][0], client.queries[1][0]
    assert first != second
    assert '"heart failure"[Title/Abstract]' in first
    assert '"coronary artery disease"[Title/Abstract]' in second
    assert '"myocardial infarction"[Title/Abstract]' in second
    assert '"Cohort Studies"' in first
    assert "2026/12/31" in second
