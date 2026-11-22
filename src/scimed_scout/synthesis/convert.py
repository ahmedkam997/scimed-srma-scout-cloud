from __future__ import annotations

from typing import Any

from scimed_scout.storage import CandidateRecord
from scimed_scout.usability import (
    ArmBinary,
    ArmContinuous,
    DiagnosticAccuracyData,
    OutcomeDatum,
    OutcomeType,
)

from .models import ExtractedOutcome


def to_outcome_datum(
    candidate: CandidateRecord,
    outcome_id: str,
    extraction: ExtractedOutcome,
) -> OutcomeDatum:
    data = extraction.data
    outcome_type = _outcome_type(extraction.outcome_type)
    principal = _is_principal(candidate, extraction.outcome_name)

    t_binary = _binary(_sub(data, "treatment_binary"))
    c_binary = _binary(_sub(data, "control_binary"))
    single_binary = _binary(_sub(data, "single_binary"))
    t_cont = _continuous(_sub(data, "treatment_continuous"))
    c_cont = _continuous(_sub(data, "control_continuous"))
    diagnostic = _diagnostic(_sub(data, "diagnostic"))

    signals = extraction.signals or {}
    graph = _signal(signals, "graph_only")
    km = _signal(signals, "kaplan_meier")
    median_iqr = _signal(signals, "median_iqr_only")
    qualitative = _signal(signals, "qualitative_findings_present")

    notes: list[str] = []
    if graph:
        notes.append("graph-only data signaled in source")
    if km:
        notes.append("Kaplan-Meier curve signaled in source")
    if median_iqr:
        notes.append("median/IQR data signaled in source")

    return OutcomeDatum(
        outcome_id=outcome_id,
        outcome_name=extraction.outcome_name or "Unnamed outcome",
        outcome_type=outcome_type,
        principal=principal,
        follow_up=extraction.follow_up,
        treatment_binary=t_binary,
        control_binary=c_binary,
        single_binary=single_binary,
        treatment_continuous=t_cont,
        control_continuous=c_cont,
        diagnostic=diagnostic,
        hr=_num(data, "hr"),
        hr_ci_lower=_num(data, "hr_ci_lower"),
        hr_ci_upper=_num(data, "hr_ci_upper"),
        log_hr=_num(data, "log_hr"),
        se_log_hr=_num(data, "se_log_hr"),
        o_minus_e=_num(data, "o_minus_e"),
        variance=_num(data, "variance"),
        common_or=_num(data, "common_or"),
        common_or_ci_lower=_num(data, "common_or_ci_lower"),
        common_or_ci_upper=_num(data, "common_or_ci_upper"),
        person_time=_num(data, "person_time"),
        rate_events=_int(data, "rate_events"),
        correlation=_num(data, "correlation"),
        correlation_n=_int(data, "correlation_n"),
        effect_estimate=_num(data, "effect_estimate"),
        effect_se=_num(data, "effect_se"),
        effect_ci_lower=_num(data, "effect_ci_lower"),
        effect_ci_upper=_num(data, "effect_ci_upper"),
        effect_measure=_text(data, "effect_measure"),
        performance_estimate=_num(data, "performance_estimate"),
        performance_se=_num(data, "performance_se"),
        performance_ci_lower=_num(data, "performance_ci_lower"),
        performance_ci_upper=_num(data, "performance_ci_upper"),
        performance_metric=_text(data, "performance_metric"),
        extractable_findings_present=qualitative,
        synthesis_method_defined=bool((candidate.metadata or {}).get("qualitative_synthesis_method")),
        graph_extraction_completed=False,
        graph_extracted_values_present=False,
        median_iqr_conversion_completed=False,
        median_iqr_conversion_justified=False,
        reconstructed_variance_completed=False,
        reconstructed_effect_completed=False,
        notes="; ".join(notes),
    )


def _outcome_type(value: str) -> OutcomeType:
    try:
        return OutcomeType(str(value or "").upper())
    except ValueError:
        return OutcomeType.OTHER


def _binary(raw: dict[str, Any]) -> ArmBinary | None:
    if not raw:
        return None
    values = {
        "n": _int(raw, "n"),
        "events": _int(raw, "events"),
        "proportion": _num(raw, "proportion"),
    }
    return ArmBinary(**values) if any(v is not None for v in values.values()) else None


def _continuous(raw: dict[str, Any]) -> ArmContinuous | None:
    if not raw:
        return None
    keys = ["n", "mean", "sd", "change_mean", "change_sd", "median", "q1", "q3"]
    values = {key: (_int(raw, key) if key == "n" else _num(raw, key)) for key in keys}
    return ArmContinuous(**values) if any(v is not None for v in values.values()) else None


def _diagnostic(raw: dict[str, Any]) -> DiagnosticAccuracyData | None:
    if not raw:
        return None
    values = {
        "index_test": _text(raw, "index_test"),
        "reference_standard": _text(raw, "reference_standard"),
        "threshold": _text(raw, "threshold"),
        "tp": _int(raw, "tp"),
        "fp": _int(raw, "fp"),
        "fn": _int(raw, "fn"),
        "tn": _int(raw, "tn"),
        "sensitivity": _num(raw, "sensitivity"),
        "specificity": _num(raw, "specificity"),
        "diseased_n": _int(raw, "diseased_n"),
        "non_diseased_n": _int(raw, "non_diseased_n"),
    }
    if not any(v not in (None, "") for v in values.values()):
        return None

    reconstruction_completed = False
    if all(values[k] is not None for k in ("sensitivity", "specificity", "diseased_n", "non_diseased_n")):
        reconstructed = _reconstruct_2x2(
            values["sensitivity"],
            values["specificity"],
            values["diseased_n"],
            values["non_diseased_n"],
        )
        if reconstructed is not None:
            for key, value in reconstructed.items():
                if values[key] is None:
                    values[key] = value
            reconstruction_completed = all(values[k] is not None for k in ("tp", "fp", "fn", "tn"))

    return DiagnosticAccuracyData(
        **values,
        reconstruction_completed=reconstruction_completed,
    )


def _reconstruct_2x2(sensitivity, specificity, diseased_n, non_diseased_n):
    if not (0 <= sensitivity <= 1 and 0 <= specificity <= 1):
        return None
    tp_float = sensitivity * diseased_n
    tn_float = specificity * non_diseased_n
    tp = round(tp_float)
    tn = round(tn_float)
    if abs(tp - tp_float) > 0.02 or abs(tn - tn_float) > 0.02:
        return None
    return {
        "tp": int(tp),
        "fn": int(diseased_n - tp),
        "tn": int(tn),
        "fp": int(non_diseased_n - tn),
    }


def _is_principal(candidate: CandidateRecord, name: str) -> bool:
    target = str((candidate.metadata or {}).get("principal_outcome") or "").strip()
    return bool(target) and _norm(target) == _norm(name)


def _sub(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key)
    return value if isinstance(value, dict) else {}


def _field(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key)
    return value if isinstance(value, dict) else {}


def _num(data: dict[str, Any], key: str):
    value = _field(data, key).get("value")
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(data: dict[str, Any], key: str):
    value = _field(data, key).get("value")
    if isinstance(value, bool) or value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return int(parsed) if parsed.is_integer() else None


def _text(data: dict[str, Any], key: str) -> str:
    value = _field(data, key).get("value")
    return str(value).strip() if value not in (None, "") else ""


def _signal(signals: dict[str, Any], key: str) -> bool:
    raw = signals.get(key)
    return bool(raw.get("value")) if isinstance(raw, dict) else False


def _norm(text: str) -> str:
    return " ".join(str(text or "").casefold().split())
