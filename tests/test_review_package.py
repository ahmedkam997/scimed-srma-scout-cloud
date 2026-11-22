from scimed_scout.domain import CandidateStatus, SourceStatus
from scimed_scout.review_package import build_review_package, export_review_package
from scimed_scout.sources.base import SearchResult
from scimed_scout.storage import CandidateRecord, ProjectRecord, SQLiteLedger
from scimed_scout.verification import SequentialDeepVerifier


class FakeSource:
    def __init__(self, name, status=SourceStatus.SEARCHED_NEGATIVE):
        self.name = name
        self.status = status

    def search(self, query, *, limit=20):
        return SearchResult(self.name, query, self.status, [], 0)


def clients():
    names = ["PubMed", "Europe PMC", "OpenAlex", "Crossref", "Semantic Scholar"]
    return [FakeSource(name) for name in names] + [
        FakeSource("PROSPERO"),
        FakeSource("OSF Registries", SourceStatus.MANUAL_VERIFIED),
        FakeSource("ClinicalTrials.gov", SourceStatus.ACCESS_FAILED),
    ]


def gate_inputs():
    return {
        "design_framework_verified": True,
        "meaningful_synthesis": True,
        "clinical_question_novelty": 4,
        "overall_novelty": 4,
        "fatal_redundancy": False,
        "question_framework_coherent": True,
        "feasibility": "HIGH",
        "fatal_methodological_flaw": False,
        "clinical_importance": 5,
        "publication_potential": 5,
        "new_information_gain": 4,
        "publication_oriented_score": 86,
        "editorial_grade": "B",
    }


def add_candidate(ledger, cid, title, complete=True):
    metadata = {"gate_inputs": gate_inputs()}
    if complete:
        metadata.update({"study_audit_complete": True, "synthesis_audit_complete": True})
    ledger.upsert_candidate(
        CandidateRecord(
            candidate_id=cid,
            project_id="P1",
            title=title,
            specialty="Radiology",
            question_type="DIAGNOSTIC_ACCURACY",
            review_question=f"What is the diagnostic accuracy of {title}?",
            population="Adults with suspected disease",
            intervention_exposure_index_test=title,
            comparator_reference="Reference standard",
            outcomes=["sensitivity", "specificity"],
            eligible_designs=["diagnostic accuracy"],
            rationale="Clinically relevant",
            novelty_hypothesis="Potential gap",
            search_terms=[title, "diagnostic accuracy"],
            metadata=metadata,
        )
    )
    if complete:
        for i in range(1, 5):
            ledger.upsert_payload(
                "study_families",
                cid,
                f"F{i}",
                {
                    "family_id": f"F{i}",
                    "independence_verified": True,
                    "eligibility_verified": True,
                    "design_verified": True,
                },
            )
            ledger.upsert_payload(
                "outcomes",
                cid,
                f"O{i}",
                {
                    "outcome_id": f"O{i}",
                    "family_id": f"F{i}",
                    "usability_status": "VERIFIED_USABLE",
                    "principal": True,
                },
                family_id=f"F{i}",
            )


def test_review_package_contains_multiple_options_and_defers_winner_to_chatgpt(tmp_path):
    with SQLiteLedger(tmp_path / "review.sqlite3") as ledger:
        ledger.upsert_project(ProjectRecord("P1", "Radiology", question_type="DIAGNOSTIC_ACCURACY"))
        add_candidate(ledger, "C1", "MRI sign A")
        add_candidate(ledger, "C2", "CT sign B")
        add_candidate(ledger, "C3", "Ultrasound sign C")

        result = SequentialDeepVerifier(ledger, clients()).run(
            "P1",
            min_verify=3,
            max_verify=3,
            final_options=3,
        )
        package = build_review_package(ledger, result)

        assert package["selection_policy"]["system_does_not_select_winner"] is True
        assert package["selection_policy"]["chatgpt_is_final_comparator"] is True
        assert package["selection_policy"]["final_option_candidate_ids"] == ["C1", "C2", "C3"]
        assert len(package["options"]) == 3
        assert all(option["candidate_status"] == CandidateStatus.QUALIFIED.value for option in package["options"])
        assert "rank all included options" in package["review_instructions"].lower()

        target = tmp_path / "chatgpt_review.json"
        exported = export_review_package(ledger, result, target)
        assert exported.exists()
        assert '"package_type": "SCIMED_FINAL_CHATGPT_REVIEW"' in exported.read_text(encoding="utf-8")


def test_review_package_excludes_nonqualified_option_when_fewer_than_three_qualify(tmp_path):
    with SQLiteLedger(tmp_path / "review.sqlite3") as ledger:
        ledger.upsert_project(ProjectRecord("P1", "Radiology", question_type="DIAGNOSTIC_ACCURACY"))
        add_candidate(ledger, "C1", "MRI sign A")
        add_candidate(ledger, "C2", "CT sign B")
        add_candidate(ledger, "C3", "Ultrasound sign C", complete=False)

        result = SequentialDeepVerifier(ledger, clients()).run(
            "P1",
            min_verify=3,
            max_verify=3,
            final_options=3,
        )
        package = build_review_package(ledger, result)

        assert len(package["options"]) == 2
        assert package["selection_policy"]["all_included_options_are_first_choice_eligible"] is True
        assert package["selection_policy"]["provisional_or_pending_options_allowed"] is False
        assert package["selection_policy"]["available_fully_qualified_options"] == 2
        assert package["selection_policy"]["comparison_ready"] is True
        assert package["selection_policy"]["shortfall"] == 1
        assert package["selection_policy"]["final_option_candidate_ids"] == ["C1", "C2"]
        assert all(option["candidate_status"] == CandidateStatus.QUALIFIED.value for option in package["options"])
        assert "C3" not in package["selection_policy"]["final_option_candidate_ids"]
