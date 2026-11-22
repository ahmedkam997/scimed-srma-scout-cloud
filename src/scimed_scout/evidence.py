from __future__ import annotations

from dataclasses import dataclass

from .usability.ledger import StudyOutcomeLedger


MIN_STUDIES = 4


@dataclass(frozen=True, slots=True)
class DeterministicEvidenceCounts:
    verified_independent_studies: int
    minimum_possible_independent_studies: int
    verified_usable_studies: int
    principal_outcome_studies: int
    unresolved_family_links: int
    potentially_usable_studies: int
    family_uncertainty_decision_changing: bool

    @property
    def verified_independent_rcts(self) -> int:
        return self.verified_independent_studies

    @property
    def verified_usable_rcts(self) -> int:
        return self.verified_usable_studies

    @property
    def principal_outcome_rcts(self) -> int:
        return self.principal_outcome_studies

    @property
    def minimum_possible_independent_rcts(self) -> int:
        return self.minimum_possible_independent_studies

    @property
    def unresolved_trial_family_links(self) -> int:
        return self.unresolved_family_links

    @property
    def potentially_usable_rcts(self) -> int:
        return self.potentially_usable_studies

    @property
    def unresolved_type_a(self) -> list[str]:
        issues: list[str] = []
        if self.family_uncertainty_decision_changing:
            issues.append(
                "Study-family uncertainty is decision-changing: unresolved possible links "
                f"could reduce the verified independent count from {self.verified_independent_studies} "
                f"to {self.minimum_possible_independent_studies}"
            )
        if self.verified_independent_studies < MIN_STUDIES:
            issues.append(
                f"Only {self.verified_independent_studies} verified independent eligible studies"
            )
        if self.verified_usable_studies < MIN_STUDIES:
            issues.append(
                f"Only {self.verified_usable_studies} verified synthesis-usable study families"
            )
        return issues


def derive_evidence_counts(
    family_audit,
    usability_ledgers: list[StudyOutcomeLedger],
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

    verified_count = len(verified_family_ids)
    minimum_count = family_audit.minimum_possible_verified_independent_count()
    return DeterministicEvidenceCounts(
        verified_independent_studies=verified_count,
        minimum_possible_independent_studies=minimum_count,
        verified_usable_studies=len(verified_usable_ids),
        principal_outcome_studies=len(principal_ids),
        unresolved_family_links=len(family_audit.possible_links),
        potentially_usable_studies=sum(
            1
            for ledger in usability_ledgers
            if ledger.family_id in verified_family_ids and ledger.potentially_usable and not ledger.verified_usable
        ),
        family_uncertainty_decision_changing=family_audit.family_uncertainty_is_decision_changing(threshold=MIN_STUDIES),
    )
