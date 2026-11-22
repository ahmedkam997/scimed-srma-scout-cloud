from scimed_scout.evidence import derive_evidence_counts
from scimed_scout.trials import TrialFamilyResolver, TrialPublication
from scimed_scout.usability import ArmBinary, OutcomeDatum, OutcomeType, TrialOutcomeLedger


def publication(i):
    return TrialPublication(
        publication_id=f"P{i}",
        title=f"Trial {i}",
        manually_verified_family_id=f"F{i}",
        independence_verified=True,
        randomization_verified=True,
        eligibility_verified=True,
    )


def usable_ledger(i, principal=False):
    return TrialOutcomeLedger(
        f"F{i}",
        [
            OutcomeDatum(
                f"O{i}",
                "Outcome",
                OutcomeType.BINARY,
                principal=principal,
                treatment_binary=ArmBinary(n=50, events=5),
                control_binary=ArmBinary(n=50, events=8),
            )
        ],
    )


def test_deterministic_counts_reach_four_study_threshold_from_ledgers():
    audit = TrialFamilyResolver().audit([publication(i) for i in range(1, 5)])
    ledgers = [usable_ledger(i, principal=i <= 2) for i in range(1, 5)]
    counts = derive_evidence_counts(audit, ledgers)
    assert counts.verified_independent_studies == 4
    assert counts.verified_usable_studies == 4
    assert counts.principal_outcome_studies == 2
    assert counts.unresolved_type_a == []


def test_usable_ledger_for_unverified_family_does_not_count():
    pubs = [publication(i) for i in range(1, 4)]
    unverified = TrialPublication(
        publication_id="P4",
        title="Trial 4",
        manually_verified_family_id="F4",
        independence_verified=False,
        randomization_verified=True,
        eligibility_verified=True,
    )
    audit = TrialFamilyResolver().audit(pubs + [unverified])
    ledgers = [usable_ledger(i) for i in range(1, 5)]
    counts = derive_evidence_counts(audit, ledgers)
    assert counts.verified_independent_studies == 3
    assert counts.verified_usable_studies == 3
    assert len(counts.unresolved_type_a) == 2


def test_possible_family_link_becomes_type_a_when_four_could_be_three():
    pubs = [publication(i) for i in range(1, 5)]
    pubs[0].acronym = pubs[1].acronym = "SAME"
    pubs[0].randomized_n = pubs[1].randomized_n = 100
    audit = TrialFamilyResolver().audit(pubs)
    counts = derive_evidence_counts(audit, [usable_ledger(i) for i in range(1, 5)])
    assert counts.verified_independent_studies == 4
    assert counts.minimum_possible_independent_studies == 3
    assert counts.family_uncertainty_decision_changing
    assert any("decision-changing" in issue for issue in counts.unresolved_type_a)
