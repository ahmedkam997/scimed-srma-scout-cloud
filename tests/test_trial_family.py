from scimed_scout.discovery.trial_family import audit_trial_families, registration_signals


def record(id, **metadata):
    return {"source_record_id": id, "source": "PubMed", "title": id,
            "payload": {"metadata": metadata}}


def test_companion_reports_group_but_never_confirm_eligibility():
    result = audit_trial_families([record("A", trial_registration_id="NCT01850082"),
                                  record("B", trial_registration_id="nct01850082"),
                                  record("C")])
    assert result["distinct_report_leads"] == 3
    assert result["registry_linked_families"] == 1
    assert result["conservative_family_lead_count"] == 2
    assert result["confirmed_independent_eligible_studies"] is None
    assert len(result["unlinked_reports"]) == 1


def test_platform_comparisons_preserved():
    result = audit_trial_families([record("A", nct_id="NCT04381936", comparison="6 mg vs control"),
                                  record("B", nct_id="NCT04381936", comparison="20 mg vs 6 mg")])
    family = result["families"][0]
    assert len(family["explicit_comparisons"]) == 2
    assert family["comparison_resolution"] == "MULTIPLE_REPORTED_COMPARISONS_MANUAL_CHECK"
    assert not family["population_independence_confirmed"]


def test_multi_id_citation_does_not_bridge_unrelated_trials():
    result = audit_trial_families([record("A", nct_id="NCT00000001"),
        record("B", nct_id="NCT00000002"),
        record("C", trial_registration_ids=["NCT00000001", "NCT00000002"])])
    assert result["registry_linked_families"] == 2
    assert len(result["ambiguous_reports"]) == 1


def test_background_citation_is_not_own_registration():
    assert registration_signals(record("A", abstractText="Previous trials included NCT00000001.")) == {}
    assert "NCT00000002" in registration_signals(record("B", abstractText="Trial registration: NCT00000002."))


def test_cross_registry_unknown_alias_is_not_auto_merged():
    result = audit_trial_families([record("A", nct_id="NCT00000001"),
        record("B", trial_registration_id="ISRCTN12345678")])
    assert result["registry_linked_families"] == 2
    assert result["confirmed_independent_eligible_studies"] is None
