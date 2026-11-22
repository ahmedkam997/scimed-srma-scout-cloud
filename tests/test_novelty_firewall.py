from scimed_scout.domain import SourceStatus
from scimed_scout.novelty import (
    CompetitorMatrix,
    CoverageAudit,
    NoveltyFirewall,
    OverlapLevel,
    QueryTerms,
    SearchLogEntry,
    generate_registry_queries,
)
from scimed_scout.sources.base import SearchResult


class FakeSource:
    def __init__(self, name, status):
        self.name = name
        self.status = status

    def search(self, query, *, limit=20):
        return SearchResult(self.name, query, self.status, total_count=0)


def test_query_generator_is_deduplicated_and_sensitive():
    queries = generate_registry_queries(
        QueryTerms(
            central_phrase="perioperative hypotension vasopressors",
            population="major surgery",
            intervention="norepinephrine",
            comparator="phenylephrine",
            disease="perioperative hypotension",
            intervention_class="vasopressor",
            strategy="blood pressure management",
            principal_outcome="major adverse cardiovascular events",
            acronym="POQI",
            population_synonyms=["noncardiac surgery"],
            intervention_synonyms=["noradrenaline"],
        )
    )
    assert len(queries) >= 8
    assert len(queries) == len(set(q.casefold() for q in queries))


def test_competitor_fatal_only_when_identical_adequate_recent_and_no_new_information():
    matrix = CompetitorMatrix(
        population=0.95,
        intervention=0.95,
        comparator=0.9,
        clinical_decision=0.95,
        principal_outcomes=0.9,
        design_restriction=0.95,
        treatment_era=0.9,
        trial_set=0.95,
        adequate=True,
        recent=True,
        meaningful_new_information=False,
    )
    assert matrix.overlap_level() == OverlapLevel.ESSENTIALLY_IDENTICAL
    assert matrix.fatal_redundancy()

    matrix.meaningful_new_information = True
    assert not matrix.fatal_redundancy()


def test_coverage_blocks_partial_registry_access():
    audit = CoverageAudit([
        SearchLogEntry("PubMed", "q", SourceStatus.SEARCHED_NEGATIVE),
        SearchLogEntry("Europe PMC", "q", SourceStatus.SEARCHED_NEGATIVE),
        SearchLogEntry("PROSPERO", "q", SourceStatus.ACCESS_FAILED),
        SearchLogEntry("OSF Registries", "q", SourceStatus.PARTIAL),
        SearchLogEntry("ClinicalTrials.gov", "q", SourceStatus.SEARCHED_NEGATIVE),
    ])
    blockers = audit.blockers()
    assert any("PROSPERO" in blocker for blocker in blockers)
    assert any("OSF" in blocker for blocker in blockers)
    assert not audit.novelty_clearance()


def test_firewall_mixed_failure_is_partial():
    firewall = NoveltyFirewall([FakeSource("PubMed", SourceStatus.SEARCHED_NEGATIVE), FakeSource("PROSPERO", SourceStatus.ACCESS_FAILED)])
    report = firewall.run({"PubMed": ["q1", "q2"], "PROSPERO": ["q1"]})
    assert report.sources["PubMed"].status == SourceStatus.SEARCHED_NEGATIVE
    assert report.sources["PROSPERO"].status == SourceStatus.ACCESS_FAILED
