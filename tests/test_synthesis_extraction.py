import json

from scimed_scout.ai import StaticAIProvider
from scimed_scout.storage import CandidateRecord
from scimed_scout.synthesis import EvidenceScope, SynthesisDataExtractor, to_outcome_datum
from scimed_scout.usability import UsabilityStatus, assess_outcome


def candidate(question_type="DIAGNOSTIC_ACCURACY"):
    return CandidateRecord(
        candidate_id="C1",
        project_id="P1",
        title="Test A",
        specialty="Radiology",
        question_type=question_type,
        review_question="What is the diagnostic accuracy of Test A?",
        population="Adults",
        intervention_exposure_index_test="Test A",
        comparator_reference="Histopathology",
        outcomes=["Sensitivity", "Specificity"],
        eligible_designs=["diagnostic accuracy"],
    )


def field(value, evidence, confidence=0.96):
    return {"value": value, "evidence": evidence, "confidence": confidence}


def blank_arm():
    return {
        "n": field(None, "", 0),
        "events": field(None, "", 0),
        "proportion": field(None, "", 0),
    }


def blank_continuous():
    return {
        key: field(None, "", 0)
        for key in ["n", "mean", "sd", "change_mean", "change_sd", "median", "q1", "q3"]
    }


def blank_diagnostic():
    return {
        key: field(None, "", 0)
        for key in [
            "index_test", "reference_standard", "threshold", "tp", "fp", "fn", "tn",
            "sensitivity", "specificity", "diseased_n", "non_diseased_n"
        ]
    }


def base_data():
    data = {
        "treatment_binary": blank_arm(),
        "control_binary": blank_arm(),
        "single_binary": blank_arm(),
        "treatment_continuous": blank_continuous(),
        "control_continuous": blank_continuous(),
        "diagnostic": blank_diagnostic(),
    }
    for key in [
        "hr", "hr_ci_lower", "hr_ci_upper", "log_hr", "se_log_hr", "o_minus_e", "variance",
        "common_or", "common_or_ci_lower", "common_or_ci_upper", "person_time", "rate_events",
        "correlation", "correlation_n", "effect_estimate", "effect_se", "effect_ci_lower",
        "effect_ci_upper", "effect_measure", "performance_estimate", "performance_se",
        "performance_ci_lower", "performance_ci_upper", "performance_metric",
    ]:
        data[key] = field(None if key not in {"effect_measure", "performance_metric"} else "", "", 0)
    return data


def response(outcome_type, data, name="Sensitivity and specificity", signals=None):
    return json.dumps({
        "outcomes": [{
            "outcome_name": name,
            "outcome_type": outcome_type,
            "follow_up": "",
            "overall_confidence": 0.96,
            "unresolved_fields": [],
            "data": data,
            "signals": signals or {
                "graph_only": {"value": False, "evidence": ""},
                "kaplan_meier": {"value": False, "evidence": ""},
                "median_iqr_only": {"value": False, "evidence": ""},
                "qualitative_findings_present": {"value": False, "evidence": ""},
            },
        }],
        "no_data_reason": "",
    })


def record(text):
    return {
        "source_record_id": "S1",
        "source": "Europe PMC",
        "title": "Study one",
        "payload": {"metadata": {"abstract": text}},
    }


def study():
    return {"study_id": "S1", "title": "Study one", "family_id": "F1"}


def test_complete_dta_2x2_is_extracted_and_verified_usable():
    sentence = "The 2x2 table showed TP 40, FN 10, FP 5, and TN 45."
    data = base_data()
    data["diagnostic"].update({
        "index_test": field("Test A", "Test A"),
        "reference_standard": field("Histopathology", "Histopathology"),
        "tp": field(40, sentence),
        "fn": field(10, sentence),
        "fp": field(5, sentence),
        "tn": field(45, sentence),
    })
    text = f"Test A was compared with Histopathology. {sentence}"
    extractor = SynthesisDataExtractor(StaticAIProvider(response("DIAGNOSTIC_ACCURACY", data)))
    extracted = extractor.extract(candidate(), study(), record(text), evidence_scope=EvidenceScope.TITLE_ABSTRACT)
    datum = to_outcome_datum(candidate(), "O1", extracted.outcomes[0])
    result = assess_outcome(datum)

    assert extracted.outcomes[0].overall_confidence == 0.96
    assert datum.diagnostic.tp == 40
    assert datum.diagnostic.tn == 45
    assert result.status == UsabilityStatus.VERIFIED_USABLE


def test_dta_sensitivity_specificity_and_denominators_reconstruct_exact_2x2():
    sentence = "Sensitivity was 80% among 50 diseased participants and specificity was 90% among 50 non-diseased participants."
    data = base_data()
    data["diagnostic"].update({
        "sensitivity": field(0.80, sentence),
        "specificity": field(0.90, sentence),
        "diseased_n": field(50, sentence),
        "non_diseased_n": field(50, sentence),
    })
    extractor = SynthesisDataExtractor(StaticAIProvider(response("DIAGNOSTIC_ACCURACY", data)))
    extracted = extractor.extract(candidate(), study(), record(sentence))
    datum = to_outcome_datum(candidate(), "O1", extracted.outcomes[0])
    result = assess_outcome(datum)

    assert datum.diagnostic.reconstruction_completed
    assert (datum.diagnostic.tp, datum.diagnostic.fn) == (40, 10)
    assert (datum.diagnostic.tn, datum.diagnostic.fp) == (45, 5)
    assert result.status == UsabilityStatus.VERIFIED_USABLE


def test_hallucinated_number_is_removed_and_cannot_be_verified_usable():
    sentence = "The 2x2 table showed TP 40, FN 10, FP 5, and TN 45."
    data = base_data()
    data["diagnostic"].update({
        "tp": field(99, sentence),
        "fn": field(10, sentence),
        "fp": field(5, sentence),
        "tn": field(45, sentence),
    })
    extractor = SynthesisDataExtractor(StaticAIProvider(response("DIAGNOSTIC_ACCURACY", data)))
    extracted = extractor.extract(candidate(), study(), record(sentence))
    datum = to_outcome_datum(candidate(), "O1", extracted.outcomes[0])

    assert extracted.outcomes[0].overall_confidence <= 0.79
    assert datum.diagnostic.tp is None
    assert assess_outcome(datum).status != UsabilityStatus.VERIFIED_USABLE


def test_binary_continuous_and_hr_routes_convert_to_existing_usability_engine():
    binary_data = base_data()
    binary_sentence = "There were 5 events among 100 treated patients and 9 events among 100 controls."
    binary_data["treatment_binary"].update({
        "n": field(100, binary_sentence),
        "events": field(5, binary_sentence),
    })
    binary_data["control_binary"].update({
        "n": field(100, binary_sentence),
        "events": field(9, binary_sentence),
    })
    binary = SynthesisDataExtractor(StaticAIProvider(response("BINARY", binary_data, "Mortality"))).extract(
        candidate("EFFECTIVENESS"), study(), record(binary_sentence)
    )
    assert assess_outcome(to_outcome_datum(candidate("EFFECTIVENESS"), "B", binary.outcomes[0])).status == UsabilityStatus.VERIFIED_USABLE

    continuous_data = base_data()
    continuous_sentence = "Mean pain was 3.1 (SD 1.2) in 40 treated patients and 4.2 (SD 1.4) in 42 controls."
    continuous_data["treatment_continuous"].update({
        "n": field(40, continuous_sentence),
        "mean": field(3.1, continuous_sentence),
        "sd": field(1.2, continuous_sentence),
    })
    continuous_data["control_continuous"].update({
        "n": field(42, continuous_sentence),
        "mean": field(4.2, continuous_sentence),
        "sd": field(1.4, continuous_sentence),
    })
    continuous = SynthesisDataExtractor(StaticAIProvider(response("CONTINUOUS", continuous_data, "Pain"))).extract(
        candidate("EFFECTIVENESS"), study(), record(continuous_sentence)
    )
    assert assess_outcome(to_outcome_datum(candidate("EFFECTIVENESS"), "C", continuous.outcomes[0])).status == UsabilityStatus.VERIFIED_USABLE

    hr_data = base_data()
    hr_sentence = "The hazard ratio for mortality was 0.78 (95% CI 0.62 to 0.98)."
    hr_data.update({
        "hr": field(0.78, hr_sentence),
        "hr_ci_lower": field(0.62, hr_sentence),
        "hr_ci_upper": field(0.98, hr_sentence),
    })
    hr = SynthesisDataExtractor(StaticAIProvider(response("TIME_TO_EVENT", hr_data, "Mortality"))).extract(
        candidate("EFFECTIVENESS"), study(), record(hr_sentence)
    )
    assert assess_outcome(to_outcome_datum(candidate("EFFECTIVENESS"), "H", hr.outcomes[0])).status == UsabilityStatus.VERIFIED_USABLE
