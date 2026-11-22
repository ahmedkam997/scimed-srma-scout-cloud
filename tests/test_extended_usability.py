from scimed_scout.usability import (
    ArmBinary,
    DiagnosticAccuracyData,
    OutcomeDatum,
    OutcomeType,
    UsabilityStatus,
    assess_outcome,
)


def test_dta_complete_2x2_is_verified_usable():
    datum = OutcomeDatum(
        "dta1",
        "Index test accuracy",
        OutcomeType.DIAGNOSTIC_ACCURACY,
        diagnostic=DiagnosticAccuracyData(
            index_test="Test A",
            reference_standard="Reference",
            tp=80,
            fp=10,
            fn=20,
            tn=90,
        ),
    )
    result = assess_outcome(datum)
    assert result.status == UsabilityStatus.VERIFIED_USABLE


def test_dta_reported_sensitivity_specificity_is_potential_until_reconstructed():
    d = DiagnosticAccuracyData(
        sensitivity=0.80,
        specificity=0.90,
        diseased_n=100,
        non_diseased_n=100,
    )
    datum = OutcomeDatum("dta2", "Accuracy", OutcomeType.DIAGNOSTIC_ACCURACY, diagnostic=d)
    assert assess_outcome(datum).status == UsabilityStatus.POTENTIALLY_USABLE
    d.reconstruction_completed = True
    assert assess_outcome(datum).status == UsabilityStatus.VERIFIED_USABLE


def test_prevalence_proportion_pathway():
    datum = OutcomeDatum(
        "prev",
        "Prevalence",
        OutcomeType.PROPORTION,
        single_binary=ArmBinary(n=1000, events=120),
    )
    assert assess_outcome(datum).status == UsabilityStatus.VERIFIED_USABLE


def test_rate_pathway():
    datum = OutcomeDatum("rate", "Incidence rate", OutcomeType.RATE, rate_events=25, person_time=800.0)
    assert assess_outcome(datum).status == UsabilityStatus.VERIFIED_USABLE


def test_correlation_pathway():
    datum = OutcomeDatum("corr", "Correlation", OutcomeType.CORRELATION, correlation=0.42, correlation_n=85)
    assert assess_outcome(datum).status == UsabilityStatus.VERIFIED_USABLE


def test_generic_adjusted_effect_pathway_supports_observational_estimates():
    datum = OutcomeDatum(
        "assoc",
        "Adjusted association",
        OutcomeType.GENERIC_EFFECT,
        effect_estimate=1.42,
        effect_ci_lower=1.10,
        effect_ci_upper=1.84,
        effect_measure="adjusted odds ratio",
    )
    assert assess_outcome(datum).status == UsabilityStatus.VERIFIED_USABLE


def test_prediction_model_performance_pathway():
    datum = OutcomeDatum(
        "auc",
        "Discrimination",
        OutcomeType.PREDICTION_MODEL_PERFORMANCE,
        performance_estimate=0.81,
        performance_ci_lower=0.76,
        performance_ci_upper=0.86,
        performance_metric="AUC",
    )
    assert assess_outcome(datum).status == UsabilityStatus.VERIFIED_USABLE


def test_qualitative_finding_pathway():
    datum = OutcomeDatum(
        "qual",
        "Patient experiences",
        OutcomeType.QUALITATIVE_FINDING,
        extractable_findings_present=True,
        synthesis_method_defined=True,
    )
    assert assess_outcome(datum).status == UsabilityStatus.VERIFIED_USABLE
