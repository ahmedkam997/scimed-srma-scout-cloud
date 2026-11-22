from scimed_scout.discovery.models import (
    DiscoveryCandidateResult,
    DiscoveryEvidenceSnapshot,
    DiscoveryRunResult,
)
from scimed_scout.discovery.review_package import build_discovery_review_package
from scimed_scout.domain import CandidateStatus, SourceStatus
from scimed_scout.ranking import RankingResult
from scimed_scout.storage import CandidateRecord, ProjectRecord, SQLiteLedger
from scimed_scout.verification.coverage import VerificationCoverage


def test_package_contains_only_qualified_review_topics_and_states_scope(tmp_path):
    with SQLiteLedger(tmp_path / "p.sqlite3") as ledger:
        ledger.upsert_project(ProjectRecord("P1", "Cardiology"))
        candidate = CandidateRecord(
            "C1",
            "P1",
            "Strong review topic",
            "Cardiology",
            question_type="EFFECTIVENESS",
            review_question="Does intervention X improve outcome Y?",
            population="Adults with disease Z",
            intervention_exposure_index_test="Intervention X",
            comparator_reference="Usual care",
            outcomes=["Outcome Y"],
            eligible_designs=["randomized and non-randomized comparative studies"],
        )
        candidate.status = CandidateStatus.QUALIFIED
        ledger.upsert_candidate(candidate)

        coverage = VerificationCoverage(
            source_statuses={
                "PubMed": SourceStatus.SEARCHED_POSITIVE,
                "Europe PMC": SourceStatus.SEARCHED_POSITIVE,
                "PROSPERO": SourceStatus.SEARCHED_NEGATIVE,
                "OSF Registries": SourceStatus.MANUAL_VERIFIED,
                "ClinicalTrials.gov": SourceStatus.SEARCHED_NEGATIVE,
            },
            blockers=(),
        )
        evidence = DiscoveryEvidenceSnapshot(6, 4, 2, ("Europe PMC", "PubMed"))
        gate_result = {
            "decision": "QUALIFIED — FIRST-CHOICE REVIEW TOPIC",
            "all_discovery_gates_passed": True,
            "unresolved_type_a": [],
            "gates": [],
        }
        verification = DiscoveryCandidateResult(
            candidate_id="C1",
            ranking_score=90,
            coverage=coverage,
            evidence=evidence,
            pending=[],
            decision="QUALIFIED — FIRST-CHOICE REVIEW TOPIC",
            candidate_status=CandidateStatus.QUALIFIED,
            final_gate_result=gate_result,
        )
        run = DiscoveryRunResult(
            project_id="P1",
            ranked=[RankingResult("C1", 90, ("specific question",))],
            verified=[verification],
            final_option_candidate_ids=["C1"],
            qualified_option_candidate_ids=["C1"],
            desired_options=3,
        )

        package = build_discovery_review_package(ledger, run)
        assert package["scope"] == "REVIEW_TOPIC_DISCOVERY_ONLY"
        assert package["selection_policy"]["full_review_execution_out_of_scope"] is True
        assert package["selection_policy"]["minimum_unique_primary_study_candidates"] == 4
        assert len(package["options"]) == 1
        assert package["options"][0]["candidate_id"] == "C1"
        assert "full-text eligibility" in package["review_instructions"].lower()
