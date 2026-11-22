from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class FamilyLinkStatus(StrEnum):
    VERIFIED_SAME_FAMILY = "VERIFIED_SAME_FAMILY"
    POSSIBLE_SAME_FAMILY = "POSSIBLE_SAME_FAMILY"
    NO_LINK_IDENTIFIED = "NO_LINK_IDENTIFIED"


class EvidenceStrength(StrEnum):
    VERY_STRONG = "VERY_STRONG"
    STRONG = "STRONG"
    MODERATE = "MODERATE"
    WEAK = "WEAK"


@dataclass(slots=True)
class TrialPublication:
    publication_id: str
    title: str
    year: int | None = None
    first_author: str = ""
    doi: str = ""
    registry_ids: list[str] = field(default_factory=list)
    acronym: str = ""
    randomized_n: int | None = None
    intervention_labels: list[str] = field(default_factory=list)
    population_label: str = ""
    manually_verified_family_id: str = ""
    independence_verified: bool = False
    randomization_verified: bool = False
    eligibility_verified: bool = False
    notes: str = ""


@dataclass(frozen=True, slots=True)
class PairLink:
    publication_a: str
    publication_b: str
    status: FamilyLinkStatus
    strength: EvidenceStrength
    reasons: tuple[str, ...]


@dataclass(slots=True)
class TrialFamily:
    family_id: str
    publication_ids: list[str]
    registry_ids: list[str] = field(default_factory=list)
    manually_verified: bool = False
    independence_verified: bool = False
    randomization_verified: bool = False
    eligibility_verified: bool = False

    @property
    def verified_for_counting(self) -> bool:
        return self.independence_verified and self.randomization_verified and self.eligibility_verified


@dataclass(slots=True)
class TrialFamilyAudit:
    families: list[TrialFamily]
    pair_links: list[PairLink]
    possible_links: list[PairLink]
    unresolved_publications: list[str]

    @property
    def verified_independent_population_count(self) -> int:
        return sum(family.verified_for_counting for family in self.families)

    @property
    def all_possible_links_resolved(self) -> bool:
        return not self.possible_links

    def publication_to_family(self) -> dict[str, str]:
        return {
            publication_id: family.family_id
            for family in self.families
            for publication_id in family.publication_ids
        }

    def minimum_possible_verified_independent_count(self) -> int:
        """Worst-case count if every unresolved possible link were the same trial.

        This is used only to decide whether unresolved family links are Type-A.
        It does not merge them in the actual family ledger.
        """
        verified_ids = {family.family_id for family in self.families if family.verified_for_counting}
        if not verified_ids:
            return 0

        parent = {family_id: family_id for family_id in verified_ids}
        publication_family = self.publication_to_family()

        def find(x: str) -> str:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a: str, b: str) -> None:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[rb] = ra

        for link in self.possible_links:
            family_a = publication_family.get(link.publication_a)
            family_b = publication_family.get(link.publication_b)
            if (
                family_a in verified_ids
                and family_b in verified_ids
                and family_a != family_b
            ):
                union(family_a, family_b)

        return len({find(family_id) for family_id in verified_ids})

    def family_uncertainty_is_decision_changing(self, threshold: int = 4) -> bool:
        return (
            bool(self.possible_links)
            and self.verified_independent_population_count >= threshold
            and self.minimum_possible_verified_independent_count() < threshold
        )
