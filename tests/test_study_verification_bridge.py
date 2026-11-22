from scimed_scout.storage import CandidateRecord, ProjectRecord, SQLiteLedger
from scimed_scout.verification import StudyVerificationBridge, snapshot_from_ledger


def candidate():
    return CandidateRecord(
        candidate_id="C1",
        project_id="P1",
        title="Test A accuracy",
        specialty="Radiology",
        question_type="DIAGNOSTIC_ACCURACY",
        review_question="What is the diagnostic accuracy of Test A?",
        population="Adults with suspected disease X",
        intervention_exposure_index_test="Test A",
        comparator_reference="Histopathology",
        outcomes=["sensitivity", "specificity"],
        eligible_designs=["diagnostic accuracy"],
    )


def field(value, evidence=None, confidence=0.95):
    return {
        "value": value,
        "evidence": evidence if evidence is not None else (str(value) if value not in (None, [], "") else ""),
        "source_section": "abstract",
        "confidence": confidence,
    }


def study_payload(
    study_id,
    *,
    title=None,
    doi="",
    sample_size=100,
    first_author="",
    confidence=0.95,
    design="prospective diagnostic accuracy study",
):
    fields = {
        "design_label": field(design, design),
        "population": field("Adults with suspected disease X", "Adults with suspected disease X"),
        "intervention_exposure_index_test": field("Test A", "Test A"),
        "comparator_reference": field("Histopathology", "Histopathology"),
        "outcomes": field(["sensitivity", "specificity"], "sensitivity and specificity"),
        "sample_size": field(sample_size, f"{sample_size} participants"),
        "registry_ids": field([], "", 0.0),
        "first_author": field(first_author, first_author, 0.95 if first_author else 0.0),
        "year": field(2026, "2026"),
    }
    return {
        "study_id": study_id,
        "title": title or f"Diagnostic study {study_id}",
        "doi": doi,
        "verification_status": "AUTO_EXTRACTED",
        "eligibility_status": "ELIGIBLE",
        "eligibility_verified": False,
        "design_verified": False,
        "independence_verified": False,
        "extraction": {
            "eligibility": "ELIGIBLE",
            "verification": "AUTO_EXTRACTED",
            "overall_confidence": confidence,
            "unresolved_fields": [],
            "exclusion_reason": "",
            "exclusion_evidence": "",
            "raw": {"fields": fields},
        },
    }


def seed(ledger, payloads):
    ledger.upsert_project(ProjectRecord("P1", "Radiology", question_type="DIAGNOSTIC_ACCURACY"))
    ledger.upsert_candidate(candidate())
    for payload in payloads:
        ledger.upsert_payload("studies", "C1", payload["study_id"], payload)


def test_four_supported_studies_become_four_verified_families(tmp_path):
    with SQLiteLedger(tmp_path / "bridge.sqlite3") as ledger:
        payloads = [
            study_payload(f"S{i}", sample_size=100 + i, title=f"Distinct diagnostic study {i}")
            for i in range(1, 5)
        ]
        seed(ledger, payloads)
        summary = StudyVerificationBridge(ledger).run("C1")

        assert summary.verified_eligible == 4
        assert summary.needs_review == 0
        assert summary.deterministic_families == 4
        assert summary.conservative_independent_count == 4
        assert summary.study_audit_complete

        snap = snapshot_from_ledger(ledger, "C1")
        assert snap.verified_independent_studies == 4
        assert not snap.synthesis_audit_complete


def test_duplicate_doi_publications_merge_into_one_family(tmp_path):
    with SQLiteLedger(tmp_path / "bridge.sqlite3") as ledger:
        payloads = [
            study_payload("S1", doi="10.1000/same", title="Primary report of Test A"),
            study_payload("S2", doi="10.1000/same", title="Secondary report of Test A"),
            study_payload("S3", doi="10.1000/3", title="Independent study three", sample_size=130),
            study_payload("S4", doi="10.1000/4", title="Independent study four", sample_size=140),
            study_payload("S5", doi="10.1000/5", title="Independent study five", sample_size=150),
        ]
        seed(ledger, payloads)
        summary = StudyVerificationBridge(ledger).run("C1")

        assert summary.verified_eligible == 5
        assert summary.deterministic_families == 4
        assert summary.conservative_independent_count == 4
        families = ledger.list_payloads("study_families", "C1")
        merged = [x for x in families if set(x["study_ids"]) == {"S1", "S2"}]
        assert len(merged) == 1


def test_possible_overlap_is_type_a_when_four_can_drop_to_three(tmp_path):
    with SQLiteLedger(tmp_path / "bridge.sqlite3") as ledger:
        payloads = [
            study_payload(
                "S1",
                title="Diagnostic accuracy of Test A in adults with disease X",
                sample_size=120,
            ),
            study_payload(
                "S2",
                title="Diagnostic accuracy of Test A among adults with disease X",
                sample_size=120,
            ),
            study_payload("S3", title="Independent imaging cohort alpha", sample_size=131),
            study_payload("S4", title="Independent imaging cohort beta", sample_size=142),
        ]
        seed(ledger, payloads)
        summary = StudyVerificationBridge(ledger).run("C1")

        assert summary.deterministic_families == 4
        assert summary.possible_family_links == 1
        assert summary.conservative_independent_count == 3
        assert summary.decision_changing_family_uncertainty
        assert not summary.study_audit_complete

        snap = snapshot_from_ledger(ledger, "C1")
        assert snap.verified_independent_studies == 3


def test_possible_overlap_with_five_families_keeps_conservative_four(tmp_path):
    with SQLiteLedger(tmp_path / "bridge.sqlite3") as ledger:
        payloads = [
            study_payload(
                "S1",
                title="Diagnostic accuracy of Test A in adults with disease X",
                sample_size=120,
            ),
            study_payload(
                "S2",
                title="Diagnostic accuracy of Test A among adults with disease X",
                sample_size=120,
            ),
            study_payload("S3", title="Independent imaging cohort alpha", sample_size=131),
            study_payload("S4", title="Independent imaging cohort beta", sample_size=142),
            study_payload("S5", title="Independent imaging cohort gamma", sample_size=153),
        ]
        seed(ledger, payloads)
        summary = StudyVerificationBridge(ledger).run("C1")

        assert summary.deterministic_families == 5
        assert summary.possible_family_links == 1
        assert summary.conservative_independent_count == 4
        assert not summary.decision_changing_family_uncertainty
        assert summary.study_audit_complete


def test_manual_distinct_override_resolves_decision_changing_possible_link(tmp_path):
    with SQLiteLedger(tmp_path / "bridge.sqlite3") as ledger:
        payloads = [
            study_payload(
                "S1",
                title="Diagnostic accuracy of Test A in adults with disease X",
                sample_size=120,
            ),
            study_payload(
                "S2",
                title="Diagnostic accuracy of Test A among adults with disease X",
                sample_size=120,
            ),
            study_payload("S3", title="Independent imaging cohort alpha", sample_size=131),
            study_payload("S4", title="Independent imaging cohort beta", sample_size=142),
        ]
        seed(ledger, payloads)
        bridge = StudyVerificationBridge(ledger)
        before = bridge.run("C1")
        assert before.conservative_independent_count == 3

        after = bridge.set_family_link_override(
            "C1",
            "S1",
            "S2",
            resolution="DISTINCT_FAMILIES",
            reason="full texts confirm different recruitment sites and periods",
        )
        assert after.possible_family_links == 0
        assert after.conservative_independent_count == 4
        assert after.study_audit_complete


def test_manual_same_family_override_merges_publications(tmp_path):
    with SQLiteLedger(tmp_path / "bridge.sqlite3") as ledger:
        payloads = [
            study_payload("S1", title="Publication one", sample_size=101),
            study_payload("S2", title="Publication two", sample_size=102),
            study_payload("S3", title="Independent three", sample_size=133),
            study_payload("S4", title="Independent four", sample_size=144),
        ]
        seed(ledger, payloads)
        bridge = StudyVerificationBridge(ledger)

        after = bridge.set_family_link_override(
            "C1",
            "S1",
            "S2",
            resolution="SAME_FAMILY",
            reason="same registry population confirmed from full text",
        )
        assert after.deterministic_families == 3
        assert after.conservative_independent_count == 3
        families = ledger.list_payloads("study_families", "C1")
        assert any(set(x["study_ids"]) == {"S1", "S2"} for x in families)


def test_low_confidence_study_needs_review_until_manual_verification(tmp_path):
    with SQLiteLedger(tmp_path / "bridge.sqlite3") as ledger:
        seed(ledger, [study_payload("S1", confidence=0.70)])
        bridge = StudyVerificationBridge(ledger)
        before = bridge.run("C1")
        assert before.needs_review == 1
        assert not before.study_audit_complete

        after = bridge.set_manual_study_verification(
            "C1",
            "S1",
            eligible=True,
            design_label="prospective diagnostic accuracy study",
            reason="verified against full text",
        )
        assert after.needs_review == 0
        assert after.verified_eligible == 1
        assert after.study_audit_complete


def test_family_id_is_stable_across_reruns(tmp_path):
    with SQLiteLedger(tmp_path / "bridge.sqlite3") as ledger:
        seed(ledger, [study_payload("S1", title="Stable family study")])
        bridge = StudyVerificationBridge(ledger)
        bridge.run("C1")
        first = ledger.list_payloads("study_families", "C1")[0]["family_id"]
        bridge.run("C1")
        second = ledger.list_payloads("study_families", "C1")[0]["family_id"]
        assert first == second
