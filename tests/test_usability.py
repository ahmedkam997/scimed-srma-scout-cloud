from scimed_scout.usability import (
    ArmBinary,
    ArmContinuous,
    OutcomeDatum,
    OutcomeType,
    TrialOutcomeLedger,
    UsabilityStatus,
    assess_outcome,
    summarize_ledgers,
)


def test_binary_events_and_denominators_are_verified_usable():
    outcome = OutcomeDatum(
        "death",
        "Mortality",
        OutcomeType.BINARY,
        treatment_binary=ArmBinary(n=100, events=5),
        control_binary=ArmBinary(n=100, events=9),
    )
    assert assess_outcome(outcome).status == UsabilityStatus.VERIFIED_USABLE


def test_invalid_binary_event_count_is_not_usable():
    outcome = OutcomeDatum(
        "event",
        "Event",
        OutcomeType.BINARY,
        treatment_binary=ArmBinary(n=10, events=11),
        control_binary=ArmBinary(n=10, events=2),
    )
    assert assess_outcome(outcome).status == UsabilityStatus.NOT_USABLE


def test_continuous_mean_sd_is_verified_usable():
    outcome = OutcomeDatum(
        "pain",
        "Pain score",
        OutcomeType.CONTINUOUS,
        treatment_continuous=ArmContinuous(n=40, mean=3.1, sd=1.2),
        control_continuous=ArmContinuous(n=42, mean=4.2, sd=1.4),
    )
    assert assess_outcome(outcome).status == UsabilityStatus.VERIFIED_USABLE


def test_median_iqr_is_only_potential_until_justified_conversion_completed():
    outcome = OutcomeDatum(
        "los",
        "Length of stay",
        OutcomeType.CONTINUOUS,
        treatment_continuous=ArmContinuous(n=50, median=4, q1=3, q3=6),
        control_continuous=ArmContinuous(n=50, median=5, q1=4, q3=7),
    )
    assert assess_outcome(outcome).status == UsabilityStatus.POTENTIALLY_USABLE

    outcome.median_iqr_conversion_completed = True
    outcome.median_iqr_conversion_justified = True
    assert assess_outcome(outcome).status == UsabilityStatus.VERIFIED_USABLE


def test_hr_ci_is_verified_and_km_only_is_potential():
    hr = OutcomeDatum(
        "survival",
        "Survival",
        OutcomeType.TIME_TO_EVENT,
        hr=0.78,
        hr_ci_lower=0.62,
        hr_ci_upper=0.98,
    )
    assert assess_outcome(hr).status == UsabilityStatus.VERIFIED_USABLE

    km = OutcomeDatum(
        "survival2",
        "Survival",
        OutcomeType.TIME_TO_EVENT,
        notes="Kaplan-Meier curve only",
    )
    assert assess_outcome(km).status == UsabilityStatus.POTENTIALLY_USABLE
    km.reconstructed_effect_completed = True
    assert assess_outcome(km).status == UsabilityStatus.VERIFIED_USABLE


def test_ordinal_common_or_is_verified_usable():
    outcome = OutcomeDatum(
        "shift",
        "Ordinal disability shift",
        OutcomeType.ORDINAL,
        common_or=1.25,
        common_or_ci_lower=1.02,
        common_or_ci_upper=1.53,
    )
    assert assess_outcome(outcome).status == UsabilityStatus.VERIFIED_USABLE


def test_trial_ledger_tracks_any_usable_and_principal_separately():
    ledger = TrialOutcomeLedger(
        "F1",
        [
            OutcomeDatum(
                "secondary",
                "Secondary",
                OutcomeType.BINARY,
                treatment_binary=ArmBinary(n=30, events=3),
                control_binary=ArmBinary(n=30, events=5),
            ),
            OutcomeDatum(
                "principal",
                "Principal",
                OutcomeType.BINARY,
                principal=True,
            ),
        ],
    )
    assert ledger.verified_usable
    assert not ledger.principal_verified_usable

    summary = summarize_ledgers([ledger])
    assert summary.verified_usable_families == 1
    assert summary.principal_outcome_verified_usable_families == 0
