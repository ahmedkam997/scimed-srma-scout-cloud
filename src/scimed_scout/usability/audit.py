from __future__ import annotations

import math

from .models import (
    ArmBinary,
    ArmContinuous,
    OutcomeDatum,
    OutcomeType,
    OutcomeUsability,
    UsabilityStatus,
)


def assess_outcome(datum: OutcomeDatum) -> OutcomeUsability:
    if datum.outcome_type == OutcomeType.BINARY:
        return _assess_binary(datum)
    if datum.outcome_type == OutcomeType.CONTINUOUS:
        return _assess_continuous(datum)
    if datum.outcome_type == OutcomeType.TIME_TO_EVENT:
        return _assess_time_to_event(datum)
    if datum.outcome_type == OutcomeType.ORDINAL:
        return _assess_ordinal(datum)
    return OutcomeUsability(datum.outcome_id, UsabilityStatus.UNRESOLVED, ("unsupported outcome type",))


def _assess_binary(datum: OutcomeDatum) -> OutcomeUsability:
    t, c = datum.treatment_binary, datum.control_binary
    if _binary_arm_complete(t) and _binary_arm_complete(c):
        return OutcomeUsability(
            datum.outcome_id,
            UsabilityStatus.VERIFIED_USABLE,
            ("events and denominators available for both randomized arms",),
        )
    if _binary_proportion_complete(t) and _binary_proportion_complete(c):
        return OutcomeUsability(
            datum.outcome_id,
            UsabilityStatus.VERIFIED_USABLE,
            ("proportions and denominators available for both randomized arms",),
        )
    if datum.graph_extraction_completed and datum.graph_extracted_values_present:
        return OutcomeUsability(
            datum.outcome_id,
            UsabilityStatus.VERIFIED_USABLE,
            ("graph extraction completed with usable arm-level values",),
        )
    if not datum.graph_extraction_completed and "graph" in datum.notes.lower():
        return OutcomeUsability(
            datum.outcome_id,
            UsabilityStatus.POTENTIALLY_USABLE,
            ("numeric values appear graph-only and extraction is not yet completed",),
        )
    return OutcomeUsability(
        datum.outcome_id,
        UsabilityStatus.NOT_USABLE,
        ("binary outcome lacks usable events/denominators or proportions/denominators for both arms",),
    )


def _assess_continuous(datum: OutcomeDatum) -> OutcomeUsability:
    t, c = datum.treatment_continuous, datum.control_continuous
    if _continuous_raw_complete(t) and _continuous_raw_complete(c):
        return OutcomeUsability(
            datum.outcome_id,
            UsabilityStatus.VERIFIED_USABLE,
            ("n, mean and SD available for both randomized arms",),
        )
    if _continuous_change_complete(t) and _continuous_change_complete(c):
        return OutcomeUsability(
            datum.outcome_id,
            UsabilityStatus.VERIFIED_USABLE,
            ("n, change mean and change SD available for both randomized arms",),
        )
    if datum.reconstructed_variance_completed and _continuous_mean_and_n(t) and _continuous_mean_and_n(c):
        return OutcomeUsability(
            datum.outcome_id,
            UsabilityStatus.VERIFIED_USABLE,
            ("variance reconstruction completed for otherwise complete arm-level means and sample sizes",),
        )
    if datum.median_iqr_conversion_completed and datum.median_iqr_conversion_justified and _median_iqr_complete(t) and _median_iqr_complete(c):
        return OutcomeUsability(
            datum.outcome_id,
            UsabilityStatus.VERIFIED_USABLE,
            ("justified median/IQR conversion completed for both arms",),
        )
    if _median_iqr_complete(t) and _median_iqr_complete(c):
        return OutcomeUsability(
            datum.outcome_id,
            UsabilityStatus.POTENTIALLY_USABLE,
            ("median/IQR data are present but justified conversion has not been completed",),
        )
    if datum.graph_extraction_completed and datum.graph_extracted_values_present:
        return OutcomeUsability(
            datum.outcome_id,
            UsabilityStatus.VERIFIED_USABLE,
            ("graph extraction completed with usable continuous arm-level values",),
        )
    if not datum.graph_extraction_completed and "graph" in datum.notes.lower():
        return OutcomeUsability(
            datum.outcome_id,
            UsabilityStatus.POTENTIALLY_USABLE,
            ("continuous data appear graph-only and extraction is not yet completed",),
        )
    return OutcomeUsability(
        datum.outcome_id,
        UsabilityStatus.NOT_USABLE,
        ("continuous outcome lacks a verified arm-level or reconstructed quantitative pathway",),
    )


def _assess_time_to_event(datum: OutcomeDatum) -> OutcomeUsability:
    if _positive(datum.hr) and _positive(datum.hr_ci_lower) and _positive(datum.hr_ci_upper):
        return OutcomeUsability(
            datum.outcome_id,
            UsabilityStatus.VERIFIED_USABLE,
            ("hazard ratio and confidence interval available",),
        )
    if _finite(datum.log_hr) and _positive(datum.se_log_hr):
        return OutcomeUsability(
            datum.outcome_id,
            UsabilityStatus.VERIFIED_USABLE,
            ("log hazard ratio and standard error available",),
        )
    if _finite(datum.o_minus_e) and _positive(datum.variance):
        return OutcomeUsability(
            datum.outcome_id,
            UsabilityStatus.VERIFIED_USABLE,
            ("log-rank O-E and variance available",),
        )
    if datum.reconstructed_effect_completed:
        return OutcomeUsability(
            datum.outcome_id,
            UsabilityStatus.VERIFIED_USABLE,
            ("time-to-event effect reconstruction completed",),
        )
    if "kaplan" in datum.notes.lower() or "km curve" in datum.notes.lower():
        return OutcomeUsability(
            datum.outcome_id,
            UsabilityStatus.POTENTIALLY_USABLE,
            ("Kaplan-Meier information may permit reconstruction but reconstruction is not completed",),
        )
    return OutcomeUsability(
        datum.outcome_id,
        UsabilityStatus.NOT_USABLE,
        ("time-to-event outcome lacks HR/CI, logHR/SE, O-E/variance or completed reconstruction",),
    )


def _assess_ordinal(datum: OutcomeDatum) -> OutcomeUsability:
    if _positive(datum.common_or) and _positive(datum.common_or_ci_lower) and _positive(datum.common_or_ci_upper):
        return OutcomeUsability(
            datum.outcome_id,
            UsabilityStatus.VERIFIED_USABLE,
            ("common odds ratio and confidence interval available",),
        )
    if _binary_arm_complete(datum.treatment_binary) and _binary_arm_complete(datum.control_binary):
        return OutcomeUsability(
            datum.outcome_id,
            UsabilityStatus.VERIFIED_USABLE,
            ("prespecified ordinal threshold is represented by usable binary arm data",),
        )
    return OutcomeUsability(
        datum.outcome_id,
        UsabilityStatus.NOT_USABLE,
        ("ordinal outcome lacks a usable common-OR/CI or prespecified threshold dataset",),
    )


def _binary_arm_complete(arm: ArmBinary | None) -> bool:
    return (
        arm is not None
        and isinstance(arm.n, int)
        and arm.n > 0
        and isinstance(arm.events, int)
        and 0 <= arm.events <= arm.n
    )


def _binary_proportion_complete(arm: ArmBinary | None) -> bool:
    return (
        arm is not None
        and isinstance(arm.n, int)
        and arm.n > 0
        and arm.proportion is not None
        and 0 <= arm.proportion <= 1
    )


def _continuous_raw_complete(arm: ArmContinuous | None) -> bool:
    return (
        arm is not None
        and isinstance(arm.n, int)
        and arm.n > 1
        and _finite(arm.mean)
        and _positive(arm.sd)
    )


def _continuous_change_complete(arm: ArmContinuous | None) -> bool:
    return (
        arm is not None
        and isinstance(arm.n, int)
        and arm.n > 1
        and _finite(arm.change_mean)
        and _positive(arm.change_sd)
    )


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
