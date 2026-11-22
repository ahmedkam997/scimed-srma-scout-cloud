from __future__ import annotations

from dataclasses import dataclass

from scimed_scout.domain import CandidateStatus
from scimed_scout.storage import CandidateRecord, SQLiteLedger


@dataclass(frozen=True, slots=True)
class RankingResult:
    candidate_id: str
    score: float
    reasons: tuple[str, ...]


def preliminary_rank(candidate: CandidateRecord) -> RankingResult:
    """Deterministic preflight ranking used only to prioritize verification work.

    The score never substitutes for novelty, feasibility, evidence counts,
    methodological quality, or final publication gates.
    """
    score = 0.0
    reasons: list[str] = []

    if candidate.review_question.strip():
        score += 18
        reasons.append("explicit review question")
    if candidate.population.strip():
        score += 12
        reasons.append("population specified")
    if candidate.intervention_exposure_index_test.strip():
        score += 12
        reasons.append("intervention/exposure/index test specified")
    if candidate.comparator_reference.strip():
        score += 8
        reasons.append("comparator/reference specified")
    if candidate.outcomes:
        score += min(15, 5 + 2 * len(candidate.outcomes))
        reasons.append("outcomes specified")
    if candidate.eligible_designs:
        score += min(12, 6 + len(candidate.eligible_designs))
        reasons.append("eligible study designs specified")
    if candidate.search_terms:
        score += min(10, 4 + len(candidate.search_terms))
        reasons.append("search terms supplied")
    if candidate.rationale.strip():
        score += 7
        reasons.append("clinical/research rationale supplied")
    if candidate.novelty_hypothesis.strip():
        score += 6
        reasons.append("testable novelty hypothesis supplied")

    vague_tokens = {"various", "multiple conditions", "different outcomes", "all diseases", "any treatment"}
    blob = " ".join([
        candidate.title,
        candidate.review_question,
        candidate.population,
        candidate.intervention_exposure_index_test,
    ]).casefold()
    vague_hits = sum(token in blob for token in vague_tokens)
    if vague_hits:
        penalty = min(15, vague_hits * 5)
        score -= penalty
        reasons.append(f"vagueness penalty -{penalty}")

    return RankingResult(candidate.candidate_id, max(0.0, min(100.0, score)), tuple(reasons))


class CandidateRankingService:
    def __init__(self, ledger: SQLiteLedger):
        self.ledger = ledger

    def rank_project(self, project_id: str, *, top_n: int = 3) -> list[RankingResult]:
        candidates = [
            c for c in self.ledger.list_candidates(project_id)
            if c.status not in {CandidateStatus.REJECTED, CandidateStatus.QUALIFIED}
        ]
        ranked = sorted(
            (preliminary_rank(c) for c in candidates),
            key=lambda x: (-x.score, x.candidate_id),
        )

        ranking_by_id = {item.candidate_id: item for item in ranked}
        top_ids = {item.candidate_id for item in ranked[:max(0, top_n)]}
        for candidate in candidates:
            item = ranking_by_id[candidate.candidate_id]
            candidate.metadata = {
                **(candidate.metadata or {}),
                "preliminary_ranking_score": item.score,
                "preliminary_ranking_reasons": list(item.reasons),
                "preliminary_ranking_role": "verification_priority_only",
            }
            if candidate.candidate_id in top_ids:
                candidate.status = CandidateStatus.SHORTLISTED
            self.ledger.upsert_candidate(candidate)

        return ranked
