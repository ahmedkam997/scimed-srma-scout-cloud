from datetime import datetime, timezone

from scimed_scout.discovery.evidence_seed import recent_pubmed_cues
from scimed_scout.domain import SourceStatus
from scimed_scout.sources.base import SearchRecord, SearchResult


class PubMedResults:
    def search(self, query, *, limit):
        return SearchResult(
            "PubMed", query, SourceStatus.SEARCHED_POSITIVE,
            [
                SearchRecord("PubMed", "1",
                    "Rationale and design of a randomized trial of adjunctive ablation",
                    year=2026),
                SearchRecord("PubMed", "2",
                    "Expert consensus on managing testosterone deficiency in primary care",
                    year=2026),
                SearchRecord("PubMed", "3",
                    "Long-term myocardial outcomes of a randomized trial in heart failure",
                    year=2027),
                SearchRecord("PubMed", "4",
                    "Effect of a sodium glucose cotransporter inhibitor on heart failure outcomes: a randomized trial",
                    year=2026, url="https://pubmed.ncbi.nlm.nih.gov/4/"),
                SearchRecord("PubMed", "5",
                    "Effects of exercise dose on heart rate in older patients: a randomized study",
                    year=2025, url="https://pubmed.ncbi.nlm.nih.gov/5/"),
            ],
            5,
        )


def test_source_seed_does_not_present_future_print_date_or_consensus_as_current_trial():
    cues=recent_pubmed_cues(
        "Cardiology", client=PubMedResults(),
        now=datetime(2026, 11, 23, tzinfo=timezone.utc),max_records=10,
    )
    assert [c["pmid"] for c in cues] == ["4", "5"]
    assert all(c["year"] <= 2026 for c in cues)
    assert all(c["verified_inclusion"] is False for c in cues)
