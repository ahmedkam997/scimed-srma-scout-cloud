from __future__ import annotations

from dataclasses import dataclass, field

from .audit import assess_outcome
from .models import OutcomeDatum, OutcomeUsability, UsabilityStatus


@dataclass(slots=True)
class StudyOutcomeLedger:
    family_id: str
    outcomes: list[OutcomeDatum] = field(default_factory=list)

    def assessments(self) -> list[OutcomeUsability]:
        return [assess_outcome(outcome) for outcome in self.outcomes]

    @property
    def verified_usable(self) -> bool:
        return any(x.status == UsabilityStatus.VERIFIED_USABLE for x in self.assessments())

    @property
    def principal_verified_usable(self) -> bool:
        assessment_by_id = {x.outcome_id: x for x in self.assessments()}
        return any(
            outcome.principal
            and assessment_by_id[outcome.outcome_id].status == UsabilityStatus.VERIFIED_USABLE
            for outcome in self.outcomes
        )

    @property
    def potentially_usable(self) -> bool:
        return any(x.status == UsabilityStatus.POTENTIALLY_USABLE for x in self.assessments())


TrialOutcomeLedger = StudyOutcomeLedger


@dataclass(frozen=True, slots=True)
class UsabilityCountSummary:
    verified_usable_families: int
    principal_outcome_verified_usable_families: int
    potentially_usable_families: int


def summarize_ledgers(ledgers: list[StudyOutcomeLedger]) -> UsabilityCountSummary:
    return UsabilityCountSummary(
        verified_usable_families=sum(ledger.verified_usable for ledger in ledgers),
        principal_outcome_verified_usable_families=sum(ledger.principal_verified_usable for ledger in ledgers),
        potentially_usable_families=sum(ledger.potentially_usable for ledger in ledgers),
    )
