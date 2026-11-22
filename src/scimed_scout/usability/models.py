from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class OutcomeType(StrEnum):
    BINARY = "BINARY"
    CONTINUOUS = "CONTINUOUS"
    TIME_TO_EVENT = "TIME_TO_EVENT"
    ORDINAL = "ORDINAL"
    DIAGNOSTIC_ACCURACY = "DIAGNOSTIC_ACCURACY"
    PROPORTION = "PROPORTION"
    RATE = "RATE"
    CORRELATION = "CORRELATION"
    GENERIC_EFFECT = "GENERIC_EFFECT"
    PREDICTION_MODEL_PERFORMANCE = "PREDICTION_MODEL_PERFORMANCE"
    QUALITATIVE_FINDING = "QUALITATIVE_FINDING"
    OTHER = "OTHER"


class UsabilityStatus(StrEnum):
    VERIFIED_USABLE = "VERIFIED_USABLE"
    POTENTIALLY_USABLE = "POTENTIALLY_USABLE"
    NOT_USABLE = "NOT_USABLE"
    UNRESOLVED = "UNRESOLVED"


@dataclass(slots=True)
class ArmContinuous:
    n: int | None = None
    mean: float | None = None
    sd: float | None = None
    change_mean: float | None = None
    change_sd: float | None = None
    se: float | None = None
    ci_lower: float | None = None
    ci_upper: float | None = None
    median: float | None = None
    q1: float | None = None
    q3: float | None = None


@dataclass(slots=True)
class ArmBinary:
    n: int | None = None
    events: int | None = None
    proportion: float | None = None


@dataclass(slots=True)
class DiagnosticAccuracyData:
    index_test: str = ""
    reference_standard: str = ""
    threshold: str = ""
    tp: int | None = None
    fp: int | None = None
    fn: int | None = None
    tn: int | None = None
    sensitivity: float | None = None
    specificity: float | None = None
    diseased_n: int | None = None
    non_diseased_n: int | None = None
    reconstruction_completed: bool = False
    paired_comparative: bool = False
    comparative_dependence_data_present: bool = False


@dataclass(slots=True)
class OutcomeDatum:
    outcome_id: str
    outcome_name: str
    outcome_type: OutcomeType
    principal: bool = False
    follow_up: str = ""
    treatment_binary: ArmBinary | None = None
    control_binary: ArmBinary | None = None
    single_binary: ArmBinary | None = None
    treatment_continuous: ArmContinuous | None = None
    control_continuous: ArmContinuous | None = None
    diagnostic: DiagnosticAccuracyData | None = None
    hr: float | None = None
    hr_ci_lower: float | None = None
    hr_ci_upper: float | None = None
    log_hr: float | None = None
    se_log_hr: float | None = None
    o_minus_e: float | None = None
    variance: float | None = None
    common_or: float | None = None
    common_or_ci_lower: float | None = None
    common_or_ci_upper: float | None = None
    person_time: float | None = None
    rate_events: int | None = None
    correlation: float | None = None
    correlation_n: int | None = None
    effect_estimate: float | None = None
    effect_se: float | None = None
    effect_ci_lower: float | None = None
    effect_ci_upper: float | None = None
    effect_measure: str = ""
    performance_estimate: float | None = None
    performance_se: float | None = None
    performance_ci_lower: float | None = None
    performance_ci_upper: float | None = None
    performance_metric: str = ""
    extractable_findings_present: bool = False
    synthesis_method_defined: bool = False
    graph_extraction_completed: bool = False
    graph_extracted_values_present: bool = False
    median_iqr_conversion_completed: bool = False
    median_iqr_conversion_justified: bool = False
    reconstructed_variance_completed: bool = False
    reconstructed_effect_completed: bool = False
    notes: str = ""


@dataclass(frozen=True, slots=True)
class OutcomeUsability:
    outcome_id: str
    status: UsabilityStatus
    reasons: tuple[str, ...]


@dataclass(slots=True)
class StudyUsabilityAudit:
    family_id: str
    outcomes: list[OutcomeUsability] = field(default_factory=list)
    principal_outcome_ids: set[str] = field(default_factory=set)

    @property
    def verified_usable(self) -> bool:
        return any(x.status == UsabilityStatus.VERIFIED_USABLE for x in self.outcomes)

    @property
    def principal_outcome_verified_usable(self) -> bool:
        return any(
            x.outcome_id in self.principal_outcome_ids
            and x.status == UsabilityStatus.VERIFIED_USABLE
            for x in self.outcomes
        )


TrialUsabilityAudit = StudyUsabilityAudit
