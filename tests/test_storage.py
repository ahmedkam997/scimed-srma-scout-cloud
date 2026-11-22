from scimed_scout.domain import CandidateStatus, SourceStatus
from scimed_scout.storage import (
    CandidateRecord,
    DecisionRecord,
    ProjectRecord,
    SearchLogRecord,
    SQLiteLedger,
)


def test_sqlite_ledger_persists_project_candidate_evidence_and_history(tmp_path):
    db = tmp_path / "scout.sqlite3"

    with SQLiteLedger(db) as ledger:
        ledger.upsert_project(ProjectRecord("P1", "Radiology", question_type="DIAGNOSTIC_ACCURACY"))
        ledger.upsert_candidate(
            CandidateRecord(
                candidate_id="C1",
                project_id="P1",
                title="Index test versus reference standard",
                specialty="Radiology",
                question_type="DIAGNOSTIC_ACCURACY",
                review_question="What is the diagnostic accuracy of the index test?",
                outcomes=["sensitivity", "specificity"],
                eligible_designs=["prospective diagnostic accuracy", "retrospective diagnostic accuracy"],
                search_terms=["index test", "reference standard"],
            )
        )
        ledger.upsert_payload("study_families", "C1", "F1", {"family_id": "F1", "verified": True})
        ledger.upsert_payload("studies", "C1", "S1", {"study_id": "S1", "title": "Study 1"}, family_id="F1")
        ledger.upsert_payload("outcomes", "C1", "O1", {"outcome_id": "O1", "tp": 30, "fp": 4, "fn": 5, "tn": 61}, family_id="F1")
        ledger.upsert_external_evidence(
            "C1",
            "PUBLISHED_REVIEW",
            "10.1000/review",
            source="Crossref",
            title="Prior review",
            payload={"year": 2025},
        )
        ledger.upsert_external_evidence(
            "C1",
            "REGISTRATION",
            "CRD420260000001",
            source="PROSPERO",
            title="Protocol",
        )
        ledger.upsert_external_evidence(
            "C1",
            "ONGOING_STUDY",
            "NCT12345678",
            source="ClinicalTrials.gov",
            title="Ongoing study",
        )
        ledger.append_search_log(
            SearchLogRecord(
                project_id="P1",
                candidate_id="C1",
                source="PubMed",
                query="index test diagnostic accuracy",
                status=SourceStatus.SEARCHED_POSITIVE,
                result_count=12,
            )
        )
        ledger.append_decision(
            DecisionRecord(
                decision_id="D1",
                project_id="P1",
                candidate_id="C1",
                decision="PROVISIONAL_BACKUP",
                stage="NOVELTY_AUDIT",
                reason="One registry comparison remains unresolved",
                payload={"type_a": ["registry comparison"]},
            )
        )
        ledger.add_query("P1", "C1", "PubMed", "index test diagnostic accuracy", "primary search")
        ledger.update_checkpoint("P1", stage="DEEP_VERIFY", progress=45, message="checking study families")

    with SQLiteLedger(db) as reopened:
        project = reopened.get_project("P1")
        assert project is not None
        assert project.stage == "DEEP_VERIFY"
        assert project.progress == 45

        candidate = reopened.get_candidate("C1")
        assert candidate is not None
        assert candidate.question_type == "DIAGNOSTIC_ACCURACY"
        assert candidate.outcomes == ["sensitivity", "specificity"]

        assert reopened.list_payloads("study_families", "C1")[0]["family_id"] == "F1"
        assert reopened.list_payloads("studies", "C1")[0]["study_id"] == "S1"
        assert reopened.list_payloads("outcomes", "C1")[0]["tp"] == 30

        evidence = reopened.list_external_evidence("C1")
        assert {item["evidence_type"] for item in evidence} == {
            "PUBLISHED_REVIEW",
            "REGISTRATION",
            "ONGOING_STUDY",
        }
        assert reopened.list_search_log("C1")[0].status == SourceStatus.SEARCHED_POSITIVE
        assert reopened.list_decisions("C1")[0].decision == "PROVISIONAL_BACKUP"
        assert reopened.list_queries("C1")[0]["purpose"] == "primary search"


def test_candidate_status_is_persistent_and_filterable(tmp_path):
    db = tmp_path / "scout.sqlite3"
    with SQLiteLedger(db) as ledger:
        ledger.upsert_project(ProjectRecord("P1", "Neurology"))
        ledger.upsert_candidate(CandidateRecord("C1", "P1", "Topic", "Neurology"))
        ledger.set_candidate_status("C1", CandidateStatus.REJECTED)
        assert ledger.get_candidate("C1").status == CandidateStatus.REJECTED
        assert [x.candidate_id for x in ledger.list_candidates("P1", CandidateStatus.REJECTED)] == ["C1"]


def test_external_evidence_type_is_validated(tmp_path):
    with SQLiteLedger(tmp_path / "x.sqlite3") as ledger:
        ledger.upsert_project(ProjectRecord("P1", "Medicine"))
        ledger.upsert_candidate(CandidateRecord("C1", "P1", "Topic", "Medicine"))
        try:
            ledger.upsert_external_evidence("C1", "NOT_A_REAL_TYPE", "X")
        except ValueError as exc:
            assert "Unsupported evidence type" in str(exc)
        else:
            raise AssertionError("invalid evidence type should fail")
