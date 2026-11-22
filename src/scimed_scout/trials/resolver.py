from __future__ import annotations

from collections import defaultdict

from .identifiers import normalize_doi, normalize_registry_id, normalize_text, token_jaccard
from .models import (
    EvidenceStrength,
    FamilyLinkStatus,
    PairLink,
    TrialFamily,
    TrialFamilyAudit,
    TrialPublication,
)


class TrialFamilyResolver:
    """Conservative trial-family resolver.

    Only very strong evidence creates an automatic family union:
    1. the same manually verified family ID, or
    2. at least one exact shared trial-registration identifier.

    DOI duplication is treated as a duplicate publication record and therefore
    the same family. Weaker bibliographic similarity is flagged for manual audit
    and never used to inflate or collapse the independent-RCT count.
    """

    def audit(self, publications: list[TrialPublication]) -> TrialFamilyAudit:
        by_id = {p.publication_id: p for p in publications}
        parent = {p.publication_id: p.publication_id for p in publications}
        links: list[PairLink] = []
        possible: list[PairLink] = []

        def find(x: str) -> str:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a: str, b: str) -> None:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[rb] = ra

        for i, a in enumerate(publications):
            for b in publications[i + 1:]:
                link = self.compare(a, b)
                links.append(link)
                if link.status == FamilyLinkStatus.VERIFIED_SAME_FAMILY:
                    union(a.publication_id, b.publication_id)
                elif link.status == FamilyLinkStatus.POSSIBLE_SAME_FAMILY:
                    possible.append(link)

        grouped: dict[str, list[TrialPublication]] = defaultdict(list)
        for publication in publications:
            grouped[find(publication.publication_id)].append(publication)

        families: list[TrialFamily] = []
        for index, members in enumerate(grouped.values(), start=1):
            manual_ids = {m.manually_verified_family_id for m in members if m.manually_verified_family_id}
            registry_ids = sorted({
                normalize_registry_id(registry_id)
                for m in members
                for registry_id in m.registry_ids
                if registry_id
            })
            family_id = (
                next(iter(manual_ids))
                if len(manual_ids) == 1
                else (registry_ids[0] if registry_ids else f"FAMILY-{index:04d}")
            )
            families.append(
                TrialFamily(
                    family_id=family_id,
                    publication_ids=sorted(m.publication_id for m in members),
                    registry_ids=registry_ids,
                    manually_verified=bool(manual_ids),
                    independence_verified=any(m.independence_verified for m in members),
                    randomization_verified=any(m.randomization_verified for m in members),
                    eligibility_verified=any(m.eligibility_verified for m in members),
                )
            )

        unresolved = sorted({
            publication_id
            for link in possible
            for publication_id in (link.publication_a, link.publication_b)
        })

        return TrialFamilyAudit(
            families=sorted(families, key=lambda f: f.family_id),
            pair_links=links,
            possible_links=possible,
            unresolved_publications=unresolved,
        )

    def compare(self, a: TrialPublication, b: TrialPublication) -> PairLink:
        reasons: list[str] = []

        if (
            a.manually_verified_family_id
            and b.manually_verified_family_id
            and a.manually_verified_family_id == b.manually_verified_family_id
        ):
            return PairLink(
                a.publication_id,
                b.publication_id,
                FamilyLinkStatus.VERIFIED_SAME_FAMILY,
                EvidenceStrength.VERY_STRONG,
                ("same manually verified family ID",),
            )

        a_reg = {normalize_registry_id(x) for x in a.registry_ids if x}
        b_reg = {normalize_registry_id(x) for x in b.registry_ids if x}
        shared_reg = sorted(a_reg & b_reg)
        if shared_reg:
            return PairLink(
                a.publication_id,
                b.publication_id,
                FamilyLinkStatus.VERIFIED_SAME_FAMILY,
                EvidenceStrength.VERY_STRONG,
                tuple(f"shared registry ID {x}" for x in shared_reg),
            )

        a_doi, b_doi = normalize_doi(a.doi), normalize_doi(b.doi)
        if a_doi and b_doi and a_doi == b_doi:
            return PairLink(
                a.publication_id,
                b.publication_id,
                FamilyLinkStatus.VERIFIED_SAME_FAMILY,
                EvidenceStrength.VERY_STRONG,
                ("duplicate DOI record",),
            )

        if a.acronym and b.acronym and normalize_text(a.acronym) == normalize_text(b.acronym):
            reasons.append("same trial acronym")

        if a.randomized_n is not None and b.randomized_n is not None and a.randomized_n == b.randomized_n:
            reasons.append("same randomized sample size")

        if a.first_author and b.first_author and normalize_text(a.first_author) == normalize_text(b.first_author):
            reasons.append("same first author")

        title_similarity = token_jaccard(a.title, b.title)
        if title_similarity >= 0.55:
            reasons.append(f"title token overlap {title_similarity:.2f}")

        intervention_overlap = _label_overlap(a.intervention_labels, b.intervention_labels)
        if intervention_overlap >= 0.5:
            reasons.append(f"intervention-label overlap {intervention_overlap:.2f}")

        if len(reasons) >= 2 or (
            any(reason == "same trial acronym" for reason in reasons)
            and any(reason.startswith("title token overlap") for reason in reasons)
        ):
            return PairLink(
                a.publication_id,
                b.publication_id,
                FamilyLinkStatus.POSSIBLE_SAME_FAMILY,
                EvidenceStrength.MODERATE,
                tuple(reasons),
            )

        return PairLink(
            a.publication_id,
            b.publication_id,
            FamilyLinkStatus.NO_LINK_IDENTIFIED,
            EvidenceStrength.WEAK,
            tuple(reasons),
        )


def _label_overlap(left: list[str], right: list[str]) -> float:
    a = {normalize_text(x) for x in left if normalize_text(x)}
    b = {normalize_text(x) for x in right if normalize_text(x)}
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)
