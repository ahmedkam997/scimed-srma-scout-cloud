from __future__ import annotations

import json
import re

from scimed_scout.ai import AIProvider, AIRequest
from scimed_scout.storage import CandidateRecord

from .models import CompetitorAssessment, DimensionAssessment, OverlapLevel


SYSTEM_PROMPT = """Assess overlap between a candidate systematic-review question and an existing review or registration.
Use only supplied evidence text. Do not infer facts absent from the evidence.
Assess Population, Intervention/Exposure/Index test, Comparator/Reference standard, Outcomes,
study-design scope, clinical decision, treatment/test era, and likely study set/search cutoff.
If evidence is insufficient, use UNRESOLVED. Return strict JSON only.
ESSENTIALLY_IDENTICAL is reserved for near-equivalent clinical questions and scope.
Do not decide the final project verdict."""


def build_overlap_prompt(candidate: CandidateRecord, record: dict) -> str:
    evidence_text = _record_evidence_text(record)
    return f"""Candidate:
Title: {candidate.title}
Question type: {candidate.question_type}
Review question: {candidate.review_question}
Population: {candidate.population}
Intervention/Exposure/Index test: {candidate.intervention_exposure_index_test}
Comparator/Reference: {candidate.comparator_reference}
Outcomes: {candidate.outcomes}
Eligible designs: {candidate.eligible_designs}

Existing record:
Source: {record.get('source', '')}
Title: {record.get('title', '')}
Evidence text:
{evidence_text or '[NO USABLE EVIDENCE TEXT]'}

Return:
{{
  "overall_overlap": "NONE|LOW|MODERATE|HIGH|ESSENTIALLY_IDENTICAL|UNRESOLVED",
  "dimensions": [
    {{"name":"population","level":"...","rationale":"...","evidence":"..."}},
    {{"name":"intervention_exposure_index_test","level":"...","rationale":"...","evidence":"..."}},
    {{"name":"comparator_reference","level":"...","rationale":"...","evidence":"..."}},
    {{"name":"outcomes","level":"...","rationale":"...","evidence":"..."}},
    {{"name":"design_scope","level":"...","rationale":"...","evidence":"..."}},
    {{"name":"clinical_decision","level":"...","rationale":"...","evidence":"..."}},
    {{"name":"era","level":"...","rationale":"...","evidence":"..."}},
    {{"name":"study_set_search_cutoff","level":"...","rationale":"...","evidence":"..."}}
  ],
  "adequate_review": true|false|null,
  "recent_review": true|false|null,
  "meaningful_new_information": true|false|null,
  "confidence": 0.0,
  "rationale": "..."
}}"""


class SemanticCompetitorAssessor:
    def __init__(self, provider: AIProvider):
        self.provider = provider

    def assess(self, candidate: CandidateRecord, record: dict) -> CompetitorAssessment:
        evidence_text = _record_evidence_text(record)
        if not evidence_text:
            return CompetitorAssessment(
                record_id=record.get("source_record_id", ""),
                source=record.get("source", ""),
                title=record.get("title", ""),
                overall_overlap=OverlapLevel.UNRESOLVED,
                confidence=0.0,
                evidence_text_available=False,
                rationale="No abstract/summary/record evidence text available for semantic assessment",
            )

        response = self.provider.complete(
            AIRequest(system=SYSTEM_PROMPT, prompt=build_overlap_prompt(candidate, record), temperature=0.0)
        )
        raw = _json_object(response.text)
        level = _level(raw.get("overall_overlap"))
        dimensions = []
        for item in raw.get("dimensions") or []:
            if not isinstance(item, dict):
                continue
            dimensions.append(
                DimensionAssessment(
                    name=str(item.get("name") or "").strip(),
                    level=_level(item.get("level")),
                    rationale=str(item.get("rationale") or "").strip(),
                    evidence=str(item.get("evidence") or "").strip(),
                )
            )
        confidence = _confidence(raw.get("confidence"))
        return CompetitorAssessment(
            record_id=record.get("source_record_id", ""),
            source=record.get("source", ""),
            title=record.get("title", ""),
            overall_overlap=level,
            dimensions=dimensions,
            adequate_review=_optional_bool(raw.get("adequate_review")),
            recent_review=_optional_bool(raw.get("recent_review")),
            meaningful_new_information=_optional_bool(raw.get("meaningful_new_information")),
            confidence=confidence,
            evidence_text_available=True,
            rationale=str(raw.get("rationale") or "").strip(),
            reviewer=f"{response.provider}:{response.model}",
        )


def _record_evidence_text(record: dict) -> str:
    payload = record.get("payload") or {}
    metadata = payload.get("metadata") or {}
    candidates = [
        metadata.get("abstract"),
        metadata.get("summary"),
        metadata.get("description"),
        metadata.get("brief_summary"),
        payload.get("abstract"),
        payload.get("summary"),
    ]
    text = "\n".join(str(x).strip() for x in candidates if x and str(x).strip())
    if not text:
        title = str(record.get("title") or "").strip()
        return title if len(title.split()) >= 6 else ""
    return text[:12000]


def _level(value) -> OverlapLevel:
    try:
        return OverlapLevel(str(value or "").strip().upper())
    except ValueError:
        return OverlapLevel.UNRESOLVED


def _confidence(value) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def _optional_bool(value):
    return value if isinstance(value, bool) else None


def _json_object(text: str) -> dict:
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
            raise ValueError("Competitor assessment response did not contain JSON")
        value = json.loads(cleaned[start:end + 1])
    if not isinstance(value, dict):
        raise ValueError("Competitor assessment root must be an object")
    return value
