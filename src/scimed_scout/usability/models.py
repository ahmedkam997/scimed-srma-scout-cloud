from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class OutcomeType(StrEnum):
    BINARY = "BINARY"
    CONTINUOUS = "CONTINUOUS"
    TIME_TO_EVENT = "TIME_TO_EVENT"
    ORDINAL = "ORDINAL"


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
class OutcomeDatum:
    outcome_id: str
    outcome_name: str
    outcome_type: OutcomeType
    principal: bool = False
    follow_up: str = ""
    treatment_binary: ArmBinary | None = None
    control_binary: ArmBinary | None = None
    treatment_continuous: ArmContinuous | None = None
    control_continuous: ArmContinuous | None = None
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
class TrialUsabilityAudit:
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
