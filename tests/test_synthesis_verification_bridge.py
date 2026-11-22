import json

from scimed_scout.ai import StaticAIProvider
from scimed_scout.storage import CandidateRecord, ProjectRecord, SQLiteLedger
from scimed_scout.synthesis import SynthesisDataExtractor
from scimed_scout.verification import SynthesisVerificationBridge, snapshot_from_ledger


def candidate():
    return CandidateRecord(
        candidate_id="C1",
        project_id="P1",
        title="Test A accuracy",
        specialty="Radiology",
        question_type="DIAGNOSTIC_ACCURACY",
        review_question="What is the diagnostic accuracy of Test A?",
        population="Adults",
        intervention_exposure_index_test="Test A",
        comparator_reference="Histopathology",
        outcomes=["Sensitivity", "Specificity"],
        eligible_designs=["diagnostic accuracy"],
    )


def field(value, evidence, confidence=0.96):
    return {"value": value, "evidence": evidence, "confidence": confidence}


def dta_response(sentence):
    blank = lambda: {"value": None, "evidence": "", "confidence": 0.0}
    diagnostic = {
        "index_test": {"value": "Test A", "evidence": "Test A", "confidence": 0.96},
        "reference_standard": {"value": "Histopathology", "evidence": "Histopathology", "confidence": 0.96},
        "threshold": {"value": "", "evidence": "", "confidence": 0.0},
        "tp": field(40, sentence),
        "fp": field(5, sentence),
        "fn": field(10, sentence),
        "tn": field(45, sentence),
        "sensitivity": blank(),
        "specificity": blank(),
        "diseased_n": blank(),
        "non_diseased_n": blank(),
    }
    data = {
        "treatment_binary": {"n": blank(), "events": blank(), "proportion": blank()},
        "control_binary": {"n": blank(), "events": blank(), "proportion": blank()},
        "single_binary": {"n": blank(), "events": blank(), "proportion": blank()},
        "treatment_continuous": {k: blank() for k in ["n", "mean", "sd", "change_mean", "change_sd", "median", "q1", "q3"]},
        "control_continuous": {k: blank() for k in ["n", "mean", "sd", "change_mean", "change_sd", "median", "q1", "q3"]},
        "diagnostic": diagnostic,
    }
    for key in [
        "hr", "hr_ci_lower", "hr_ci_upper", "log_hr", "se_log_hr", "o_minus_e", "variance",
        "common_or", "common_or_ci_lower", "common_or_ci_upper", "person_time", "rate_events",
        "correlation", "correlation_n", "effect_estimate", "effect_se", "effect_ci_lower",
        "effect_ci_upper", "performance_estimate", "performance_se", "performance_ci_lower",
        "performance_ci_upper",
    ]:
        data[key] = blank()
    data["effect_measure"] = {"value": "", "evidence": "", "confidence": 0.0}
    data["performance_metric"] = {"value": "", "evidence": "", "confidence": 0.0}

    return json.dumps({
        "outcomes": [{
            "outcome_name": "Sensitivity and specificity",
            "outcome_type": "DIAGNOSTIC_ACCURACY",
            "follow_up": "",
            "overall_confidence": 0.96,
            "unresolved_fields": [],
            "data": data,
            "signals": {
                "graph_only": {"value": False, "evidence": ""},
                "kaplan_meier": {"value": False, "evidence": ""},
                "median_iqr_only": {"value": False, "evidence": ""},
                "qualitative_findings_present": {"value": False, "evidence": ""},
            },
        }],
        "no_data_reason": "",
    })


def seed_verified_families(ledger, n=4, possible_link=False):
    ledger.upsert_project(ProjectRecord("P1", "Radiology", question_type="DIAGNOSTIC_ACCURACY"))
    c = candidate()
    c.metadata["study_audit_complete"] = True
    ledger.upsert_candidate(c)
    sentence = "Test A versus Histopathology yielded TP 40, FN 10, FP 5, and TN 45."

    for i in range(1, n + 1):
        sid = f"S{i}"
        fid = f"F{i}"
        ledger.upsert_payload(
            "studies",
            "C1",
            sid,
            {
                "study_id": sid,
                "title": f"Study {i}",
                "family_id": fid,
                "promotion_status": "VERIFIED_ELIGIBLE",
                "eligibility_verified": True,
                "design_verified": True,
                "independence_verified": True,
            },
            family_id=fid,
        )
        ledger.upsert_payload(
            "study_families",
            "C1",
            fid,
            {
                "family_id": fid,
                "study_ids": [sid],
                "independence_verified": True,
                "eligibility_verified": True,
                "design_verified": True,
            },
        )
        ledger.upsert_external_evidence(
            "C1",
            "PRIMARY_STUDY",
            sid,
            source="Europe PMC",
            title=f"Study {i}",
            payload={"metadata": {"abstract": sentence}},
        )

    if possible_link:
        c = ledger.get_candidate("C1")
        c.metadata["family_possible_links_detail"] = [{
            "study_a": "S1",
            "study_b": "S2",
            "status": "POSSIBLE_SAME_FAMILY",
            "reasons": ["same cohort indicators"],
        }]
        ledger.upsert_candidate(c)

    return sentence


def test_four_verified_usable_families_close_synthesis_threshold(tmp_path):
    with SQLiteLedger(tmp_path / "synth.sqlite3") as ledger:
        sentence = seed_verified_families(ledger, 4)
        bridge = SynthesisVerificationBridge(
            ledger,
            SynthesisDataExtractor(StaticAIProvider(dta_response(sentence))),
        )
        summary = bridge.run("C1")

        assert summary.verified_usable_families == 4
        assert summary.conservative_verified_usable_families == 4
        assert summary.threshold_met
        assert summary.synthesis_audit_complete
        assert len(ledger.list_payloads("outcomes", "C1")) == 4

        snap = snapshot_from_ledger(ledger, "C1")
        assert snap.verified_independent_studies == 4
        assert snap.verified_usable_studies == 4
        assert snap.minimum_passes


def test_possible_family_overlap_reduces_usable_count_conservatively(tmp_path):
    with SQLiteLedger(tmp_path / "synth.sqlite3") as ledger:
        sentence = seed_verified_families(ledger, 4, possible_link=True)
        bridge = SynthesisVerificationBridge(
            ledger,
            SynthesisDataExtractor(StaticAIProvider(dta_response(sentence))),
        )
        summary = bridge.run("C1")

        assert summary.verified_usable_families == 4
        assert summary.conservative_verified_usable_families == 3
        assert not summary.threshold_met
        assert not summary.synthesis_audit_complete

        snap = snapshot_from_ledger(ledger, "C1")
        assert snap.verified_usable_studies == 3


def test_abstract_without_quantitative_data_needs_full_text_not_not_usable(tmp_path):
    with SQLiteLedger(tmp_path / "synth.sqlite3") as ledger:
        seed_verified_families(ledger, 4)
        empty_response = json.dumps({
            "outcomes": [],
            "no_data_reason": "The abstract reports diagnostic performance without numerical data.",
        })
        bridge = SynthesisVerificationBridge(
            ledger,
            SynthesisDataExtractor(StaticAIProvider(empty_response)),
        )
        summary = bridge.run("C1")

        assert summary.verified_usable_families == 0
        assert summary.conservative_verified_usable_families == 0
        assert summary.families_needing_full_text == 4
        assert not summary.synthesis_audit_complete
        assert ledger.list_payloads("outcomes", "C1") == []


def test_same_family_multiple_publications_counts_once(tmp_path):
    with SQLiteLedger(tmp_path / "synth.sqlite3") as ledger:
        ledger.upsert_project(ProjectRecord("P1", "Radiology", question_type="DIAGNOSTIC_ACCURACY"))
        ledger.upsert_candidate(candidate())
        sentence = "Test A versus Histopathology yielded TP 40, FN 10, FP 5, and TN 45."
        ledger.upsert_payload(
            "study_families",
            "C1",
            "F1",
            {
                "family_id": "F1",
                "study_ids": ["S1", "S2"],
                "independence_verified": True,
                "eligibility_verified": True,
                "design_verified": True,
            },
        )
        for sid in ["S1", "S2"]:
            ledger.upsert_payload(
                "studies",
                "C1",
                sid,
                {
                    "study_id": sid,
                    "title": sid,
                    "family_id": "F1",
                    "promotion_status": "VERIFIED_ELIGIBLE",
                },
                family_id="F1",
            )
            ledger.upsert_external_evidence(
                "C1",
                "PRIMARY_STUDY",
                sid,
                source="Europe PMC",
                title=sid,
                payload={"metadata": {"abstract": sentence}},
            )

        bridge = SynthesisVerificationBridge(
            ledger,
            SynthesisDataExtractor(StaticAIProvider(dta_response(sentence))),
        )
        summary = bridge.run("C1")

        assert summary.outcomes_extracted == 2
        assert summary.verified_usable_families == 1
        assert summary.conservative_verified_usable_families == 1
