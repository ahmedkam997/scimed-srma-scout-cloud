import pytest

from scimed_scout.gates import final_decision

def valid_payload():
    return {
        "design":"RCT_ONLY","verified_independent_rcts":7,"verified_usable_rcts":7,
        "meaningful_pooling":True,"clinical_question_novelty":3,"overall_novelty":3,
        "fatal_redundancy":False,"pico_coherent":True,"feasibility":"HIGH",
        "fatal_methodological_flaw":False,"clinical_importance":4,"publication_potential":4,
        "new_information_gain":4,"publication_oriented_score":75,"editorial_grade":"B",
        "unresolved_type_a":[]
    }

def test_all_gates_pass():
    assert final_decision(valid_payload())["decision"] == "PROCEED — FIRST-CHOICE"

def test_access_uncertainty_blocks_proceed():
    p = valid_payload(); p["unresolved_type_a"] = ["PROSPERO ACCESS_FAILED"]
    assert final_decision(p)["decision"] == "DO NOT PROCEED"

def test_less_than_seven_usable_blocks_proceed():
    p = valid_payload(); p["verified_usable_rcts"] = 6
    assert final_decision(p)["decision"] == "DO NOT PROCEED"


def test_independent_population_threshold_is_separate_from_usable_threshold():
    payload = valid_payload()
    payload["verified_independent_rcts"] = 6
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
    del payload[field]
    assert final_decision(payload)["decision"] == "DO NOT PROCEED"
