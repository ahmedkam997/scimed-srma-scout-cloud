from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from scimed_scout.designs import StudyDesignProfile


class FamilyLinkStatus(StrEnum):
    VERIFIED_SAME_FAMILY = "VERIFIED_SAME_FAMILY"
    POSSIBLE_SAME_FAMILY = "POSSIBLE_SAME_FAMILY"
    NO_LINK_IDENTIFIED = "NO_LINK_IDENTIFIED"


@dataclass(slots=True)
class StudyRecord:
    study_id: str
    title: str
    design: StudyDesignProfile
    year: int | None = None
    first_author: str = ""
    doi: str = ""
    registry_ids: list[str] = field(default_factory=list)
    cohort_name: str = ""
    data_source: str = ""
    study_site: str = ""
    recruitment_period: str = ""
    sample_size: int | None = None
    manually_verified_family_id: str = ""
    independence_verified: bool = False
    eligibility_verified: bool = False
    notes: str = ""


@dataclass(frozen=True, slots=True)
class StudyPairLink:
    study_a: str
    study_b: str
    status: FamilyLinkStatus
    reasons: tuple[str, ...]


@dataclass(slots=True)
class StudyFamily:
    family_id: str
    study_ids: list[str]
    registry_ids: list[str] = field(default_factory=list)
    independence_verified: bool = False
    eligibility_verified: bool = False
    design_verified: bool = False

    @property
    def verified_for_counting(self) -> bool:
        return self.independence_verified and self.eligibility_verified and self.design_verified


@dataclass(slots=True)
class StudyFamilyAudit:
    families: list[StudyFamily]
    pair_links: list[StudyPairLink]
    possible_links: list[StudyPairLink]

    @property
    def verified_independent_study_count(self) -> int:
        return sum(f.verified_for_counting for f in self.families)

    def study_to_family(self) -> dict[str, str]:
        return {study_id: f.family_id for f in self.families for study_id in f.study_ids}

    def minimum_possible_verified_independent_count(self) -> int:
        verified = {f.family_id for f in self.families if f.verified_for_counting}
        if not verified:
            return 0
        parent = {x: x for x in verified}
        mapping = self.study_to_family()

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
            a, b = mapping.get(link.study_a), mapping.get(link.study_b)
            if a in verified and b in verified and a != b:
                union(a, b)
        return len({find(x) for x in verified})

    def family_uncertainty_is_decision_changing(self, threshold: int = 4) -> bool:
        return (
            bool(self.possible_links)
            and self.verified_independent_study_count >= threshold
            and self.minimum_possible_verified_independent_count() < threshold
        )
