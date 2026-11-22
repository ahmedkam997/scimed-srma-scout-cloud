from scimed_scout.discovery import final_discovery_decision
from scimed_scout.domain import SourceStatus


def passing_payload():
    return {
        "design_framework_defined": True,
        "unique_primary_study_candidates": 4,
        "complete_literature_sources": 3,
        "meaningful_synthesis_plausible": True,
        "clinical_question_novelty": 4,
        "overall_novelty": 4,
        "fatal_redundancy": False,
        "question_framework_coherent": True,
        "feasibility": "HIGH",
        "fatal_methodological_flaw": False,
        "clinical_importance": 5,
        "publication_potential": 5,
        "new_information_gain": 4,
        "publication_oriented_score": 85,
        "editorial_grade": "B",
        "sources": [
            {"source": "PubMed", "status": SourceStatus.SEARCHED_POSITIVE.value},
            {"source": "Europe PMC", "status": SourceStatus.SEARCHED_POSITIVE.value},
            {"source": "PROSPERO", "status": SourceStatus.SEARCHED_NEGATIVE.value},
            {"source": "OSF Registries", "status": SourceStatus.MANUAL_VERIFIED.value},
        ],
        "unresolved_type_a": [],
    }


def test_first_choice_review_topic_requires_all_discovery_gates():
    result = final_discovery_decision(passing_payload())
    assert result["decision"] == "QUALIFIED — FIRST-CHOICE REVIEW TOPIC"
    assert result["all_discovery_gates_passed"] is True


def test_three_primary_study_candidates_fail_discovery_threshold():
    payload = passing_payload()
    payload["unique_primary_study_candidates"] = 3
    result = final_discovery_decision(payload)
    assert result["decision"] == "DO NOT INCLUDE IN FINAL DISCOVERY LIST"
    assert result["gates"][1]["passed"] is False


def test_source_failure_cannot_support_no_redundancy_inference():
    payload = passing_payload()
    payload["sources"][2]["status"] = SourceStatus.ACCESS_FAILED.value
    result = final_discovery_decision(payload)
    assert result["decision"] == "DO NOT INCLUDE IN FINAL DISCOVERY LIST"
    assert result["gates"][6]["passed"] is False


def test_type_a_issue_blocks_otherwise_passing_topic():
    payload = passing_payload()
    payload["unresolved_type_a"] = ["PROSPERO overlap unresolved"]
    result = final_discovery_decision(payload)
    assert result["all_discovery_gates_passed"] is True
    assert result["decision"] == "DO NOT INCLUDE IN FINAL DISCOVERY LIST"
