from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from scimed_scout.designs import ReviewQuestionType


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
    specialty: str = ""
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
            question_type=normalize_question_type(
                question_type,
                title=title,
                designs=_string_list(raw.get("eligible_designs")),
            ),
            review_question=review_question,
            specialty=str(raw.get("specialty") or "").strip(),
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


def normalize_question_type(value: str, *, title: str = "", designs: list[str] | None = None) -> str:
    """Normalize model wording into the supported methodological question types.

    'Systematic review' and 'meta-analysis' are publication formats, not
    clinical PICO question types. An unclear question stays OTHER.
    """
    text = str(value or "").strip().upper().replace("-", "_").replace(" ", "_")
    valid = {item.value for item in ReviewQuestionType}
    if text in valid:
        return text
    if "DIAGNOS" in text or "TEST_ACCURACY" in text:
        return ReviewQuestionType.DIAGNOSTIC_ACCURACY.value
    if "PREDICT" in text:
        return ReviewQuestionType.PREDICTION_MODEL.value
    if "PROGNOS" in text:
        return ReviewQuestionType.PROGNOSIS.value
    if "PREVALEN" in text or "INCIDEN" in text:
        return ReviewQuestionType.PREVALENCE_INCIDENCE.value
    if "SAFETY" in text or "ADVERSE" in text or "HARM" in text:
        return ReviewQuestionType.SAFETY_HARMS.value
    if "ETIOLOG" in text or "RISK_FACTOR" in text:
        return ReviewQuestionType.ETIOLOGY_RISK.value
    if "QUALITATIVE" in text:
        return ReviewQuestionType.QUALITATIVE.value
    if "IMPLEMENT" in text:
        return ReviewQuestionType.IMPLEMENTATION.value
    if "ECONOMIC" in text or "COST_EFFECT" in text:
        return ReviewQuestionType.ECONOMIC.value
    if "ASSOCIATION" in text:
        return ReviewQuestionType.ASSOCIATION.value
    if "INTERVENTION" in text or "EFFICACY" in text or "EFFECTIVENESS" in text:
        return ReviewQuestionType.EFFECTIVENESS.value
    if "META" in text or "SYSTEMATIC_REVIEW" in text:
        eligible = " ".join(designs or []).casefold()
        heading = str(title or "").casefold()
        if any(marker in eligible for marker in (
            "randomiz", "randomis", "cross-over", "crossover", "intervention", "clinical trial"
        )) or any(marker in heading for marker in (" versus ", " compared with ", " vs ")):
            return ReviewQuestionType.EFFECTIVENESS.value
    return ReviewQuestionType.OTHER.value
