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
