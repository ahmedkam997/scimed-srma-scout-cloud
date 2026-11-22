from scimed_scout.ai.discovery import build_discovery_prompt
from scimed_scout.cli import _open_scope, _question_type_scope


def test_all_specialty_and_all_question_type_are_open_scope():
    prompt = build_discovery_prompt(
        specialty="ALL",
        question_types=["ALL"],
        design_scope=["ALL"],
        count=8,
    )
    assert "Specialty scope: all medical specialties" in prompt
    assert "Question-type scope: all appropriate review-question types" in prompt
    assert "Study-design scope: all appropriate eligible study designs" in prompt
    assert "Specialty scope: ALL" not in prompt


def test_cli_all_question_type_becomes_unrestricted_scope():
    assert _question_type_scope([], "ALL") == []
    assert _question_type_scope(["ALL"], "DIAGNOSTIC_ACCURACY") == []
    assert _question_type_scope(["PROGNOSIS"], "ALL") == ["PROGNOSIS"]


def test_cli_all_design_scope_is_removed_as_literal_value():
    assert _open_scope(["ALL"]) == []
    assert _open_scope(["ALL", "cohort studies"]) == ["cohort studies"]


def test_all_specialty_keeps_specific_specialty_returned_by_ai(tmp_path):
    import json
    from scimed_scout.ai import CandidateDiscoveryService, StaticAIProvider
    from scimed_scout.storage import ProjectRecord, SQLiteLedger

    payload = {
        "candidates": [{
            "title": "Stroke imaging review",
            "specialty": "Neurology",
            "question_type": "DIAGNOSTIC_ACCURACY",
            "review_question": "What is the accuracy of imaging test X for acute stroke?",
            "population": "Adults with suspected acute stroke",
            "intervention_exposure_index_test": "Imaging test X",
            "comparator_reference": "Reference standard",
            "outcomes": ["sensitivity", "specificity"],
            "eligible_designs": ["diagnostic accuracy studies"],
            "rationale": "Important diagnostic question",
            "novelty_hypothesis": "Current reviews may not cover the latest test generation",
            "search_terms": ["stroke", "test X"],
        }]
    }
    with SQLiteLedger(tmp_path / "all.sqlite3") as ledger:
        ledger.upsert_project(ProjectRecord("P1", "ALL", question_type="ALL"))
        records = CandidateDiscoveryService(
            StaticAIProvider(json.dumps(payload)),
            ledger,
        ).generate_and_store(
            project_id="P1",
            specialty="ALL",
            question_types=[],
            count=1,
        )
        assert records[0].specialty == "Neurology"
