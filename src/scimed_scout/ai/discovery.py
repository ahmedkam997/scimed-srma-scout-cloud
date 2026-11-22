from __future__ import annotations

import hashlib
import json
import re
from typing import Iterable

from scimed_scout.domain import CandidateStatus
from scimed_scout.storage import CandidateRecord, SQLiteLedger
from scimed_scout.storage.models import utc_now
from .models import AIRequest, CandidateProposal
from .providers import AIProvider


SYSTEM_PROMPT = """You assist with generating candidate systematic-review and meta-analysis questions.
You do not verify novelty, count eligible studies, declare feasibility, assign source status, apply final gates, or make a PROCEED decision.
Return only candidate proposals for later deterministic and source-based verification.
The review engine supports all study designs, including diagnostic accuracy studies.
Use precise clinical and research language and do not invent study counts or registry-search results."""


def build_discovery_prompt(
    *,
    specialty: str,
    question_types: Iterable[str] = (),
    design_scope: Iterable[str] = (),
    count: int = 10,
    additional_context: str = "",
) -> str:
    qtypes = ", ".join(question_types) or "any appropriate review-question type"
    designs = ", ".join(design_scope) or "any appropriate eligible study design"
    return f"""Generate {int(count)} candidate systematic-review/meta-analysis research questions.

Specialty: {specialty}
Question-type scope: {qtypes}
Study-design scope: {designs}
Additional context: {additional_context.strip() or 'None'}

Return strict JSON with this shape:
{{
  "candidates": [
    {{
      "title": "...",
      "question_type": "...",
      "review_question": "...",
      "population": "...",
      "intervention_exposure_index_test": "...",
      "comparator_reference": "...",
      "outcomes": ["..."],
      "eligible_designs": ["..."],
      "rationale": "...",
      "novelty_hypothesis": "A hypothesis to test, not a verified novelty claim",
      "search_terms": ["..."]
    }}
  ]
}}

Do not include verified study counts, source-search results, gate scores, publication score, or final decisions.
"""


def parse_candidate_proposals(text: str) -> list[CandidateProposal]:
    payload = _parse_json_object(text)
    forbidden_root = {"decision", "final_decision", "proceed", "verified_independent_studies", "verified_usable_studies"} & {str(k) for k in payload}
    if forbidden_root:
        raise ValueError(f"AI response root attempted to set protected methodological fields: {sorted(forbidden_root)}")
    candidates = payload.get("candidates")
    if not isinstance(candidates, list):
        raise ValueError("AI response must contain a candidates array")
    proposals = [CandidateProposal.from_dict(item) for item in candidates if isinstance(item, dict)]
    if not proposals:
        raise ValueError("AI response did not contain any valid candidate proposals")
    return proposals


class CandidateDiscoveryService:
    def __init__(self, provider: AIProvider, ledger: SQLiteLedger):
        self.provider = provider
        self.ledger = ledger

    def generate_and_store(
        self,
        *,
        project_id: str,
        specialty: str,
        question_types: Iterable[str] = (),
        design_scope: Iterable[str] = (),
        count: int = 10,
        additional_context: str = "",
        allow_rejected_revisit: bool = False,
    ) -> list[CandidateRecord]:
        prompt = build_discovery_prompt(
            specialty=specialty,
            question_types=question_types,
            design_scope=design_scope,
            count=count,
            additional_context=additional_context,
        )
        response = self.provider.complete(AIRequest(system=SYSTEM_PROMPT, prompt=prompt))
        proposals = parse_candidate_proposals(response.text)

        records: list[CandidateRecord] = []
        for proposal in proposals:
            candidate_id = stable_candidate_id(project_id, proposal)
            existing = self.ledger.get_candidate(candidate_id)
            if existing is not None and existing.status == CandidateStatus.REJECTED and not allow_rejected_revisit:
                continue

            record = CandidateRecord(
                candidate_id=candidate_id,
                project_id=project_id,
                title=proposal.title,
                specialty=specialty,
                question_type=proposal.question_type,
                review_question=proposal.review_question,
                population=proposal.population,
                intervention_exposure_index_test=proposal.intervention_exposure_index_test,
                comparator_reference=proposal.comparator_reference,
                outcomes=proposal.outcomes,
                eligible_designs=proposal.eligible_designs,
                rationale=proposal.rationale,
                novelty_hypothesis=proposal.novelty_hypothesis,
                search_terms=proposal.search_terms,
                status=existing.status if existing is not None else CandidateStatus.DISCOVERED,
                metadata={
                    **(existing.metadata if existing is not None else {}),
                    "ai_provider": response.provider,
                    "ai_model": response.model,
                    "ai_role": "candidate_generation_only",
                },
                created_at=existing.created_at if existing is not None else utc_now(),
            )
            self.ledger.upsert_candidate(record)
            records.append(record)
        return records


def stable_candidate_id(project_id: str, proposal: CandidateProposal) -> str:
    basis = "|".join([
        project_id.strip().casefold(),
        proposal.title.strip().casefold(),
        proposal.review_question.strip().casefold(),
    ])
    return "CAND-" + hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16].upper()


def _parse_json_object(text: str) -> dict:
    cleaned = text.strip()
    fence = chr(96) * 3
    if cleaned.startswith(fence):
        cleaned = re.sub("^" + re.escape(fence) + r"(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*" + re.escape(fence) + "$", "", cleaned)
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("AI response did not contain a JSON object")
        payload = json.loads(cleaned[start:end + 1])
    if not isinstance(payload, dict):
        raise ValueError("AI response root must be a JSON object")
    return payload
