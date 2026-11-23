"""Regression tests for evidence-map-style review and study classification."""
from scimed_scout.discovery.evidence_classification import (
    classify_review_search_hit, classify_registration_search_hit,
)
from scimed_scout.domain import SourceStatus
from scimed_scout.sources.base import SearchRecord, SearchResult
from scimed_scout.storage import CandidateRecord, ProjectRecord, SQLiteLedger
from scimed_scout.discovery.orchestrator import ReviewDiscoveryOrchestrator


def record(title, source="OpenAlex", **meta):
    return SearchRecord(source, "R1", title, metadata=meta)


def test_original_rct_is_not_construed_as_competing_systematic_review():
    study = record("Ketone monoester ingestion and cognitive performance during exercise-heat stress",
                   type="article")
    assert classify_review_search_hit(study) == "NEEDS_BIBLIOGRAPHIC_CHECK"
    randomized = record("A randomized controlled trial of ketone monoester ingestion", type="article")
    assert classify_review_search_hit(randomized) == "PRIMARY_OR_NONREVIEW"


def test_synthesis_titles_and_pubmed_types_are_identified_as_review_cues():
    for title in (
        "Ketone supplementation: A systematic review and meta-analysis",
        "An umbrella review of trials in heart failure",
        "A scoping review of stroke rehabilitation",
        "Network meta-analysis of randomized trials",
    ):
        assert classify_review_search_hit(record(title)) == "CONFIRMED_REVIEW_CUE"
    assert classify_review_search_hit(record(
        "Heart failure treatment evidence", "PubMed",
        publicationTypes=["Systematic Review", "Journal Article"],
    )) == "CONFIRMED_REVIEW_CUE"


def test_explicit_systematic_search_abstract_is_review_cue_but_not_random_article():
    assert classify_review_search_hit(record(
        "Treatment options for adult hypertension",
        abstract="We systematically searched PubMed and Embase and pooled effect sizes."
    )) == "CONFIRMED_REVIEW_CUE"
    assert classify_review_search_hit(record(
        "Randomized trial of treatment in adults",
        abstract="Systematic review of older experiments was discussed.",
    )) == "PRIMARY_OR_NONREVIEW"


def test_osf_primary_preregistrations_do_not_compete_with_review_protocols():
    trial = record(
        "Acute ketone monoester ingestion affects monocyte phenotype in healthy adults: randomized crossover trial",
        "OSF Registries",
    )
    protocol = record(
        "Systematic review and meta-analysis of ketone monoester interventions",
        "OSF Registries",
    )
    uncertain = record("Metabolic health in exercising adults", "OSF Registries")
    assert classify_registration_search_hit(trial) == "PRIMARY_STUDY_PREREGISTRATION"
    assert classify_registration_search_hit(protocol) == "REVIEW_REGISTRATION_CUE"
    assert classify_registration_search_hit(uncertain) == "UNCLASSIFIED_REGISTRATION"
    assert classify_registration_search_hit(record("Review methods without title", "PROSPERO")) == "REVIEW_REGISTRATION_CUE"


class ConstantSearch:
    def __init__(self, name, records):
        self.name, self.records = name, records

    def search(self, query, *, limit=10):
        return SearchResult(
            self.name, query, SourceStatus.SEARCHED_POSITIVE,
            self.records, len(self.records),
        )


def test_orchestrator_preserves_uncertain_article_but_avoids_false_competing_review(tmp_path):
    with SQLiteLedger(tmp_path / "evidence.db") as ledger:
        ledger.upsert_project(ProjectRecord("P1", "Cardiology"))
        ledger.upsert_candidate(CandidateRecord(
            candidate_id="C1", project_id="P1",
            title="Ketone monoester for heart failure", specialty="Cardiology",
            question_type="EFFECTIVENESS",
            population="Adults with heart failure",
            intervention_exposure_index_test="Ketone monoester",
            comparator_reference="Placebo",
            outcomes=["Hospitalization"],
            eligible_designs=["randomized controlled trials"],
        ))
        study = record("Ketone monoester effect on endurance in cyclists", type="article")
        review = SearchRecord(
            "OpenAlex", "R2",
            "Systematic review of ketone ester outcomes in adults",
        )
        source = ConstantSearch("OpenAlex", [study, review])
        engine = ReviewDiscoveryOrchestrator(ledger, [source])
        candidate = ledger.get_candidate("C1")
        engine._search_sources(candidate, ("OpenAlex",), ("ketone review",),
                               evidence_type="PUBLISHED_REVIEW",
                               purpose="published review", limit_per_query=10)
        actual_reviews = ledger.list_external_evidence("C1", "PUBLISHED_REVIEW")
        ambiguous = ledger.list_external_evidence("C1", "UNCLASSIFIED_REVIEW_LEAD")
        assert [r["title"] for r in actual_reviews] == [review.title]
        assert [r["title"] for r in ambiguous] == [study.title]
        assert ledger.list_search_log("C1")[0].status == SourceStatus.SEARCHED_POSITIVE
