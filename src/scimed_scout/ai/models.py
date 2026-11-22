from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


FORBIDDEN_AI_FIELDS = {
    "verified_independent_studies",
    "verified_usable_studies",
    "verified_independent_rcts",
    "verified_usable_rcts",
    "source_status",
    "source_statuses",
    "fatal_redundancy",
    "all_15_gates_passed",
    "final_decision",
    "decision",
    "proceed",
    "publication_oriented_score",
}


@dataclass(frozen=True, slots=True)
class AIRequest:
    system: str
    prompt: str
    temperature: float = 0.2
    max_tokens: int = 4000


@dataclass(frozen=True, slots=True)
class AIResponse:
    text: str
    provider: str
    model: str
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class CandidateProposal:
    title: str
    question_type: str
    review_question: str
    population: str = ""
    intervention_exposure_index_test: str = ""
    comparator_reference: str = ""
    outcomes: list[str] = field(default_factory=list)
    eligible_designs: list[str] = field(default_factory=list)
    rationale: str = ""
    novelty_hypothesis: str = ""
    search_terms: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "CandidateProposal":
        forbidden = FORBIDDEN_AI_FIELDS & {str(k) for k in raw}
        if forbidden:
            raise ValueError(f"AI response attempted to set protected methodological fields: {sorted(forbidden)}")
        title = str(raw.get("title") or "").strip()
        question_type = str(raw.get("question_type") or "").strip()
        review_question = str(raw.get("review_question") or "").strip()
        if not title or not question_type or not review_question:
            raise ValueError("Candidate proposal requires title, question_type, and review_question")
        return cls(
            title=title,
            question_type=question_type,
            review_question=review_question,
            population=str(raw.get("population") or "").strip(),
            intervention_exposure_index_test=str(raw.get("intervention_exposure_index_test") or "").strip(),
            comparator_reference=str(raw.get("comparator_reference") or "").strip(),
            outcomes=_string_list(raw.get("outcomes")),
            eligible_designs=_string_list(raw.get("eligible_designs")),
            rationale=str(raw.get("rationale") or "").strip(),
            novelty_hypothesis=str(raw.get("novelty_hypothesis") or "").strip(),
            search_terms=_string_list(raw.get("search_terms")),
        )


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(x).strip() for x in value if str(x).strip()]
