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
Every non-empty dimension evidence field must be a short exact quote from the supplied evidence text.
Keep quotes to <= 12 words and reasons to <= 8 words. If evidence is insufficient,
use UNRESOLVED with empty evidence. Return short, complete, strict JSON.
Never invent a competing review, paper, source excerpt, or last-search date.
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


def build_batch_overlap_prompt(candidate: CandidateRecord, records: list[dict]) -> str:
    rows = []
    for record in records:
        evidence_text = _record_evidence_text(record)
        rows.append(
            {
                "record_id": str(record.get("source_record_id") or ""),
                "source": str(record.get("source") or ""),
                "title": str(record.get("title") or ""),
                "evidence_text": evidence_text[:900],
            }
        )

    # A compact schema is important for free GPT-OSS inference. Responses
    # with eight verbose dimensions frequently exhausted output budgets and
    # caused every competitor to become "unresolved".
    return f"""Evaluate each existing record against this proposed SRMA PICO.
Proposed: {candidate.title}
Population: {candidate.population}
Intervention: {candidate.intervention_exposure_index_test}
Comparator: {candidate.comparator_reference}
Outcomes: {candidate.outcomes}
Study designs: {candidate.eligible_designs}
Existing source-backed records: {json.dumps(rows, ensure_ascii=False)}

Return ONE strict JSON object with assessments for EVERY supplied record_id.
Each dimension must use a short exact quote from that record's evidence_text, or
level UNRESOLVED with evidence "". Never infer last search date from publication
year, or equate a PROSPERO/OSF registration with a journal publication.
Required fields for each entry:
{{
 "record_id":"exact supplied ID",
 "overall_overlap":"NONE|LOW|MODERATE|HIGH|ESSENTIALLY_IDENTICAL|UNRESOLVED",
 "dimensions":[
  {{"name":"population","level":"HIGH","evidence":"exact quote"}},
  {{"name":"intervention_exposure_index_test","level":"HIGH","evidence":"exact quote"}},
  {{"name":"comparator_reference","level":"HIGH","evidence":"exact quote"}},
  {{"name":"outcomes","level":"HIGH","evidence":"exact quote"}},
  {{"name":"design_scope","level":"HIGH","evidence":"exact quote"}},
  {{"name":"clinical_decision","level":"HIGH","evidence":"exact quote"}}
 ],
 "adequate_review":null,"recent_review":null,"meaningful_new_information":null,
 "confidence":0.0,"rationale":"brief"
}}
Wrap entries in {{"assessments":[...]}}. Choose levels based on evidence, not
on the example's HIGH placeholder. Do not claim a recent search without date."""


class SemanticCompetitorAssessor:
    def __init__(self, provider: AIProvider):
        self.provider = provider

    def assess(self, candidate: CandidateRecord, record: dict) -> CompetitorAssessment:
        evidence_text = _record_evidence_text(record)
        if not evidence_text:
            return _unresolved_record(record, "No abstract/summary/record evidence text available for semantic assessment")

        response = self.provider.complete(
            AIRequest(system=SYSTEM_PROMPT, prompt=build_overlap_prompt(candidate, record), temperature=0.0)
        )
        raw = _json_object(response.text)
        return _assessment_from_raw(raw, record, evidence_text, response.provider, response.model)

    def assess_many(
        self,
        candidate: CandidateRecord,
        records: list[dict],
    ) -> list[CompetitorAssessment]:
        if not records:
            return []

        usable: list[dict] = []
        unresolved_by_id: dict[str, CompetitorAssessment] = {}
        for record in records:
            rid = str(record.get("source_record_id") or "")
            if not _record_evidence_text(record):
                unresolved_by_id[rid] = _unresolved_record(
                    record,
                    "No abstract/summary/record evidence text available for semantic assessment",
                )
            else:
                usable.append(record)

        parsed_by_id: dict[str, dict] = {}
        provider_name = "AI_PROVISIONAL"
        model_name = ""
        if usable:
            response = self.provider.complete(
                AIRequest(
                    system=SYSTEM_PROMPT + "\nAssess every supplied record independently and return one item for each record_id.",
                    prompt=build_batch_overlap_prompt(candidate, usable),
                    temperature=0.0,
                    max_tokens=2400,
                )
            )
            provider_name = response.provider
            model_name = response.model
            root = _json_object(response.text)
            for item in root.get("assessments") or []:
                if not isinstance(item, dict):
                    continue
                rid = str(item.get("record_id") or "")
                if rid:
                    parsed_by_id[rid] = item

        results: list[CompetitorAssessment] = []
        for record in records:
            rid = str(record.get("source_record_id") or "")
            if rid in unresolved_by_id:
                results.append(unresolved_by_id[rid])
                continue
            raw = parsed_by_id.get(rid)
            if raw is None:
                results.append(
                    _unresolved_record(
                        record,
                        "Batch semantic assessment omitted this record",
                    )
                )
                continue
            results.append(
                _assessment_from_raw(
                    raw,
                    record,
                    _record_evidence_text(record),
                    provider_name,
                    model_name,
                )
            )
        return results


def _unresolved_record(record: dict, rationale: str) -> CompetitorAssessment:
    return CompetitorAssessment(
        record_id=str(record.get("source_record_id") or ""),
        source=str(record.get("source") or ""),
        title=str(record.get("title") or ""),
        overall_overlap=OverlapLevel.UNRESOLVED,
        confidence=0.0,
        evidence_text_available=False,
        rationale=rationale,
    )


def _assessment_from_raw(
    raw: dict,
    record: dict,
    evidence_text: str,
    provider_name: str,
    model_name: str,
) -> CompetitorAssessment:
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

    result = CompetitorAssessment(
        record_id=str(record.get("source_record_id") or ""),
        source=str(record.get("source") or ""),
        title=str(record.get("title") or ""),
        overall_overlap=_level(raw.get("overall_overlap")),
        dimensions=dimensions,
        adequate_review=_optional_bool(raw.get("adequate_review")),
        recent_review=_optional_bool(raw.get("recent_review")),
        meaningful_new_information=_optional_bool(raw.get("meaningful_new_information")),
        confidence=_confidence(raw.get("confidence")),
        evidence_text_available=True,
        rationale=str(raw.get("rationale") or "").strip(),
        reviewer=f"{provider_name}:{model_name}".rstrip(":"),
    )
    return _validate_dimension_provenance(result, evidence_text)



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



def _validate_dimension_provenance(
    assessment: CompetitorAssessment,
    evidence_text: str,
) -> CompetitorAssessment:
    source = _norm(evidence_text)
    invalid = False
    validated: list[DimensionAssessment] = []
    for item in assessment.dimensions:
        quote = _norm(item.evidence)
        if quote and quote not in source:
            invalid = True
            validated.append(
                DimensionAssessment(
                    name=item.name,
                    level=OverlapLevel.UNRESOLVED,
                    rationale=item.rationale,
                    evidence=item.evidence,
                )
            )
        else:
            validated.append(item)
    assessment.dimensions = validated
    if invalid:
        assessment.overall_overlap = OverlapLevel.UNRESOLVED
        assessment.confidence = min(assessment.confidence, 0.79)
        assessment.rationale = (
            assessment.rationale + " Evidence provenance validation failed for one or more dimensions."
        ).strip()
    return assessment


def _norm(text: str) -> str:
    return " ".join(str(text or "").casefold().split())
