from scimed_scout.gates import final_decision_from_audits
from scimed_scout.trials import TrialFamilyResolver, TrialPublication
from scimed_scout.usability import ArmBinary, OutcomeDatum, OutcomeType, TrialOutcomeLedger


def base_payload():
    return {
        "design": "RCT_ONLY",
        "verified_independent_rcts": 999,
        "verified_usable_rcts": 999,
        "meaningful_pooling": True,
        "clinical_question_novelty": 3,
        "overall_novelty": 3,
        "fatal_redundancy": False,
        "pico_coherent": True,
        "feasibility": "HIGH",
        "fatal_methodological_flaw": False,
        "clinical_importance": 4,
        "publication_potential": 4,
        "new_information_gain": 4,
        "publication_oriented_score": 75,
        "editorial_grade": "B",
        "unresolved_type_a": [],
        "sources": [{"source": "Registry", "status": "SEARCHED_NEGATIVE"}],
    }


def pub(i):
    return TrialPublication(
        publication_id=f"P{i}",
        title=f"Trial {i}",
        manually_verified_family_id=f"F{i}",
        independence_verified=True,
        randomization_verified=True,
        eligibility_verified=True,
    )


def ledger(i):
    return TrialOutcomeLedger(
        f"F{i}",
        [
            OutcomeDatum(
                f"O{i}",
                "Outcome",
                OutcomeType.BINARY,
                treatment_binary=ArmBinary(n=20, events=2),
                control_binary=ArmBinary(n=20, events=4),
            )
        ],
    )


def test_ai_supplied_counts_are_overwritten_by_deterministic_audits():
    audit = TrialFamilyResolver().audit([pub(i) for i in range(1, 7)])
    result = final_decision_from_audits(base_payload(), audit, [ledger(i) for i in range(1, 7)])
    assert result["decision"] == "DO NOT PROCEED"
    assert result["deterministic_evidence"]["verified_independent_rcts"] == 6
    assert result["deterministic_evidence"]["verified_usable_rcts"] == 6
