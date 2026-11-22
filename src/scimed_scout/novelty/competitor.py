from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class OverlapLevel(StrEnum):
    MINIMAL = "MINIMAL"
    PARTIAL = "PARTIAL"
    SUBSTANTIAL_BUT_DISTINCT = "SUBSTANTIAL BUT DISTINCT"
    HIGH = "HIGH"
    ESSENTIALLY_IDENTICAL = "ESSENTIALLY IDENTICAL"


@dataclass(slots=True)
class CompetitorMatrix:
    population: float = 0.0
    intervention: float = 0.0
    comparator: float = 0.0
    clinical_decision: float = 0.0
    principal_outcomes: float = 0.0
    design_restriction: float = 0.0
    treatment_era: float = 0.0
    trial_set: float = 0.0
    adequate: bool = False
    recent: bool = False
    meaningful_new_information: bool = True

    def overlap_level(self) -> OverlapLevel:
        values = [
            self.population,
            self.intervention,
            self.comparator,
            self.clinical_decision,
            self.principal_outcomes,
            self.design_restriction,
            self.treatment_era,
            self.trial_set,
        ]
        values = [_clamp(v) for v in values]
        mean = sum(values) / len(values)
        core = min(
            _clamp(self.population),
            _clamp(self.intervention),
            _clamp(self.clinical_decision),
            _clamp(self.design_restriction),
        )

        if core >= 0.9 and mean >= 0.88:
            return OverlapLevel.ESSENTIALLY_IDENTICAL
        if core >= 0.75 and mean >= 0.75:
            return OverlapLevel.HIGH
        if mean >= 0.55:
            return OverlapLevel.SUBSTANTIAL_BUT_DISTINCT
        if mean >= 0.30:
            return OverlapLevel.PARTIAL
        return OverlapLevel.MINIMAL

    def fatal_redundancy(self) -> bool:
        return (
            self.overlap_level() == OverlapLevel.ESSENTIALLY_IDENTICAL
            and self.adequate
            and self.recent
            and not self.meaningful_new_information
        )


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))
