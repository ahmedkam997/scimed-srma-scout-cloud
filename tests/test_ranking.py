from scimed_scout.domain import CandidateStatus
from scimed_scout.ranking import CandidateRankingService, preliminary_rank
from scimed_scout.storage import CandidateRecord, ProjectRecord, SQLiteLedger


def test_preliminary_ranking_prioritizes_complete_specific_candidate(tmp_path):
    with SQLiteLedger(tmp_path / "rank.sqlite3") as ledger:
        ledger.upsert_project(ProjectRecord("P1", "Radiology"))
        strong = CandidateRecord(
            candidate_id="C-STRONG",
            project_id="P1",
            title="Accuracy of MRI sign X for disease Y",
            specialty="Radiology",
            question_type="DIAGNOSTIC_ACCURACY",
            review_question="What is the diagnostic accuracy of MRI sign X for disease Y?",
            population="Adults with suspected disease Y",
            intervention_exposure_index_test="MRI sign X",
            comparator_reference="Histopathology",
            outcomes=["sensitivity", "specificity"],
            eligible_designs=["diagnostic accuracy"],
            rationale="Changes diagnostic decision-making",
            novelty_hypothesis="Newer MRI sequences may not be synthesized",
            search_terms=["MRI sign X", "disease Y", "diagnostic accuracy"],
        )
        weak = CandidateRecord(
            candidate_id="C-WEAK",
            project_id="P1",
            title="Imaging in disease",
            specialty="Radiology",
            question_type="OTHER",
            review_question="Imaging in various diseases and different outcomes",
        )
        ledger.upsert_candidate(strong)
        ledger.upsert_candidate(weak)

        assert preliminary_rank(strong).score > preliminary_rank(weak).score

        ranked = CandidateRankingService(ledger).rank_project("P1", top_n=1)
        assert ranked[0].candidate_id == "C-STRONG"
        assert ledger.get_candidate("C-STRONG").status == CandidateStatus.SHORTLISTED
        assert ledger.get_candidate("C-WEAK").status == CandidateStatus.DISCOVERED
