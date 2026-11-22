from __future__ import annotations

from dataclasses import dataclass

from .trials.models import TrialFamilyAudit
from .usability.ledger import TrialOutcomeLedger


@dataclass(frozen=True, slots=True)
class DeterministicEvidenceCounts:
    verified_independent_rcts: int
    minimum_possible_independent_rcts: int
    verified_usable_rcts: int
    principal_outcome_rcts: int
    unresolved_trial_family_links: int
    potentially_usable_rcts: int
    family_uncertainty_decision_changing: bool

    @property
    def unresolved_type_a(self) -> list[str]:
        issues: list[str] = []
        if self.family_uncertainty_decision_changing:
            issues.append(
                "Trial-family uncertainty is decision-changing: unresolved possible links "
                f"could reduce the verified independent count from {self.verified_independent_rcts} "
                f"to {self.minimum_possible_independent_rcts}"
            )
        if self.verified_independent_rcts < 7:
            issues.append(
                f"Only {self.verified_independent_rcts} verified independent randomized populations"
            )
        if self.verified_usable_rcts < 7:
            issues.append(
                f"Only {self.verified_usable_rcts} verified quantitatively usable RCT families"
            )
        return issues


def derive_evidence_counts(
    family_audit: TrialFamilyAudit,
    usability_ledgers: list[TrialOutcomeLedger],
) -> DeterministicEvidenceCounts:
    verified_family_ids = {
        family.family_id
        for family in family_audit.families
        if family.verified_for_counting
    }
    verified_usable_ids = {
        ledger.family_id
        for ledger in usability_ledgers
        if ledger.family_id in verified_family_ids and ledger.verified_usable
    }
    principal_ids = {
        ledger.family_id
        for ledger in usability_ledgers
        if ledger.family_id in verified_family_ids and ledger.principal_verified_usable
    }

    return DeterministicEvidenceCounts(
        verified_independent_rcts=len(verified_family_ids),
        minimum_possible_independent_rcts=family_audit.minimum_possible_verified_independent_count(),
        verified_usable_rcts=len(verified_usable_ids),
        principal_outcome_rcts=len(principal_ids),
        unresolved_trial_family_links=len(family_audit.possible_links),
        potentially_usable_rcts=sum(
            1
            for ledger in usability_ledgers
            if ledger.family_id in verified_family_ids and ledger.potentially_usable and not ledger.verified_usable
        ),
        family_uncertainty_decision_changing=family_audit.family_uncertainty_is_decision_changing(),
    )
