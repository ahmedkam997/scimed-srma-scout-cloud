from __future__ import annotations

from collections import defaultdict

from scimed_scout.trials.identifiers import normalize_doi, normalize_registry_id, normalize_text, token_jaccard
from .models import FamilyLinkStatus, StudyFamily, StudyFamilyAudit, StudyPairLink, StudyRecord


class EvidenceFamilyResolver:
    """Design-agnostic duplicate-population/publication resolver.

    Automatic merging requires strong identifiers. Weaker overlap in cohort,
    site, recruitment period, sample size, author or title is flagged for
    manual verification rather than merged.
    """

    def audit(self, studies: list[StudyRecord]) -> StudyFamilyAudit:
        parent = {s.study_id: s.study_id for s in studies}
        links: list[StudyPairLink] = []
        possible: list[StudyPairLink] = []

        def find(x: str) -> str:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a: str, b: str) -> None:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[rb] = ra

        for i, a in enumerate(studies):
            for b in studies[i + 1:]:
                link = self.compare(a, b)
                links.append(link)
                if link.status == FamilyLinkStatus.VERIFIED_SAME_FAMILY:
                    union(a.study_id, b.study_id)
                elif link.status == FamilyLinkStatus.POSSIBLE_SAME_FAMILY:
                    possible.append(link)

        groups: dict[str, list[StudyRecord]] = defaultdict(list)
        for study in studies:
            groups[find(study.study_id)].append(study)

        families: list[StudyFamily] = []
        for idx, members in enumerate(groups.values(), 1):
            manual = {m.manually_verified_family_id for m in members if m.manually_verified_family_id}
            registries = sorted({
                normalize_registry_id(r)
                for m in members
                for r in m.registry_ids
                if r
            })
            family_id = next(iter(manual)) if len(manual) == 1 else (registries[0] if registries else f"STUDY-{idx:04d}")
            families.append(
                StudyFamily(
                    family_id=family_id,
                    study_ids=sorted(m.study_id for m in members),
                    registry_ids=registries,
                    independence_verified=any(m.independence_verified for m in members),
                    eligibility_verified=any(m.eligibility_verified for m in members),
                    design_verified=any(m.design.design_verified for m in members),
                )
            )

        return StudyFamilyAudit(
            families=sorted(families, key=lambda x: x.family_id),
            pair_links=links,
            possible_links=possible,
        )

    def compare(self, a: StudyRecord, b: StudyRecord) -> StudyPairLink:
        if (
            a.manually_verified_family_id
            and b.manually_verified_family_id
            and a.manually_verified_family_id == b.manually_verified_family_id
        ):
            return StudyPairLink(a.study_id, b.study_id, FamilyLinkStatus.VERIFIED_SAME_FAMILY, ("same manually verified family ID",))

        a_reg = {normalize_registry_id(x) for x in a.registry_ids if x}
        b_reg = {normalize_registry_id(x) for x in b.registry_ids if x}
        shared = sorted(a_reg & b_reg)
        if shared:
            return StudyPairLink(a.study_id, b.study_id, FamilyLinkStatus.VERIFIED_SAME_FAMILY, tuple(f"shared registry ID {x}" for x in shared))

        a_doi, b_doi = normalize_doi(a.doi), normalize_doi(b.doi)
        if a_doi and b_doi and a_doi == b_doi:
            return StudyPairLink(a.study_id, b.study_id, FamilyLinkStatus.VERIFIED_SAME_FAMILY, ("duplicate DOI",))

        reasons: list[str] = []
        if a.cohort_name and b.cohort_name and normalize_text(a.cohort_name) == normalize_text(b.cohort_name):
            reasons.append("same cohort name")
        if a.data_source and b.data_source and normalize_text(a.data_source) == normalize_text(b.data_source):
            reasons.append("same data source")
        if a.study_site and b.study_site and normalize_text(a.study_site) == normalize_text(b.study_site):
            reasons.append("same study site")
        if a.recruitment_period and b.recruitment_period and normalize_text(a.recruitment_period) == normalize_text(b.recruitment_period):
            reasons.append("same recruitment period")
        if a.sample_size is not None and b.sample_size is not None and a.sample_size == b.sample_size:
            reasons.append("same sample size")
        if a.first_author and b.first_author and normalize_text(a.first_author) == normalize_text(b.first_author):
            reasons.append("same first author")
        similarity = token_jaccard(a.title, b.title)
        if similarity >= 0.55:
            reasons.append(f"title token overlap {similarity:.2f}")

        status = FamilyLinkStatus.POSSIBLE_SAME_FAMILY if len(reasons) >= 2 else FamilyLinkStatus.NO_LINK_IDENTIFIED
        return StudyPairLink(a.study_id, b.study_id, status, tuple(reasons))
