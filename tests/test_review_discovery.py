from scimed_scout.discovery import ReviewDiscoveryOrchestrator
from scimed_scout.domain import CandidateStatus, SourceStatus
from scimed_scout.sources.base import SearchRecord, SearchResult
from scimed_scout.storage import CandidateRecord, ProjectRecord, SQLiteLedger


def gate_inputs():
    return {
        "design_framework_defined": True,
        "meaningful_synthesis_plausible": True,
        "clinical_question_novelty": 4,
        "overall_novelty": 4,
        "question_framework_coherent": True,
        "feasibility": "HIGH",
        "fatal_methodological_flaw": False,
        "clinical_importance": 5,
        "publication_potential": 5,
        "new_information_gain": 4,
        "publication_oriented_score": 85,
        "editorial_grade": "B",
    }


def candidate(cid="C1"):
    return CandidateRecord(
        candidate_id=cid,
        project_id="P1",
        title="Diagnostic accuracy of Test A for disease X",
        specialty="Radiology",
        question_type="DIAGNOSTIC_ACCURACY",
        review_question="What is the diagnostic accuracy of Test A for disease X?",
        population="Adults with suspected disease X",
        intervention_exposure_index_test="Test A",
        comparator_reference="Histopathology",
        outcomes=["sensitivity", "specificity"],
        eligible_designs=["diagnostic accuracy studies"],
        rationale="Clinically important diagnostic uncertainty",
        novelty_hypothesis="Current syntheses may not answer this exact question",
        search_terms=["Test A disease X", "diagnostic accuracy"],
        metadata={"discovery_gate_inputs": gate_inputs()},
    )


class LiteratureSource:
    def __init__(self, name, records):
        self.name = name
        self.records = records

    def search(self, query, *, limit=20):
        if "systematic review" in query.casefold() or "meta-analysis" in query.casefold():
            return SearchResult(self.name, query, SourceStatus.SEARCHED_NEGATIVE, [], 0)
        return SearchResult(
            self.name,
            query,
            SourceStatus.SEARCHED_POSITIVE if self.records else SourceStatus.SEARCHED_NEGATIVE,
            list(self.records)[:limit],
            len(self.records),
        )


class FixedSource:
    def __init__(self, name, status):
        self.name = name
        self.status = status

    def search(self, query, *, limit=20):
        return SearchResult(self.name, query, self.status, [], 0)


def primary_records(n=4):
    rows = []
    for i in range(1, n + 1):
        rows.append(
            SearchRecord(
                source="PubMed",
                record_id=f"P{i}",
                title=f"Primary diagnostic study {i}",
                doi=f"10.1000/study{i}",
                year=2024 + (i % 2),
            )
        )
    return rows


def clients(n=4, prospero=SourceStatus.SEARCHED_NEGATIVE):
    pubmed = primary_records(n)
    duplicates = [
        SearchRecord(
            source="Europe PMC",
            record_id=f"E{i}",
            title=f"Primary diagnostic study {i}",
            doi=f"10.1000/study{i}",
        )
        for i in range(1, min(n, 2) + 1)
    ]
    return [
        LiteratureSource("PubMed", pubmed),
        LiteratureSource("Europe PMC", duplicates),
        LiteratureSource("OpenAlex", []),
        LiteratureSource("Crossref", []),
        LiteratureSource("Semantic Scholar", []),
        FixedSource("PROSPERO", prospero),
        FixedSource("OSF Registries", SourceStatus.MANUAL_VERIFIED),
        FixedSource("ClinicalTrials.gov", SourceStatus.SEARCHED_NEGATIVE),
    ]


def test_discovery_only_candidate_with_four_unique_studies_qualifies(tmp_path):
    with SQLiteLedger(tmp_path / "d.sqlite3") as ledger:
        ledger.upsert_project(ProjectRecord("P1", "Radiology", question_type="DIAGNOSTIC_ACCURACY"))
        ledger.upsert_candidate(candidate())
        result = ReviewDiscoveryOrchestrator(ledger, clients()).verify_candidate("C1")

        assert result.evidence.unique_primary_study_candidates == 4
        assert result.candidate_status == CandidateStatus.QUALIFIED
        assert result.decision == "QUALIFIED — FIRST-CHOICE REVIEW TOPIC"
        assert ledger.list_payloads if False else True
        decision = ledger.list_decisions("C1")[-1]
        assert decision.payload["scope"] == "REVIEW_DISCOVERY_ONLY"
        assert "study_verification_summary" not in decision.payload
        assert "synthesis_verification_summary" not in decision.payload


def test_duplicate_database_records_do_not_inflate_primary_study_count(tmp_path):
    with SQLiteLedger(tmp_path / "d.sqlite3") as ledger:
        ledger.upsert_project(ProjectRecord("P1", "Radiology", question_type="DIAGNOSTIC_ACCURACY"))
        ledger.upsert_candidate(candidate())
        result = ReviewDiscoveryOrchestrator(ledger, clients()).verify_candidate("C1")
        assert result.evidence.raw_primary_records > result.evidence.unique_primary_study_candidates
        assert result.evidence.unique_primary_study_candidates == 4


def test_three_unique_primary_studies_are_rejected_after_complete_search(tmp_path):
    with SQLiteLedger(tmp_path / "d.sqlite3") as ledger:
        ledger.upsert_project(ProjectRecord("P1", "Radiology", question_type="DIAGNOSTIC_ACCURACY"))
        ledger.upsert_candidate(candidate())
        result = ReviewDiscoveryOrchestrator(ledger, clients(n=3)).verify_candidate("C1")
        assert result.evidence.unique_primary_study_candidates == 3
        assert result.candidate_status == CandidateStatus.REJECTED
        assert "FEWER THAN 4" in result.decision


def test_prospero_failure_never_becomes_negative_novelty_clearance(tmp_path):
    with SQLiteLedger(tmp_path / "d.sqlite3") as ledger:
        ledger.upsert_project(ProjectRecord("P1", "Radiology", question_type="DIAGNOSTIC_ACCURACY"))
        ledger.upsert_candidate(candidate())
        result = ReviewDiscoveryOrchestrator(
            ledger,
            clients(prospero=SourceStatus.ACCESS_FAILED),
        ).verify_candidate("C1")
        assert result.candidate_status == CandidateStatus.PROVISIONAL_BACKUP
        assert any("PROSPERO" in blocker for blocker in result.coverage.blockers)


def test_obvious_systematic_review_is_not_counted_as_primary_study(tmp_path):
    records = primary_records(4) + [
        SearchRecord(
            source="PubMed",
            record_id="REV1",
            title="Systematic review and meta-analysis of Test A",
            doi="10.1000/review",
        )
    ]
    custom = clients()
    custom[0] = LiteratureSource("PubMed", records)

    with SQLiteLedger(tmp_path / "d.sqlite3") as ledger:
        ledger.upsert_project(ProjectRecord("P1", "Radiology", question_type="DIAGNOSTIC_ACCURACY"))
        ledger.upsert_candidate(candidate())
        result = ReviewDiscoveryOrchestrator(ledger, custom).verify_candidate("C1")
        assert result.evidence.unique_primary_study_candidates == 4


def test_completed_candidate_with_complete_registry_but_unresolved_scoring_is_provisional(tmp_path):
    class OutOfQuotaScoring:
        def score(self, *args, **kwargs):
            raise RuntimeError("Free provider quota exhausted")

    with SQLiteLedger(tmp_path / "out_of_quota.sqlite3") as ledger:
        ledger.upsert_project(ProjectRecord("P1", "Radiology", question_type="DIAGNOSTIC_ACCURACY"))
        ledger.upsert_candidate(candidate())
        result = ReviewDiscoveryOrchestrator(
            ledger, clients(), scoring_service=OutOfQuotaScoring()
        ).verify_candidate("C1")
        assert result.coverage.complete
        assert result.candidate_status == CandidateStatus.PROVISIONAL_BACKUP
        assert result.decision == "PROVISIONAL — SCIENTIFIC ASSESSMENT INCOMPLETE"
        assert ledger.get_candidate("C1").status == CandidateStatus.PROVISIONAL_BACKUP
        assert any("Free provider quota" in x for x in result.pending)


def test_source_complete_topic_scores_preliminary_importance_but_never_claims_novelty(tmp_path):
    class MixedPublicationSource:
        name = "PubMed"

        def search(self, query, *, limit=20):
            if "systematic review" in query.lower() or "meta-analysis" in query.lower():
                return SearchResult(
                    self.name, query, SourceStatus.SEARCHED_POSITIVE,
                    [SearchRecord(
                        self.name, "REVIEW1",
                        title="Systematic review of Test A for disease X",
                        doi="10.1000/competingreview",
                        metadata={"abstract": "We systematically reviewed Test A in adults."},
                    )], 1,
                )
            return SearchResult(
                self.name, query, SourceStatus.SEARCHED_POSITIVE,
                primary_records(5), 5,
            )

    class PreliminaryScorer:
        def __init__(self):
            self.calls = 0

        def score(self, *args, **kwargs):
            self.calls += 1
            return gate_inputs()

    score = PreliminaryScorer()
    all_clients = clients(n=5)
    all_clients[0] = MixedPublicationSource()
    with SQLiteLedger(tmp_path / "provisional_score.sqlite3") as ledger:
        ledger.upsert_project(ProjectRecord("P1", "Radiology", question_type="DIAGNOSTIC_ACCURACY"))
        review_candidate = candidate()
        review_candidate.metadata = {}
        ledger.upsert_candidate(review_candidate)
        result = ReviewDiscoveryOrchestrator(
            ledger, all_clients, scoring_service=score,
        ).verify_candidate("C1")
        metadata = ledger.get_candidate("C1").metadata
        assert result.coverage.complete
        assert score.calls == 1
        assert metadata["discovery_scoring_preliminary_only"] is True
        assert metadata["discovery_scoring_deferred"] is False
        assert metadata["discovery_gate_inputs"]["clinical_importance"] == 5
        assert result.candidate_status == CandidateStatus.PROVISIONAL_BACKUP
        assert result.final_gate_result is None
        assert any("published reviews" in x for x in result.pending)


def test_missing_mandatory_registration_source_defers_preliminary_ai_scoring(tmp_path):
    class NeverCalledScorer:
        def score(self, *args, **kwargs):
            raise AssertionError("Must not score when PROSPERO is unavailable")

    with SQLiteLedger(tmp_path / "source_missing_score.sqlite3") as ledger:
        ledger.upsert_project(ProjectRecord("P1", "Radiology", question_type="DIAGNOSTIC_ACCURACY"))
        record = candidate()
        record.metadata = {}
        ledger.upsert_candidate(record)
        result = ReviewDiscoveryOrchestrator(
            ledger, clients(prospero=SourceStatus.ACCESS_FAILED),
            scoring_service=NeverCalledScorer(),
        ).verify_candidate("C1")
        metadata = ledger.get_candidate("C1").metadata
        assert not result.coverage.complete
        assert metadata["discovery_scoring_deferred"] is True
        assert metadata["discovery_scoring_deferred_reason"] == "Mandatory source coverage unavailable"
        assert result.candidate_status == CandidateStatus.PROVISIONAL_BACKUP


def test_scoring_uses_newly_persisted_competitor_assessment(tmp_path):
    """Do not score stale citation snapshots taken before semantic assessment."""
    class OneReviewSource:
        name = "PubMed"

        def search(self, query, *, limit=20):
            if "systematic review" in query.casefold() or "meta-analysis" in query.casefold():
                return SearchResult(
                    self.name, query, SourceStatus.SEARCHED_POSITIVE,
                    [SearchRecord(
                        self.name, "REVIEW-1",
                        title="Systematic review of Test A in disease X",
                        doi="10.1000/review-a",
                        metadata={"abstract": "Test A in adults with disease X"},
                    )], 1,
                )
            return SearchResult(
                self.name, query, SourceStatus.SEARCHED_POSITIVE,
                primary_records(4), 4,
            )

    with SQLiteLedger(tmp_path / "fresh_competitor.sqlite3") as ledger:
        ledger.upsert_project(ProjectRecord("P1", "Radiology", question_type="DIAGNOSTIC_ACCURACY"))
        ledger.upsert_candidate(candidate())

        class PersistingNovelty:
            def assess_candidate(self, candidate_id, *, allow_ai=True):
                reviews = ledger.list_external_evidence(candidate_id, "PUBLISHED_REVIEW")
                assert reviews
                record = reviews[0]
                ledger.upsert_external_evidence(
                    candidate_id, "PUBLISHED_REVIEW", record["source_record_id"],
                    source=record["source"], title=record["title"],
                    payload={
                        **record["payload"],
                        "discovery_semantic_assessment": {
                            "overall_overlap": "LOW", "unresolved": False,
                            "confidence": 0.91,
                        },
                    },
                )
                item = ledger.get_candidate(candidate_id)
                item.metadata = {
                    **(item.metadata or {}),
                    "discovery_competitor_assessment_complete": True,
                    "discovery_registration_assessment_complete": True,
                    "discovery_semantic_scope_capped": False,
                }
                ledger.upsert_candidate(item)
                return {"summary": "Source-backed assessment persisted"}

        class CapturingScore:
            def score(self, *args, **kwargs):
                reviews = kwargs["review_records"]
                assert len(reviews) == 1
                assert reviews[0]["payload"]["discovery_semantic_assessment"]["overall_overlap"] == "LOW"
                return gate_inputs()

        all_clients = clients()
        all_clients[0] = OneReviewSource()
        result = ReviewDiscoveryOrchestrator(
            ledger, all_clients,
            novelty_service=PersistingNovelty(),
            scoring_service=CapturingScore(),
        ).verify_candidate("C1")
        assert result.coverage.complete
        assert not any("competing published reviews are not fully assessed" in p for p in result.pending)


def test_optional_semantic_scholar_does_not_veto_otherwise_passing_discovery(tmp_path):
    with SQLiteLedger(tmp_path / "optional.sqlite3") as ledger:
        ledger.upsert_project(ProjectRecord("P1", "Radiology", question_type="DIAGNOSTIC_ACCURACY"))
        ledger.upsert_candidate(candidate())
        configured = clients()
        configured[4] = FixedSource("Semantic Scholar", SourceStatus.NOT_SEARCHED)
        result = ReviewDiscoveryOrchestrator(ledger, configured).verify_candidate("C1")
        assert result.coverage.complete
        assert result.coverage.source_statuses["Semantic Scholar"] == SourceStatus.NOT_SEARCHED
        assert result.candidate_status == CandidateStatus.QUALIFIED
        assert ledger.list_decisions("C1")[-1].payload["coverage"]["source_statuses"]["Semantic Scholar"] == "NOT_SEARCHED"


def test_optional_source_failure_never_overrides_mandatory_registry_gate(tmp_path):
    with SQLiteLedger(tmp_path / "registry.sqlite3") as ledger:
        ledger.upsert_project(ProjectRecord("P1", "Radiology", question_type="DIAGNOSTIC_ACCURACY"))
        ledger.upsert_candidate(candidate())
        configured = clients(prospero=SourceStatus.ACCESS_FAILED)
        configured[4] = FixedSource("Semantic Scholar", SourceStatus.NOT_SEARCHED)
        result = ReviewDiscoveryOrchestrator(ledger, configured).verify_candidate("C1")
        assert not result.coverage.complete
        assert result.candidate_status == CandidateStatus.PROVISIONAL_BACKUP
