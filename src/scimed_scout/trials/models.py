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


@dataclass(slots=True)
class TrialFamilyAudit:
    families: list[TrialFamily]
    pair_links: list[PairLink]
    possible_links: list[PairLink]
    unresolved_publications: list[str]

    @property
    def verified_independent_population_count(self) -> int:
        return sum(
            1
            for family in self.families
            if family.independence_verified
            and family.randomization_verified
            and family.eligibility_verified
        )

    @property
    def all_possible_links_resolved(self) -> bool:
        return not self.possible_links
