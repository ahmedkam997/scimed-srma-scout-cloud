from __future__ import annotations

import math

from .models import (
    ArmBinary,
    ArmContinuous,
    DiagnosticAccuracyData,
    OutcomeDatum,
    OutcomeType,
    OutcomeUsability,
    UsabilityStatus,
)


def assess_outcome(datum: OutcomeDatum) -> OutcomeUsability:
    routes = {
        OutcomeType.BINARY: _assess_binary,
        OutcomeType.CONTINUOUS: _assess_continuous,
        OutcomeType.TIME_TO_EVENT: _assess_time_to_event,
        OutcomeType.ORDINAL: _assess_ordinal,
        OutcomeType.DIAGNOSTIC_ACCURACY: _assess_dta,
        OutcomeType.PROPORTION: _assess_proportion,
        OutcomeType.RATE: _assess_rate,
        OutcomeType.CORRELATION: _assess_correlation,
        OutcomeType.GENERIC_EFFECT: _assess_generic_effect,
        OutcomeType.PREDICTION_MODEL_PERFORMANCE: _assess_prediction,
        OutcomeType.QUALITATIVE_FINDING: _assess_qualitative,
    }
    assessor = routes.get(datum.outcome_type)
    if assessor is None:
        return OutcomeUsability(datum.outcome_id, UsabilityStatus.UNRESOLVED, ("no verified synthesis pathway configured for this outcome type",))
    return assessor(datum)


def _assess_binary(datum: OutcomeDatum) -> OutcomeUsability:
    t, c = datum.treatment_binary, datum.control_binary
    if _binary_arm_complete(t) and _binary_arm_complete(c):
        return _usable(datum, "events and denominators available for both comparison groups")
    if _binary_proportion_complete(t) and _binary_proportion_complete(c):
        return _usable(datum, "proportions and denominators available for both comparison groups")
    if datum.graph_extraction_completed and datum.graph_extracted_values_present:
        return _usable(datum, "graph extraction completed with usable group-level binary values")
    if not datum.graph_extraction_completed and "graph" in datum.notes.lower():
        return _potential(datum, "binary values appear graph-only and extraction is not completed")
    return _not_usable(datum, "binary outcome lacks usable group-level events/denominators or proportions/denominators")


def _assess_continuous(datum: OutcomeDatum) -> OutcomeUsability:
    t, c = datum.treatment_continuous, datum.control_continuous
    if _continuous_raw_complete(t) and _continuous_raw_complete(c):
        return _usable(datum, "n, mean and SD available for both comparison groups")
    if _continuous_change_complete(t) and _continuous_change_complete(c):
        return _usable(datum, "n, change mean and change SD available for both comparison groups")
    if datum.reconstructed_variance_completed and _continuous_mean_and_n(t) and _continuous_mean_and_n(c):
        return _usable(datum, "variance reconstruction completed for group-level means and sample sizes")
    if datum.median_iqr_conversion_completed and datum.median_iqr_conversion_justified and _median_iqr_complete(t) and _median_iqr_complete(c):
        return _usable(datum, "justified median/IQR conversion completed for both groups")
    if _median_iqr_complete(t) and _median_iqr_complete(c):
        return _potential(datum, "median/IQR data are present but justified conversion is not completed")
    if datum.graph_extraction_completed and datum.graph_extracted_values_present:
        return _usable(datum, "graph extraction completed with usable continuous values")
    if not datum.graph_extraction_completed and "graph" in datum.notes.lower():
        return _potential(datum, "continuous data appear graph-only and extraction is not completed")
    return _not_usable(datum, "continuous outcome lacks a verified group-level or reconstructed quantitative pathway")


def _assess_time_to_event(datum: OutcomeDatum) -> OutcomeUsability:
    if _positive(datum.hr) and _valid_ci(datum.hr_ci_lower, datum.hr_ci_upper):
        return _usable(datum, "hazard ratio and confidence interval available")
    if _finite(datum.log_hr) and _positive(datum.se_log_hr):
        return _usable(datum, "log hazard ratio and standard error available")
    if _finite(datum.o_minus_e) and _positive(datum.variance):
        return _usable(datum, "log-rank O-E and variance available")
    if datum.reconstructed_effect_completed:
        return _usable(datum, "time-to-event effect reconstruction completed")
    if "kaplan" in datum.notes.lower() or "km curve" in datum.notes.lower():
        return _potential(datum, "Kaplan-Meier information may permit reconstruction but reconstruction is not completed")
    return _not_usable(datum, "time-to-event outcome lacks HR/CI, logHR/SE, O-E/variance or completed reconstruction")


def _assess_ordinal(datum: OutcomeDatum) -> OutcomeUsability:
    if _positive(datum.common_or) and _valid_ci(datum.common_or_ci_lower, datum.common_or_ci_upper):
        return _usable(datum, "common odds ratio and confidence interval available")
    if _binary_arm_complete(datum.treatment_binary) and _binary_arm_complete(datum.control_binary):
        return _usable(datum, "prespecified ordinal threshold represented by usable binary group data")
    return _not_usable(datum, "ordinal outcome lacks common-OR/CI or a usable prespecified threshold dataset")


def _assess_dta(datum: OutcomeDatum) -> OutcomeUsability:
    d = datum.diagnostic
    if d is None:
        return _not_usable(datum, "diagnostic accuracy outcome lacks diagnostic data")
    if _complete_2x2(d):
        reason = "complete TP/FP/FN/TN 2x2 data available"
        if d.paired_comparative and not d.comparative_dependence_data_present:
            reason += "; sufficient for per-test accuracy synthesis, paired comparative dependence data remain unavailable"
        return _usable(datum, reason)
    if _reported_se_sp_with_denominators(d):
        if d.reconstruction_completed:
            return _usable(datum, "sensitivity/specificity and diseased/non-diseased denominators were successfully reconstructed to usable accuracy data")
        return _potential(datum, "sensitivity/specificity and denominators are present but 2x2 reconstruction is not completed")
    return _not_usable(datum, "DTA outcome lacks complete 2x2 data or a verified reconstruction pathway")


def _assess_proportion(datum: OutcomeDatum) -> OutcomeUsability:
    if _binary_arm_complete(datum.single_binary):
        return _usable(datum, "events and denominator available for single-group proportion/prevalence synthesis")
    if _binary_proportion_complete(datum.single_binary):
        return _usable(datum, "proportion and denominator available for single-group synthesis")
    return _not_usable(datum, "proportion/prevalence outcome lacks events/denominator or proportion/denominator")


def _assess_rate(datum: OutcomeDatum) -> OutcomeUsability:
    if isinstance(datum.rate_events, int) and datum.rate_events >= 0 and _positive(datum.person_time):
        return _usable(datum, "event count and person-time available for rate synthesis")
    return _not_usable(datum, "rate outcome lacks non-negative event count and positive person-time")


def _assess_correlation(datum: OutcomeDatum) -> OutcomeUsability:
    if (
        _finite(datum.correlation)
        and -1 < float(datum.correlation) < 1
        and isinstance(datum.correlation_n, int)
        and datum.correlation_n > 3
    ):
        return _usable(datum, "correlation coefficient and sample size available for transformation/synthesis")
    return _not_usable(datum, "correlation outcome lacks valid r and sample size")


def _assess_generic_effect(datum: OutcomeDatum) -> OutcomeUsability:
    if _finite(datum.effect_estimate) and _positive(datum.effect_se):
        return _usable(datum, f"{datum.effect_measure or 'effect estimate'} and standard error available")
    if _finite(datum.effect_estimate) and _valid_ci(datum.effect_ci_lower, datum.effect_ci_upper):
        return _usable(datum, f"{datum.effect_measure or 'effect estimate'} and confidence interval available")
    if datum.reconstructed_effect_completed:
        return _usable(datum, "generic effect estimate reconstruction completed")
    return _not_usable(datum, "generic effect lacks SE/CI or completed reconstruction")


def _assess_prediction(datum: OutcomeDatum) -> OutcomeUsability:
    if _finite(datum.performance_estimate) and _positive(datum.performance_se):
        return _usable(datum, f"{datum.performance_metric or 'prediction performance'} estimate and standard error available")
    if _finite(datum.performance_estimate) and _valid_ci(datum.performance_ci_lower, datum.performance_ci_upper):
        return _usable(datum, f"{datum.performance_metric or 'prediction performance'} estimate and confidence interval available")
    return _not_usable(datum, "prediction-model performance lacks an estimate with uncertainty")


def _assess_qualitative(datum: OutcomeDatum) -> OutcomeUsability:
    if datum.extractable_findings_present and datum.synthesis_method_defined:
        return _usable(datum, "extractable qualitative findings are present and a synthesis method is defined")
    if datum.extractable_findings_present:
        return _potential(datum, "extractable qualitative findings are present but the synthesis method is not yet defined")
    return _not_usable(datum, "qualitative study lacks extractable findings for synthesis")


def _complete_2x2(d: DiagnosticAccuracyData) -> bool:
    values = (d.tp, d.fp, d.fn, d.tn)
    return all(isinstance(x, int) and x >= 0 for x in values) and (d.tp + d.fn > 0) and (d.tn + d.fp > 0)


def _reported_se_sp_with_denominators(d: DiagnosticAccuracyData) -> bool:
    return (
        d.sensitivity is not None
        and 0 <= d.sensitivity <= 1
        and d.specificity is not None
        and 0 <= d.specificity <= 1
        and isinstance(d.diseased_n, int)
        and d.diseased_n > 0
        and isinstance(d.non_diseased_n, int)
        and d.non_diseased_n > 0
    )


def _binary_arm_complete(arm: ArmBinary | None) -> bool:
    return arm is not None and isinstance(arm.n, int) and arm.n > 0 and isinstance(arm.events, int) and 0 <= arm.events <= arm.n


def _binary_proportion_complete(arm: ArmBinary | None) -> bool:
    return arm is not None and isinstance(arm.n, int) and arm.n > 0 and arm.proportion is not None and 0 <= arm.proportion <= 1


def _continuous_raw_complete(arm: ArmContinuous | None) -> bool:
    return arm is not None and isinstance(arm.n, int) and arm.n > 1 and _finite(arm.mean) and _positive(arm.sd)


def _continuous_change_complete(arm: ArmContinuous | None) -> bool:
    return arm is not None and isinstance(arm.n, int) and arm.n > 1 and _finite(arm.change_mean) and _positive(arm.change_sd)


def _continuous_mean_and_n(arm: ArmContinuous | None) -> bool:
    return arm is not None and isinstance(arm.n, int) and arm.n > 1 and _finite(arm.mean)


def _median_iqr_complete(arm: ArmContinuous | None) -> bool:
    return (
        arm is not None
        and isinstance(arm.n, int)
        and arm.n > 1
        and _finite(arm.median)
        and _finite(arm.q1)
        and _finite(arm.q3)
        and float(arm.q1) <= float(arm.median) <= float(arm.q3)
    )


def _finite(value: float | int | None) -> bool:
    return value is not None and math.isfinite(float(value))


def _positive(value: float | int | None) -> bool:
    return _finite(value) and float(value) > 0


def _valid_ci(lower: float | int | None, upper: float | int | None) -> bool:
    return _finite(lower) and _finite(upper) and float(lower) < float(upper)


def _usable(datum: OutcomeDatum, reason: str) -> OutcomeUsability:
    return OutcomeUsability(datum.outcome_id, UsabilityStatus.VERIFIED_USABLE, (reason,))


def _potential(datum: OutcomeDatum, reason: str) -> OutcomeUsability:
    return OutcomeUsability(datum.outcome_id, UsabilityStatus.POTENTIALLY_USABLE, (reason,))


def _not_usable(datum: OutcomeDatum, reason: str) -> OutcomeUsability:
    return OutcomeUsability(datum.outcome_id, UsabilityStatus.NOT_USABLE, (reason,))
