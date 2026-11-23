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
    normalized_qtypes = [
        str(value).strip()
        for value in question_types
        if str(value).strip() and str(value).strip().upper() != "ALL"
    ]
    normalized_designs = [
        str(value).strip()
        for value in design_scope
        if str(value).strip() and str(value).strip().upper() != "ALL"
    ]
    specialty_scope = (
        "all medical specialties"
        if str(specialty).strip().upper() == "ALL"
        else str(specialty).strip()
    )
    qtypes = ", ".join(normalized_qtypes) or "all appropriate review-question types"
    designs = ", ".join(normalized_designs) or "all appropriate eligible study designs"
    return f"""Generate {int(count)} candidate systematic-review/meta-analysis research questions.

Specialty scope: {specialty_scope}
Question-type scope: {qtypes}
Study-design scope: {designs}
Additional context: {additional_context.strip() or 'None'}

Return strict JSON with this shape:
{{
  "candidates": [
    {{
      "title": "...",
      "specialty": "Specific medical specialty for this topic",
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

Keep every candidate compact. Use one focused clinical question per topic. Limit
rationale and novelty_hypothesis to 20 words each; include 2 to 4 search terms
and at most 3 outcomes and 2 eligible designs per candidate. Avoid
long explanations, markdown or commentary outside JSON.
Prefer a diverse mix of clinically meaningful gaps: recent interventions or
diagnostic generations, underserved populations, head-to-head comparisons,
patient-important outcomes, and feasible updates of older reviews.
Do not assert novelty without a source search. Do not include verified study
counts, source-search results, gate scores, publication score, or final decisions.
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


def _recover_complete_candidate_proposals(text: str) -> list[CandidateProposal]:
    """Salvage only fully valid objects from a truncated candidates array.

    Never repair, guess, or synthesize missing JSON fields. This is used only
    after strict parsing has failed, and preserves the complete earlier objects.
    """
    match = re.search(r'"candidates"\s*:\s*\[', text)
    if match is None:
        return []
    decoder = json.JSONDecoder()
    offset = match.end()
    recovered: list[CandidateProposal] = []
    while True:
        while offset < len(text) and text[offset] in " \r\n\t,":
            offset += 1
        if offset >= len(text) or text[offset] == "]":
            break
        try:
            candidate, offset = decoder.raw_decode(text, offset)
        except json.JSONDecodeError:
            break
        if not isinstance(candidate, dict):
            continue
        # Preserve strict prohibition on AI-provided methodological verdicts.
        recovered.append(CandidateProposal.from_dict(candidate))
    return recovered


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
        # Small JSON batches avoid incomplete output from free reasoning models.
        # Maximum six model calls per job (three regular batches and up to three
        # short retries); no paid models or external JSON-repair service.
        target = max(1, min(50, int(count)))
        proposals_with_response: list[tuple[CandidateProposal, object]] = []
        seen_titles: set[str] = set()
        batch_sizes = [min(4, target - start) for start in range(0, target, 4)]
        # Do not spend unlimited model requests when a batch is malformed.
        max_calls = min(8, len(batch_sizes) + 3)
        calls = 0
        failure_messages: list[str] = []

        for requested in batch_sizes:
            if calls >= max_calls:
                break
            remaining = min(requested, target - len(proposals_with_response))
            if remaining <= 0:
                break
            additional = additional_context
            if seen_titles:
                previous = "; ".join(sorted(seen_titles)[-10:])
                additional = (additional + "\nDo not repeat these prior topic titles: " + previous).strip()
            prompt = build_discovery_prompt(
                specialty=specialty,
                question_types=question_types,
                design_scope=design_scope,
                count=remaining,
                additional_context=additional,
            )
            try:
                calls += 1
                response = self.provider.complete(
                    AIRequest(system=SYSTEM_PROMPT, prompt=prompt, max_tokens=3200)
                )
                try:
                    batch = parse_candidate_proposals(response.text)
                except (ValueError, json.JSONDecodeError) as exc:
                    # Valid, complete candidates preceding a broken tail survive.
                    batch = _recover_complete_candidate_proposals(response.text)
                    failure_messages.append(f"Batch JSON truncated or malformed: {type(exc).__name__}")
                for proposal in batch:
                    key = re.sub(r"[^a-z0-9]+", " ", proposal.title.casefold()).strip()
                    if key in seen_titles:
                        continue
                    seen_titles.add(key)
                    proposals_with_response.append((proposal, response))
                    if len(proposals_with_response) >= target:
                        break
            except (ValueError, RuntimeError) as exc:
                # Providers fail independently. Continue with a smaller request.
                failure_messages.append(f"Batch request failed: {type(exc).__name__}")

        # One short follow-up instead of retrying another long malformed array.
        # When zero candidates were returned, make two small independent attempts.
        while len(proposals_with_response) < target and calls < max_calls:
            remaining = min(2, target - len(proposals_with_response))
            previous = "; ".join(sorted(seen_titles)[-10:])
            prompt = build_discovery_prompt(
                specialty=specialty,
                question_types=question_types,
                design_scope=design_scope,
                count=remaining,
                additional_context=(
                    additional_context
                    + "\nGenerate alternative focused questions; avoid previous titles: "
                    + previous
                ).strip(),
            )
            calls += 1
            try:
                response = self.provider.complete(
                    AIRequest(system=SYSTEM_PROMPT, prompt=prompt, max_tokens=2300)
                )
                try:
                    batch = parse_candidate_proposals(response.text)
                except (ValueError, json.JSONDecodeError):
                    batch = _recover_complete_candidate_proposals(response.text)
                for proposal in batch:
                    key = re.sub(r"[^a-z0-9]+", " ", proposal.title.casefold()).strip()
                    if key in seen_titles:
                        continue
                    seen_titles.add(key)
                    proposals_with_response.append((proposal, response))
                    if len(proposals_with_response) >= target:
                        break
            except (ValueError, RuntimeError) as exc:
                failure_messages.append(f"Short retry failed: {type(exc).__name__}")

        if not proposals_with_response:
            raise RuntimeError(
                f"AI did not return any complete candidate JSON after {calls} bounded requests; "
                + "; ".join(failure_messages[:3])
            )

        records: list[CandidateRecord] = []
        for proposal, response in proposals_with_response:
            candidate_id = stable_candidate_id(project_id, proposal)
            existing = self.ledger.get_candidate(candidate_id)
            if existing is not None and existing.status == CandidateStatus.REJECTED and not allow_rejected_revisit:
                continue

            record = CandidateRecord(
                candidate_id=candidate_id,
                project_id=project_id,
                title=proposal.title,
                specialty=(
                    proposal.specialty
                    if specialty.strip().upper() == "ALL" and proposal.specialty
                    else specialty
                ),
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
        proposal.specialty.strip().casefold(),
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
