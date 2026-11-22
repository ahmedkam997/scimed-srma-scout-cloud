import pytest

from scimed_scout.gates import final_decision

def valid_payload():
    return {
        "design_framework_verified": True,
        "verified_independent_studies": 4,
        "verified_usable_studies": 4,
        "meaningful_synthesis": True,
        "clinical_question_novelty": 3,
        "overall_novelty": 3,
        "fatal_redundancy": False,
        "question_framework_coherent": True,
        "feasibility": "HIGH",
        "fatal_methodological_flaw": False,
        "clinical_importance": 4,
        "publication_potential": 4,
        "new_information_gain": 4,
        "publication_oriented_score": 75,
        "editorial_grade": "B",
        "unresolved_type_a": [],
    }

def test_all_gates_pass():
    p = valid_payload()
    p["sources"] = [{"source": "Registry", "status": "SEARCHED_NEGATIVE"}]
    assert final_decision(p)["decision"] == "PROCEED — FIRST-CHOICE"

def test_access_uncertainty_blocks_proceed():
    p = valid_payload()
    p["sources"] = [{"source": "Registry", "status": "SEARCHED_NEGATIVE"}]
    p["unresolved_type_a"] = ["PROSPERO ACCESS_FAILED"]
    assert final_decision(p)["decision"] == "DO NOT PROCEED"

def test_less_than_four_usable_blocks_proceed():
    p = valid_payload()
    p["sources"] = [{"source": "Registry", "status": "SEARCHED_NEGATIVE"}]
    p["verified_usable_studies"] = 3
    assert final_decision(p)["decision"] == "DO NOT PROCEED"

def test_independent_study_threshold_is_separate_from_usable_threshold():
    payload = valid_payload()
    payload["sources"] = [{"source": "Registry", "status": "SEARCHED_NEGATIVE"}]
    payload["verified_independent_studies"] = 3
    decision = final_decision(payload)
    assert len(decision["gates"]) == 15
    assert decision["decision"] == "DO NOT PROCEED"
    assert decision["gates"][1]["passed"] is False
    assert decision["gates"][2]["passed"] is True

@pytest.mark.parametrize("status", ["ACCESS_FAILED", "PARTIAL", "NOT_SEARCHED", None])
def test_inconclusive_source_audits_block_proceed(status):
    payload = valid_payload()
    payload["sources"] = [{"source": "Registry", "status": status}]
    assert final_decision(payload)["decision"] == "DO NOT PROCEED"

def test_conclusive_source_audit_allows_proceed():
    payload = valid_payload()
    payload["sources"] = [{"source": "Registry", "status": "SEARCHED_NEGATIVE"}]
    assert final_decision(payload)["decision"] == "PROCEED — FIRST-CHOICE"

@pytest.mark.parametrize("field", ["fatal_redundancy", "fatal_methodological_flaw"])
def test_missing_fatal_risk_assessment_blocks_proceed(field):
    payload = valid_payload()
    payload["sources"] = [{"source": "Registry", "status": "SEARCHED_NEGATIVE"}]
    del payload[field]
    assert final_decision(payload)["decision"] == "DO NOT PROCEED"

def test_legacy_rct_payload_still_works_but_uses_four_study_threshold():
    payload = valid_payload()
    payload.pop("design_framework_verified")
    payload.pop("verified_independent_studies")
    payload.pop("verified_usable_studies")
    payload.pop("meaningful_synthesis")
    payload.pop("question_framework_coherent")
    payload.update({
        "design": "RCT_ONLY",
        "verified_independent_rcts": 4,
        "verified_usable_rcts": 4,
        "meaningful_pooling": True,
        "pico_coherent": True,
        "sources": [{"source": "Registry", "status": "SEARCHED_NEGATIVE"}],
    })
    assert final_decision(payload)["decision"] == "PROCEED — FIRST-CHOICE"
