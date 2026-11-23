"""Source-first evidence gap discovery uses actual review abstract caveats."""
from datetime import datetime, timezone

from scimed_scout.discovery.evidence_seed import recent_review_gap_cues, review_gap_prompt
from scimed_scout.domain import SourceStatus
from scimed_scout.sources.base import SearchRecord, SearchResult


class FakeEurope:
    def __init__(self, records, *, status=SourceStatus.SEARCHED_POSITIVE):
        self.records, self.status, self.queries = records, status, []

    def search(self, query, *, limit=20):
        self.queries.append((query, limit))
        return SearchResult("Europe PMC", query, self.status, self.records,
                            len(self.records))


def record(title, abstract, year=2024, pmid="123", doi="10.1000/abc"):
    return SearchRecord(
        "Europe PMC", pmid, title,
        year=year, doi=doi, url="https://europepmc.org/article/MED/" + pmid,
        metadata={"abstractText": abstract, "pubTypeList": {"pubType": ["Review"]}},
    )


def test_source_linked_review_gap_cues_from_published_abstracts_not_model_inference():
    source=FakeEurope([
        record(
            "Heart failure treatments: a systematic review and meta-analysis",
            "<p>We searched MEDLINE. Further randomized trials are needed "
            "to resolve heart failure hospitalization in elderly patients.</p>",
        ),
        record(
            "Ketone monoester exercise performance: a systematic review",
            "All participants improved exercise ability. No cautionary limitation.",
            pmid="124", doi="10.1000/def",
        ),
        record(
            "An acute trial of ketogenic exercise treatment",
            "Future research should include larger trials.",
            pmid="125", doi="10.1000/ghi",
        ),
    ])
    cues=recent_review_gap_cues(
        "Cardiology", now=datetime(2026, 11, 23, tzinfo=timezone.utc),
        client=source,
    )
    assert len(cues)==1
    assert cues[0]["doi"]=="10.1000/abc"
    assert "Further randomized trials" in cues[0]["gap_sentence_from_abstract"]
    assert cues[0]["last_literature_search_date"] is None
    assert cues[0]["update_justified"] is False
    assert cues[0]["new_independent_eligible_studies_confirmed"] is None
    assert cues[0]["role"]=="PUBLISHED_REVIEW_ABSTRACT_GAP_LEAD_ONLY"
    assert "PUB_TYPE:review" in source.queries[0][0]
    assert "PUB_YEAR:[2021 TO 2026]" in source.queries[0][0]
    assert "further" in review_gap_prompt(cues).lower()
    assert "no URL" not in review_gap_prompt(cues)


def test_review_gap_no_evidence_is_not_invented():
    source=FakeEurope([],status=SourceStatus.ACCESS_FAILED)
    assert recent_review_gap_cues("Cardiology",client=source)==[]
    assert recent_review_gap_cues("ALL",client=source)==[]
    assert review_gap_prompt([])==""


def test_review_gap_evidence_type_fails_closed_when_abstract_has_no_gap():
    src=FakeEurope([record(
        "Systematic review and meta-analysis of pain outcomes",
        "Background and results only; no evidence gap mentioned.",
    )])
    assert recent_review_gap_cues("General Surgery",client=src)==[]


def test_discovery_gaps_from_abstract_are_not_fulltext_adjudicated():
    src=FakeEurope([record(
        "Systematic review of hypertension",
        "<b>Conclusion</b> The evidence is insufficient to reach a firm conclusion.",
    )])
    lead=recent_review_gap_cues("Cardiology",client=src)[0]
    assert lead["fulltext_gap_verified"] is False
    assert "Evidence" not in lead["role"]


def test_long_review_abstract_gap_excerpt_contains_exact_uncertainty_words():
    long_results = (
        "Background. " + "Observed heart rate and cardiac output in study participants. " * 12
        + "Further randomized trials are needed to assess patient-important outcomes."
    )
    source=FakeEurope([record(
        "A systematic review and meta-analysis of exercise interventions",
        long_results,
    )])
    result=recent_review_gap_cues("Cardiology",client=source)
    assert len(result)==1
    assert "Further randomized trials" in result[0]["gap_sentence_from_abstract"]
    assert "Further randomized trials" in result[0]["matched_gap_phrase"]
    assert len(result[0]["gap_sentence_from_abstract"]) <= 330
    assert result[0]["fulltext_gap_verified"] is False
