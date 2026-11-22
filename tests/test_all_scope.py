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
