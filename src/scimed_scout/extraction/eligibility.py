from __future__ import annotations

import json
import re

from scimed_scout.ai import AIProvider, AIRequest
from scimed_scout.storage import CandidateRecord

from .models import EligibilityStatus, ProvenanceField, StudyEligibilityExtraction


SYSTEM_PROMPT = """Extract study-design and eligibility information for a systematic review.
Use only the supplied title/abstract/metadata. Never invent missing fields.
Every extracted field must include a short supporting evidence snippet copied or closely paraphrased from the supplied text.
If eligibility cannot be established from supplied evidence, return UNCERTAIN.
Do not mark any field as manually verified. Return strict JSON only."""


class StudyEligibilityExtractor:
    def __init__(self, provider: AIProvider):
        self.provider = provider

    def extract(self, candidate: CandidateRecord, record: dict) -> StudyEligibilityExtraction:
        evidence_text = _record_evidence_text(record)
        if not evidence_text:
            return _unresolved(record, "No title/abstract/metadata text sufficient for eligibility extraction")

        response = self.provider.complete(
            AIRequest(
                system=SYSTEM_PROMPT,
                prompt=_prompt(candidate, record, evidence_text),
                temperature=0.0,
                max_tokens=3500,
            )
        )
        raw = _json_object(response.text)
        eligibility = _eligibility(raw.get("eligibility"))
        fields = raw.get("fields") if isinstance(raw.get("fields"), dict) else {}

        extracted = StudyEligibilityExtraction(
            study_id=str(record.get("source_record_id") or ""),
            title=str(record.get("title") or ""),
            eligibility=eligibility,
            design_label=_field(fields.get("design_label")),
            population=_field(fields.get("population")),
            intervention_exposure_index_test=_field(fields.get("intervention_exposure_index_test")),
            comparator_reference=_field(fields.get("comparator_reference")),
            outcomes=_field(fields.get("outcomes")),
            sample_size=_field(fields.get("sample_size")),
            registry_ids=_field(fields.get("registry_ids")),
            first_author=_field(fields.get("first_author")),
            year=_field(fields.get("year")),
            exclusion_reason=str(raw.get("exclusion_reason") or "").strip(),
            overall_confidence=_confidence(raw.get("overall_confidence")),
            unresolved_fields=[str(x) for x in (raw.get("unresolved_fields") or []) if str(x).strip()],
            raw=raw,
        )
        return extracted


def _prompt(candidate: CandidateRecord, record: dict, evidence_text: str) -> str:
    return f"""Review eligibility target:
Question type: {candidate.question_type}
Review question: {candidate.review_question}
Population: {candidate.population}
Intervention/Exposure/Index test: {candidate.intervention_exposure_index_test}
Comparator/Reference: {candidate.comparator_reference}
Outcomes: {candidate.outcomes}
Eligible designs: {candidate.eligible_designs}

Study record:
Source: {record.get('source', '')}
Title: {record.get('title', '')}
Evidence:
{evidence_text}

Return:
{{
  "eligibility":"ELIGIBLE|INELIGIBLE|UNCERTAIN",
  "exclusion_reason":"",
  "overall_confidence":0.0,
  "unresolved_fields":[],
  "fields":{{
    "design_label":{{"value":"","evidence":"","source_section":"title/abstract/metadata","confidence":0.0}},
    "population":{{"value":"","evidence":"","source_section":"","confidence":0.0}},
    "intervention_exposure_index_test":{{"value":"","evidence":"","source_section":"","confidence":0.0}},
    "comparator_reference":{{"value":"","evidence":"","source_section":"","confidence":0.0}},
    "outcomes":{{"value":[],"evidence":"","source_section":"","confidence":0.0}},
    "sample_size":{{"value":null,"evidence":"","source_section":"","confidence":0.0}},
    "registry_ids":{{"value":[],"evidence":"","source_section":"","confidence":0.0}},
    "first_author":{{"value":"","evidence":"","source_section":"","confidence":0.0}},
    "year":{{"value":null,"evidence":"","source_section":"","confidence":0.0}}
  }}
}}"""


def _record_evidence_text(record: dict) -> str:
    payload = record.get("payload") or {}
    metadata = payload.get("metadata") or {}
    pieces = [record.get("title"), metadata.get("abstract"), metadata.get("summary"), metadata.get("description")]
    return "\n".join(str(x).strip() for x in pieces if x and str(x).strip())[:16000]


def _field(value) -> ProvenanceField:
    if not isinstance(value, dict):
        return ProvenanceField(None)
    return ProvenanceField(
        value=value.get("value"),
        evidence=str(value.get("evidence") or "").strip(),
        source_section=str(value.get("source_section") or "").strip(),
        confidence=_confidence(value.get("confidence")),
    )


def _eligibility(value) -> EligibilityStatus:
    try:
        return EligibilityStatus(str(value or "").strip().upper())
    except ValueError:
        return EligibilityStatus.UNCERTAIN


def _confidence(value) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


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
            raise ValueError("Eligibility extraction response did not contain JSON")
        value = json.loads(cleaned[start:end + 1])
    if not isinstance(value, dict):
        raise ValueError("Eligibility extraction root must be an object")
    return value


def _unresolved(record: dict, reason: str) -> StudyEligibilityExtraction:
    empty = ProvenanceField(None)
    return StudyEligibilityExtraction(
        study_id=str(record.get("source_record_id") or ""),
        title=str(record.get("title") or ""),
        eligibility=EligibilityStatus.UNCERTAIN,
        design_label=empty,
        population=empty,
        intervention_exposure_index_test=empty,
        comparator_reference=empty,
        outcomes=empty,
        sample_size=empty,
        registry_ids=empty,
        first_author=empty,
        year=empty,
        overall_confidence=0.0,
        unresolved_fields=["all"],
        raw={"reason": reason},
    )
