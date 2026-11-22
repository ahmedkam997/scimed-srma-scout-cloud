from __future__ import annotations

import json
import re
from typing import Any

from scimed_scout.ai import AIProvider, AIRequest
from scimed_scout.storage import CandidateRecord

from .evidence_metrics import composite_score, evidence_metrics


SYSTEM_PROMPT = """Score a candidate systematic-review/meta-analysis topic for discovery prioritization.
This is topic discovery only. Do not claim that studies are eligible, synthesis-ready, or extracted.
Use the supplied deterministic search counts and competitor summaries as context, but never alter them.
Return strict JSON only. Be conservative. A fatal methodological flaw means the proposed review question itself
is not defensible as framed. AI ratings of importance, methodological feasibility and editorial quality are preliminary
and require human review. Novelty, information gain proxy and MCDA composite are calculated
from retrieved records by deterministic code. Do not invent study counts or search dates."""


ALLOWED = {
    "design_framework_defined",
    "meaningful_synthesis_plausible",
    "clinical_question_novelty",
    "overall_novelty",
    "question_framework_coherent",
    "feasibility",
    "fatal_methodological_flaw",
    "clinical_importance",
    "publication_potential",
    "new_information_gain",
    "publication_oriented_score",
    "editorial_grade",
    "rationale",
}


class DiscoveryScoringService:
    def __init__(self, provider: AIProvider):
        self.provider = provider

    def score(
        self,
        candidate: CandidateRecord,
        *,
        unique_primary_studies: int,
        published_review_hits: int,
        registration_hits: int,
        competitor_summary: str,
        review_records: list[dict] | None = None,
        registration_records: list[dict] | None = None,
        primary_records: list[dict] | None = None,
        semantically_capped: bool = False,
    ) -> dict[str, Any]:
        response = self.provider.complete(
            AIRequest(
                system=SYSTEM_PROMPT,
                prompt=_prompt(
                    candidate,
                    unique_primary_studies=unique_primary_studies,
                    published_review_hits=published_review_hits,
                    registration_hits=registration_hits,
                    competitor_summary=competitor_summary,
                ),
                temperature=0.0,
                max_tokens=1800,
            )
        )
        raw = _json_object(response.text)
        unexpected = set(raw) - ALLOWED
        if unexpected:
            raise ValueError(f"Discovery scoring returned unsupported fields: {sorted(unexpected)}")

        result = {
            "design_framework_defined": _bool(raw.get("design_framework_defined")),
            "meaningful_synthesis_plausible": _bool(raw.get("meaningful_synthesis_plausible")),
            "clinical_question_novelty": _bounded(raw.get("clinical_question_novelty"), 0, 5),
            "overall_novelty": _bounded(raw.get("overall_novelty"), 0, 5),
            "question_framework_coherent": _bool(raw.get("question_framework_coherent")),
            "feasibility": str(raw.get("feasibility") or "").strip().upper(),
            "fatal_methodological_flaw": _bool(raw.get("fatal_methodological_flaw")),
            "clinical_importance": _bounded(raw.get("clinical_importance"), 0, 5),
            "publication_potential": _bounded(raw.get("publication_potential"), 0, 5),
            "new_information_gain": _bounded(raw.get("new_information_gain"), 0, 5),
            "publication_oriented_score": _bounded(raw.get("publication_oriented_score"), 0, 100),
            "editorial_grade": str(raw.get("editorial_grade") or "").strip().upper(),
            "rationale": str(raw.get("rationale") or "").strip(),
            "scored_by": f"{response.provider}:{response.model}",
        }
        metrics = evidence_metrics(
            review_records or [],
            registration_records or [],
            primary_records or [],
            semantically_capped=semantically_capped,
        )
        # Ignore self-reported AI novelty/information-gain/composite numbers.
        result["clinical_question_novelty"] = metrics["clinical_question_novelty"]
        result["overall_novelty"] = metrics["overall_novelty"]
        result["new_information_gain"] = metrics["new_information_gain"]
        composite = composite_score(
            novelty=result["overall_novelty"],
            information_gain=result["new_information_gain"],
            clinical_importance=result["clinical_importance"],
            feasibility=result["feasibility"],
            publication_potential=result["publication_potential"],
        )
        result["publication_oriented_score"] = composite["publication_oriented_score"]
        result["scoring_trace"] = {
            **metrics,
            **composite,
            "model_only_judgments": [
                "clinical_importance",
                "publication_potential",
                "feasibility",
                "editorial_grade",
                "meaningful_synthesis_plausible",
                "fatal_methodological_flaw",
            ],
            "human_confirmation_needed": True,
        }
        return result


def _prompt(
    candidate: CandidateRecord,
    *,
    unique_primary_studies: int,
    published_review_hits: int,
    registration_hits: int,
    competitor_summary: str,
) -> str:
    return f"""Candidate review topic:
Title: {candidate.title}
Question type: {candidate.question_type}
Review question: {candidate.review_question}
Population: {candidate.population}
Intervention/Exposure/Index test: {candidate.intervention_exposure_index_test}
Comparator/Reference standard: {candidate.comparator_reference}
Outcomes: {candidate.outcomes}
Eligible designs: {candidate.eligible_designs}
Rationale: {candidate.rationale}
Novelty hypothesis: {candidate.novelty_hypothesis}

Deterministic discovery evidence:
Unique primary-study candidates found: {unique_primary_studies}
Published-review records found: {published_review_hits}
Review/protocol registrations found: {registration_hits}

Competitor summary:
{competitor_summary or "No assessed competitor summary available."}

Return:
{{
  "design_framework_defined": true,
  "meaningful_synthesis_plausible": true,
  "clinical_question_novelty": 0,
  "overall_novelty": 0,
  "question_framework_coherent": true,
  "feasibility": "HIGH|STRONG MODERATE|MODERATE|LOW",
  "fatal_methodological_flaw": false,
  "clinical_importance": 0,
  "publication_potential": 0,
  "new_information_gain": 0,
  "publication_oriented_score": 0,
  "editorial_grade": "A|B|CORRECTED C|C|D",
  "rationale": ""
}}"""


def _json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    fence = chr(96) * 3
    if cleaned.startswith(fence):
        cleaned = re.sub("^" + re.escape(fence) + r"(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*" + re.escape(fence) + "$", "", cleaned)
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("Discovery scoring response did not contain JSON")
        value = json.loads(cleaned[start:end + 1])
    if not isinstance(value, dict):
        raise ValueError("Discovery scoring root must be an object")
    return value


def _bool(value: Any) -> bool:
    return value is True or str(value).strip().upper() in {"TRUE", "YES", "1", "PASS"}


def _bounded(value: Any, low: float, high: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return low
    return max(low, min(high, number))
