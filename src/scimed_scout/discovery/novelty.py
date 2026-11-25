from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any

from scimed_scout.competitors import OverlapLevel, SemanticCompetitorAssessor
from scimed_scout.storage import SQLiteLedger
from .open_access_dates import OpenAccessSearchDateResolver
from .competitor_records import deduplicate, identity, audit as identity_audit, enrich_missing_abstracts


class DiscoveryNoveltyService:
    """Assess competing reviews/registrations without extracting primary-study data.

    Records are deterministically deduplicated and ranked for semantic relevance.
    AI assessment is batched to stay within a zero-cost inference budget.
    """

    def __init__(
        self,
        ledger: SQLiteLedger,
        assessor: SemanticCompetitorAssessor,
        *,
        max_reviews: int = 10,
        max_registrations: int = 6,
        batch_size: int = 3,
        search_date_resolver: OpenAccessSearchDateResolver | None = None,
        max_fulltext_reviews: int = 2,
        enrichment_client=None,
        max_enrichment_lookups: int = 2,
    ):
        self.ledger = ledger
        self.assessor = assessor
        self.max_reviews = max(1, int(max_reviews))
        self.max_registrations = max(1, int(max_registrations))
        self.batch_size = max(1, min(20, int(batch_size)))
        self.search_date_resolver = search_date_resolver
        self.max_fulltext_reviews = max(0, min(4, int(max_fulltext_reviews)))
        self.enrichment_client = enrichment_client
        self.max_enrichment_lookups = max(0,min(4,int(max_enrichment_lookups)))

    def assess_candidate(
        self, candidate_id: str, *, force: bool = False, allow_ai: bool = True,
        recovery: bool = False,
    ) -> dict[str, Any]:
        candidate = self.ledger.get_candidate(candidate_id)
        if candidate is None:
            raise ValueError(f"Candidate not found: {candidate_id}")

        all_reviews = self.ledger.list_external_evidence(candidate_id, "PUBLISHED_REVIEW")
        all_registrations = self.ledger.list_external_evidence(candidate_id, "REGISTRATION")

        # Expand only the best candidate during recovery, not every draft.
        review_cap = min(36, max(self.max_reviews, 30)) if recovery else self.max_reviews
        registry_cap = min(30, max(self.max_registrations, 24)) if recovery else self.max_registrations
        select = _select_incremental if allow_ai else _select_records
        review_records = select(candidate, all_reviews, review_cap, force=force) if allow_ai else select(candidate, all_reviews, review_cap)
        registration_records = select(candidate, all_registrations, registry_cap, force=force) if allow_ai else select(candidate, all_registrations, registry_cap)
        cached_reviews = sum(_valid_cached(candidate,r) for r in review_records) if allow_ai and not force else 0
        cached_registrations = sum(_valid_cached(candidate,r) for r in registration_records) if allow_ai and not force else 0

        enrichment = []
        if allow_ai and self.enrichment_client is not None and self.max_enrichment_lookups:
            enrichment = enrich_missing_abstracts(self.ledger,candidate_id,review_records,
                self.enrichment_client,limit=self.max_enrichment_lookups)
            if any(x["status"]=="ABSTRACT_ENRICHED" for x in enrichment):
                all_reviews=self.ledger.list_external_evidence(candidate_id,"PUBLISHED_REVIEW")
                review_records=select(candidate,all_reviews,review_cap,force=force)
                cached_reviews=sum(_valid_cached(candidate,r) for r in review_records) if not force else 0
        resolved_dates = self._resolve_search_dates(candidate_id, review_records)
        if resolved_dates:
            all_reviews = self.ledger.list_external_evidence(candidate_id, "PUBLISHED_REVIEW")
            review_records = select(candidate, all_reviews, review_cap, force=force) if allow_ai else select(candidate, all_reviews, review_cap)
            cached_reviews = sum(_valid_cached(candidate,r) for r in review_records) if allow_ai and not force else 0
        if allow_ai:
            review_assessments = self._assess_records(candidate, review_records, force=force,
                                                       repair_budget=3 if recovery else 0)
            registration_assessments = self._assess_records(
                candidate, registration_records, force=force,
                repair_budget=2 if recovery else 0,
            )
        else:
            # No amount of AI scoring repairs incomplete mandatory registry
            # searches. Preserve dated competitor evidence but defer expensive
            # semantic inference until source coverage is available.
            review_assessments = [_deferred_competitor(item) for item in review_records]
            registration_assessments = [
                _deferred_competitor(item) for item in registration_records
            ]
        primary_records = self.ledger.list_external_evidence(candidate_id, "PRIMARY_STUDY")
        registration_freshness = [
            registration_age_audit(candidate, record, primary_records)
            for record in registration_records
        ]
        review_freshness = [
            published_review_update_audit(candidate, record, primary_records)
            for record in review_records
        ]
        for item in registration_freshness:
            _attach_publication_linkage(item, all_reviews)

        review_unresolved = sum(bool(item.get("unresolved")) for item in review_assessments)
        registration_unresolved = sum(bool(item.get("unresolved")) for item in registration_assessments)
        # Full bibliographic backlog remains visible and blocks clearance.
        # The first-pass lexical PICO ranking decides only which records are
        # assessed within the free inference budget, never eligibility.
        review_backlog = _unassessed_citation_queue(all_reviews, review_records)
        registration_backlog = _unassessed_citation_queue(
            all_registrations, registration_records,
        )
        # The LLM's "recent review" judgment is not a verified last
        # search date. Avoid automatically rejecting an update opportunity
        # based only on model-supplied recent/adequate fields. Retain the
        # high-overlap items as manual review blockers instead.
        potential_fatal_review_ids = [
            str(item.get("record_id") or "") for item in review_assessments
            if item.get("fatal_redundancy")
        ]
        fatal_redundancy = False
        material_registration_ids = [
            item.get("record_id", "")
            for item in registration_assessments
            if not item.get("unresolved")
            and item.get("overall_overlap") in {
                OverlapLevel.HIGH.value,
                OverlapLevel.ESSENTIALLY_IDENTICAL.value,
            }
        ]

        metadata = dict(candidate.metadata or {})
        metadata.update({
            "discovery_ai_competitor_analysis_deferred": not allow_ai,
            "discovery_competitor_assessment_complete": (
                allow_ai and review_unresolved == 0 and not review_backlog
            ),
            "discovery_registration_assessment_complete": (
                allow_ai and registration_unresolved == 0 and not registration_backlog
            ),
            "discovery_fatal_redundancy": fatal_redundancy,
            "discovery_potential_fatal_review_overlap_ids": potential_fatal_review_ids,
            "discovery_registration_age_audit": registration_freshness,
            "discovery_published_review_update_audit": review_freshness,
            "discovery_fulltext_search_date_resolutions": resolved_dates,
            "discovery_material_registration_overlap_ids": material_registration_ids,
            "discovery_competitor_records_discovered": len(all_reviews),
            "discovery_competitor_records_semantically_assessed": len(review_records),
            "discovery_registration_records_discovered": len(all_registrations),
            "discovery_registration_records_semantically_assessed": len(registration_records),
            "discovery_competitor_identity_audit": identity_audit(all_reviews),
            "discovery_competitor_enrichment": enrichment,
            "discovery_incremental_competitor_budget": {"version":"INCREMENTAL_V1",
                "new_review_limit":review_cap,"new_registration_limit":registry_cap,
                "cached_review_assessments_reused":cached_reviews,
                "cached_registration_assessments_reused":cached_registrations,
                "selected_uncached_reviews":len(review_records)-cached_reviews if allow_ai else 0,
                "selected_uncached_registrations":len(registration_records)-cached_registrations if allow_ai else 0},
            "discovery_unassessed_review_count": len(review_backlog),
            "discovery_unassessed_registration_count": len(registration_backlog),
            "discovery_unassessed_review_queue": review_backlog[:40],
            "discovery_unassessed_registration_queue": registration_backlog[:40],
            "discovery_unassessed_queue_truncated": (
                len(review_backlog) > 40 or len(registration_backlog) > 40
            ),
            "discovery_competitor_resolved_count": (
                len(review_assessments) - review_unresolved
            ),
            "discovery_registration_resolved_count": (
                len(registration_assessments) - registration_unresolved
            ),
            "discovery_semantic_scope_capped": bool(
                review_backlog or registration_backlog
            ),
        })
        candidate.metadata = metadata
        self.ledger.upsert_candidate(candidate)

        return {
            "competitor_identity_audit":metadata["discovery_competitor_identity_audit"],
            "competitor_enrichment":enrichment,
            "incremental_competitor_budget": metadata["discovery_incremental_competitor_budget"],
            "published_reviews_discovered": len(all_reviews),
            "published_reviews_assessed": len(review_assessments),
            "published_reviews_unresolved": review_unresolved,
            "published_reviews_prefiltered_out": len(review_backlog),
            "published_reviews_unassessed_queue": review_backlog[:40],
            "unassessed_queue_truncated": (
                len(review_backlog) > 40 or len(registration_backlog) > 40
            ),
            "registrations_discovered": len(all_registrations),
            "registrations_assessed": len(registration_assessments),
            "registrations_unresolved": registration_unresolved,
            "registrations_prefiltered_out": len(registration_backlog),
            "registrations_unassessed_queue": registration_backlog[:40],
            "fatal_redundancy": fatal_redundancy,
            "potential_fatal_review_overlap_ids": potential_fatal_review_ids,
            "registration_age_audit": registration_freshness,
            "published_review_update_audit": review_freshness,
            "fulltext_search_date_resolutions": resolved_dates,
            "material_registration_overlap_ids": material_registration_ids,
            "summary": _summary(review_assessments, registration_assessments)
                       + "\\n" + _freshness_summary(registration_freshness, review_freshness),
        }

    def _resolve_search_dates(
        self,
        candidate_id: str,
        records: list[dict],
    ) -> list[dict[str, Any]]:
        if self.search_date_resolver is None or self.max_fulltext_reviews == 0:
            return []
        found: list[dict[str, Any]] = []
        attempted = 0
        for record in records:
            meta = _metadata(record)
            if any(meta.get(k) for k in (
                "last_search_date", "date_last_searched", "search_end_date",
                "date_of_last_search", "search_cutoff",
            )):
                continue
            if attempted >= self.max_fulltext_reviews:
                break
            attempted += 1
            evidence = self.search_date_resolver.resolve(record)
            if evidence is None:
                continue
            payload = dict(record.get("payload") or {})
            updated = dict(meta)
            updated["last_search_date"] = evidence["date"]
            updated["search_date_evidence_quote"] = evidence["quote"]
            updated["search_date_evidence_url"] = evidence["source_url"]
            updated["search_date_evidence_level"] = evidence["source_type"]
            payload["metadata"] = updated
            self.ledger.upsert_external_evidence(
                candidate_id, "PUBLISHED_REVIEW", record["source_record_id"],
                source=record.get("source", ""), title=record.get("title", ""),
                payload=payload,
            )
            found.append({
                "source_record_id": record["source_record_id"],
                "title": record.get("title", ""),
                **evidence,
            })
        return found

    def _assess_records(
        self,
        candidate,
        records: list[dict],
        *,
        force: bool,
        repair_budget: int = 0,
    ) -> list[dict[str, Any]]:
        if not records:
            return []

        results_by_id: dict[str, dict[str, Any]] = {}
        pending: list[dict] = []

        for record in records:
            payload = dict(record.get("payload") or {})
            existing = payload.get("discovery_semantic_assessment")
            if not force and _valid_cached(candidate,record):
                results_by_id[_record_identity(record)] = existing
            else:
                pending.append(record)

        for start in range(0, len(pending), self.batch_size):
            batch = pending[start:start + self.batch_size]
            try:
                assessments = self.assessor.assess_many(candidate, batch)
            except Exception as exc:
                # Do not erase successful batches or the registry age audit
                # when a free AI endpoint is throttled or emits broken JSON.
                # These unresolved records cannot satisfy novelty gates.
                assessments = []
                failure_reason = f"AI competitor analysis unavailable: {type(exc).__name__}"
            else:
                failure_reason = ""
            for idx, record in enumerate(batch):
                if idx < len(assessments):
                    serialized = _serialize_assessment(record, assessments[idx])
                else:
                    serialized = {
                        "record_id": record.get("source_record_id", ""),
                        "source": record.get("source", ""),
                        "title": record.get("title", ""),
                        "overall_overlap": OverlapLevel.UNRESOLVED.value,
                        "unresolved": True,
                        "confidence": 0.0,
                        "fatal_redundancy": False,
                        "rationale": failure_reason or "No assessment returned by free AI provider",
                        "dimensions": [],
                    }
                self._persist_assessment(candidate, record, serialized)
                results_by_id[_record_identity(record)] = serialized

        # Retry isolated unresolved records with the full individual prompt.
        # Preserve the prior judgment unless the new evidence-backed response
        # is resolved; a failed retry is never converted to low overlap.
        for record in records:
            if repair_budget <= 0:
                break
            key = _record_identity(record)
            if not results_by_id.get(key, {}).get("unresolved"):
                continue
            repair_budget -= 1
            try:
                assessment = self.assessor.assess(candidate, record)
                if not assessment.unresolved:
                    serialized = _serialize_assessment(record, assessment)
                    self._persist_assessment(candidate, record, serialized)
                    results_by_id[key] = serialized
            except Exception:
                continue

        return [
            results_by_id[_record_identity(record)]
            for record in records
            if _record_identity(record) in results_by_id
        ]

    def _persist_assessment(
        self,
        candidate,
        record: dict,
        serialized: dict[str, Any],
    ) -> None:
        payload = dict(record.get("payload") or {})
        payload["discovery_semantic_assessment"] = serialized
        payload["discovery_semantic_assessment_input_hash"] = _assessment_hash(candidate,record)
        self.ledger.upsert_external_evidence(
            candidate.candidate_id,
            record["evidence_type"],
            record["source_record_id"],
            source=record.get("source", ""),
            title=record.get("title", ""),
            payload=payload,
        )


def _serialize_assessment(record: dict, assessment) -> dict[str, Any]:
    return {
        "record_id": record.get("source_record_id", ""),
        "source": record.get("source", ""),
        "title": record.get("title", ""),
        "overall_overlap": assessment.overall_overlap.value,
        "dimensions": [
            {
                "name": item.name,
                "level": item.level.value,
                "evidence": item.evidence,
                "rationale": item.rationale,
            }
            for item in assessment.dimensions
        ],
        "adequate_review": assessment.adequate_review,
        "recent_review": assessment.recent_review,
        "meaningful_new_information": assessment.meaningful_new_information,
        "confidence": assessment.confidence,
        "rationale": assessment.rationale,
        "reviewer": assessment.reviewer,
        "unresolved": assessment.unresolved,
        "fatal_redundancy": assessment.fatal_redundancy,
    }


def _deferred_competitor(record: dict) -> dict:
    return {
        "record_id": str(record.get("source_record_id") or ""),
        "title": str(record.get("title") or ""),
        "source": str(record.get("source") or ""),
        "overall_overlap": OverlapLevel.UNRESOLVED.value,
        "unresolved": True,
        "confidence": 0.0,
        "fatal_redundancy": False,
        "dimensions": [],
        "rationale": (
            "AI overlap comparison deferred because required source searches "
            "were incomplete. Registration age and linked publications remain "
            "available for independent manual review."
        ),
    }


def _unassessed_citation_queue(all_records: list[dict], selected: list[dict]) -> list[dict]:
    """Trace every unreviewed bibliographic hit without assuming non-overlap.

    The output is a prioritized manual verification queue, not an exclusion
    table. Metadata-only absence of a PICO phrase never clears a competitor.
    """
    checked = {_record_identity(record) for record in selected}
    queue: list[dict] = []
    for record in _dedupe_records(all_records):
        if _record_identity(record) in checked:
            continue
        payload = record.get("payload") or {}
        queue.append({
            "record_id": str(record.get("source_record_id") or ""),
            "title": str(record.get("title") or "")[:300],
            "source": str(record.get("source") or ""),
            "url": str(payload.get("url") or ""),
            "doi": str(payload.get("doi") or ""),
            "year": payload.get("year"),
            "status": "UNASSESSED_BIBLIOGRAPHIC_COMPETITOR",
            "reason": (
                "Outside the free semantic assessment budget. "
                "PICO relevance and review overlap NOT VERIFIED."
            ),
        })
    return queue


def _assessment_hash(candidate, record):
    # Never carry a prior low-overlap judgement to a changed question.
    # Explicit version also invalidates legacy record-only cache keys.
    basis = {
        "version":"COMPETITOR_PICO_CACHE_V1",
        "record_hash":_record_hash(record),
        "evidence_type":record.get("evidence_type"),
        "record_id":record.get("source_record_id"),
        "pico":[candidate.title,candidate.population,candidate.intervention_exposure_index_test,
                candidate.comparator_reference,list(candidate.outcomes or []),
                list(candidate.eligible_designs or []),candidate.question_type,candidate.review_question],
    }
    return hashlib.sha256(json.dumps(basis,sort_keys=True,ensure_ascii=False,default=str).encode()).hexdigest()


def _valid_cached(candidate,record):
    payload=record.get("payload") or {}
    existing=payload.get("discovery_semantic_assessment")
    return (isinstance(existing,dict) and existing.get("unresolved") is False
            and payload.get("discovery_semantic_assessment_input_hash")==_assessment_hash(candidate,record))


def _attempted_current(candidate,record):
    payload=record.get("payload") or {}
    return (isinstance(payload.get("discovery_semantic_assessment"),dict)
            and payload.get("discovery_semantic_assessment_input_hash")==_assessment_hash(candidate,record))


def _select_incremental(candidate,records,limit,*,force=False):
    # Keep all valid saved decisions in the audit. Budget only new work.
    # Fresh/unseen citations precede previously unresolved citations so a
    # pathological record cannot indefinitely starve the tail of the queue.
    ranked=_select_records(candidate,records,len(records))
    if force:
        return ranked[:limit]
    cached=[r for r in ranked if _valid_cached(candidate,r)]
    outstanding=[r for r in ranked if not _valid_cached(candidate,r)]
    fresh=[r for r in outstanding if not _attempted_current(candidate,r)]
    retry=[r for r in outstanding if _attempted_current(candidate,r)]
    return cached+(fresh+retry)[:limit]


def _select_records(candidate, records: list[dict], limit: int) -> list[dict]:
    unique = _dedupe_records(records)
    # Prioritize explicit intervention and comparator concepts over shared
    # generic disease words. This ranks what the limited LLM budget sees
    # first, but never automatically excludes any remaining competitor.
    priority_stop = {
        "intervention", "interventions", "supplementation", "supplement",
        "treatment", "treatments", "therapy", "therapies", "effect",
        "effects", "efficacy", "clinical", "use", "using", "dose",
        "doses", "oral", "patients", "placebo", "control",
    }
    concepts = [
        (0.55, _tokens(candidate.intervention_exposure_index_test) - priority_stop),
        (0.18, _tokens(candidate.population) - priority_stop),
        (0.12, _tokens(candidate.comparator_reference) - priority_stop),
        (0.10, _tokens(" ".join(str(x) for x in (candidate.outcomes or []))) - priority_stop),
        (0.05, _tokens(candidate.title) - priority_stop),
    ]
    current_year = datetime.now(timezone.utc).year

    scored: list[tuple[float, int, dict]] = []
    for index, record in enumerate(unique):
        record_text = _record_text(record)
        record_tokens = _tokens(record_text)
        weighted_overlap = sum(
            weight * len(tokens & record_tokens) / len(tokens)
            for weight, tokens in concepts if tokens
        )
        year = _record_year(record)
        recency = (
            0.10 if year is not None and year >= current_year - 5
            else 0.03 if year is not None and year >= current_year - 10
            else 0.0
        )
        evidence_bonus = min(0.04, len(record_text) / 50000.0)
        scored.append((weighted_overlap + recency + evidence_bonus, -index, record))

    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [record for _, _, record in scored[:limit]]


def _dedupe_records(records: list[dict]) -> list[dict]:
    return deduplicate(records)


def _record_identity(record: dict):
    return identity(record)


def _primary_bibliographic_key(record: dict) -> str:
    # Keep the existing primary-publication freshness heuristic separate from
    # competitor identity. Neither key establishes trial independence.
    payload = record.get("payload") or {}
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    doi = str(payload.get("doi") or metadata.get("doi") or _external_doi(metadata) or "").strip().casefold()
    doi = doi.removeprefix("https://doi.org/").removeprefix("http://doi.org/")
    if doi:
        return "doi:" + doi.rstrip(".")
    title = " ".join(re.sub(r"[^a-z0-9]+", " ", str(record.get("title") or "").casefold()).split())
    if title:
        return "title:" + title
    return "id:" + str(record.get("source") or "") + ":" + str(record.get("source_record_id") or "")


def _record_text(record: dict) -> str:
    payload = record.get("payload") or {}
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    parts = [
        record.get("title"),
        metadata.get("abstract"),
        metadata.get("abstractText"),
        metadata.get("summary"),
        metadata.get("description"),
        metadata.get("brief_summary"),
        payload.get("abstract"),
        payload.get("summary"),
    ]
    return " ".join(str(x).strip() for x in parts if x and str(x).strip())


def _record_year(record: dict) -> int | None:
    payload = record.get("payload") or {}
    value = payload.get("year")
    if isinstance(value, int):
        return value
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _external_doi(metadata: dict) -> str:
    external = metadata.get("externalIds")
    if isinstance(external, dict):
        return str(external.get("DOI") or external.get("doi") or "")
    article_ids = metadata.get("articleids") or metadata.get("articleIds")
    if isinstance(article_ids, list):
        for item in article_ids:
            if not isinstance(item, dict):
                continue
            if str(item.get("idtype") or item.get("idType") or "").casefold() == "doi":
                return str(item.get("value") or item.get("id") or "")
    return ""


def _tokens(text: str) -> set[str]:
    stop = {
        "the", "and", "for", "with", "from", "into", "among", "after", "before",
        "systematic", "review", "meta", "analysis", "study", "studies", "patients",
        "adults", "effect", "effects", "outcome", "outcomes",
    }
    return {
        token
        for token in re.findall(r"[a-z0-9]{3,}", str(text or "").casefold())
        if token not in stop
    }


def _record_hash(record: dict[str, Any]) -> str:
    payload = record.get("payload") or {}
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    basis = json.dumps([record.get("source"),record.get("title"),payload.get("year"),
        payload.get("doi"),metadata,payload.get("abstract"),payload.get("summary")],
        sort_keys=True,ensure_ascii=False,default=str)
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


def _summary(reviews: list[dict], registrations: list[dict]) -> str:
    rows = []
    for kind, items in (("published review", reviews), ("registration", registrations)):
        for item in items:
            rows.append(
                f"{kind}: {item.get('title', '')} | overlap={item.get('overall_overlap', 'UNRESOLVED')} "
                f"| unresolved={bool(item.get('unresolved'))} | fatal={bool(item.get('fatal_redundancy'))}"
            )
    return "\n".join(rows[:30])


def _date_from_metadata(metadata: dict, keys: tuple[str, ...]) -> tuple[int | None, str]:
    """Only use an explicit date field. Publication year is never search date."""
    for key in keys:
        value = metadata.get(key)
        if isinstance(value, dict):
            value = value.get("@value") or value.get("value")
        if isinstance(value, list):
            value = value[0] if value else None
        if isinstance(value, dict):
            value = value.get("@value") or value.get("value")
        match = re.match(r"^((?:19|20)\d{2})(?:-[01]\d(?:-[0-3]\d)?)?", str(value or "").strip())
        if match:
            year = int(match.group(1))
            if year <= datetime.now(timezone.utc).year:
                return year, str(value).strip()[:32]
    return None, ""


def _bibliographic_leads_after(candidate, records: list[dict], baseline_year: int | None) -> dict:
    """Count only potentially PICO-related dated citations, not eligible trials."""
    if baseline_year is None:
        return {"count": None, "examples": [], "eligible_studies_confirmed": 0}
    intervention = {
        t for t in _tokens(candidate.intervention_exposure_index_test)
        if not t.isdigit() and len(t) > 2
    }
    found: dict[str, dict] = {}
    for item in records:
        payload = item.get("payload") or {}
        year = _year_value(payload.get("year"))
        if year is None or year <= baseline_year or not intervention:
            continue
        title = str(item.get("title") or "").strip()
        tokens = _tokens(title)
        if not tokens or len(tokens & intervention) / len(intervention) < 0.5:
            continue
        ident = _primary_bibliographic_key(item)
        if ident not in found:
            found[ident] = {
                "title": title, "year": year, "source": item.get("source", ""),
                "url": str(payload.get("url") or ""),
            }
    examples = sorted(found.values(), key=lambda item: (-item["year"], item["title"]))[:4]
    return {
        "count": len(found),
        "examples": examples,
        "eligible_studies_confirmed": 0,
    }


def _year_value(value) -> int | None:
    try:
        result = int(value)
        return result if 1900 <= result <= datetime.now(timezone.utc).year else None
    except (ValueError, TypeError):
        return None


def _metadata(record: dict) -> dict:
    payload = record.get("payload") or {}
    raw = payload.get("metadata") or {}
    return raw if isinstance(raw, dict) else {}


_GENERIC_INTERVENTION_TERMS = {
    "supplement", "supplements", "supplementation", "administration",
    "intervention", "interventions", "treatment", "treatments",
    "therapy", "therapies", "clinical", "efficacy", "safety",
    "inhibitor", "inhibitors", "agonist", "agonists", "receptor", "receptors",
    "standard", "care", "comparison", "compared", "placebo",
    "cardiac", "cardiovascular", "patients", "disease", "diseases",
    "management", "high", "low", "dose", "doses", "intensity",
    "use", "oral", "adjunctive", "versus", "physical", "during",
    "response", "drug", "drugs", "medication", "medications", "routine",
}


def registration_pico_preflight(candidate, record: dict) -> dict:
    """Keyword-only prioritization, never full PICO equivalence or exclusion.

    Broad registry queries produce unrelated protocols with generic terms
    such as 'supplementation'. Keep those hits in the raw source ledger while
    preventing their registration age from implying an update opportunity.
    """
    intervention = str(candidate.intervention_exposure_index_test or "")
    anchors = sorted(
        term for term in _tokens(intervention)
        if term not in _GENERIC_INTERVENTION_TERMS and not term.isdigit()
    )
    if not anchors:
        label = "UNKNOWN_INTERVENTION_TERMS"
        overlap = []
    else:
        evidence = _record_text(record)
        if not evidence:
            label = "UNKNOWN_REGISTRY_TEXT"
            overlap = []
        else:
            overlap = sorted(set(anchors) & _tokens(evidence))
            label = (
                "POTENTIAL_INTERVENTION_MATCH"
                if overlap else "BROAD_SEARCH_HIT_NO_INTERVENTION_MATCH"
            )
    return {
        "status": label,
        "intervention_terms": anchors,
        "matched_intervention_terms": overlap,
        "method": "KEYWORD_PREFLIGHT_ONLY_NOT_FULL_PICO_OVERLAP",
        "scientific_exclusion_confirmed": False,
    }


def registration_age_audit(candidate, record: dict, primary_records: list[dict]) -> dict:
    """Registration age and progress are indicators, never novelty clearance.

    A PROSPERO/OSF registration is not evidence of a published systematic
    review. Publication linkage and latest literature search date need checking.
    """
    meta = _metadata(record)
    payload = record.get("payload") or {}
    source = str(record.get("source") or "")
    if source == "PROSPERO":
        date_keys = ("date_first_published", "year_first_published", "date_registered", "dateRegistered")
    else:
        date_keys = ("date_registered", "dateRegistered", "dateCreated", "datePublished")
    year, registered_at = _date_from_metadata(meta, date_keys)
    if year is None:
        year = _year_value(payload.get("year"))
        if year is not None:
            registered_at = str(year)
    _, modified_at = _date_from_metadata(meta, ("date_modified", "dateModified", "last_updated"))
    status = str(
        meta.get("review_status") or meta.get("registry_status")
        or meta.get("reviewstatus") or "UNKNOWN"
    ).strip()[:64]
    withdrawn = str(meta.get("withdrawn") or "").casefold() in ("true", "1", "yes")
    topic_match = registration_pico_preflight(candidate, record)
    # An unrelated registry result is still saved for auditing, but its age
    # must not trigger misleading "new evidence since registration" counts.
    if topic_match["status"] == "BROAD_SEARCH_HIT_NO_INTERVENTION_MATCH":
        leads = {
            "count": None, "examples": [],
            "eligible_studies_confirmed": 0,
            "scope_note": "NOT_ESTIMABLE_FOR_UNMATCHED_REGISTRY_TOPIC",
        }
    else:
        leads = _bibliographic_leads_after(candidate, primary_records, year)
    age = datetime.now(timezone.utc).year - year if year is not None else None
    modified_year = _year_value(modified_at[:4]) if modified_at else None
    recent_metadata_activity = (
        modified_year is not None
        and modified_year >= datetime.now(timezone.utc).year - 1
    )
    if withdrawn:
        classification = "WITHDRAWN_REGISTRATION_VERIFY_PUBLICATION"
    elif age is None:
        classification = "UNKNOWN_DATE_MANUAL_REVIEW"
    elif age >= 3 and recent_metadata_activity:
        classification = "OLD_REGISTRATION_WITH_RECENT_METADATA_ACTIVITY"
    elif age >= 3 and any(marker in status.casefold() for marker in (
        "completed", "published", "finished",
    )):
        classification = "OLDER_COMPLETED_REGISTRATION_CHECK_PUBLISHED_REVIEW"
    elif age >= 3:
        classification = "OLDER_REGISTRATION_UPDATE_OPPORTUNITY_TO_VERIFY"
    else:
        classification = "RECENT_REGISTRATION_REVIEW_COMPETITION"
    return {
        "source": source,
        "record_id": str(record.get("source_record_id") or ""),
        "title": str(record.get("title") or ""),
        "url": str(payload.get("url") or ""),
        "registered_at": registered_at or None,
        "registry_metadata_modified_at": modified_at or None,
        "age_years_approx": age,
        "registry_status": status,
        "pico_relevance_preflight": topic_match,
        "withdrawn": withdrawn,
        "recent_metadata_activity": recent_metadata_activity,
        "classification": classification,
        "post_registration_bibliographic_leads": leads,
        "publication_status": "NOT_VERIFIED",
        "review_last_search_date": "NOT_VERIFIED",
        "novelty_confirmed": False,
        "next_action": (
            "Check full registration progress, published follow-up review, last search date, "
            "and eligibility of newer primary studies before deciding if an update is justified."
        ),
    }


def published_review_update_audit(candidate, record: dict, primary_records: list[dict]) -> dict:
    """A review's publication date must not be mistaken for its search cutoff."""
    meta = _metadata(record)
    year, cutoff = _date_from_metadata(meta, (
        "last_search_date", "date_last_searched", "search_end_date",
        "date_of_last_search", "search_cutoff",
    ))
    leads = _bibliographic_leads_after(candidate, primary_records, year)
    pub_year = _year_value((record.get("payload") or {}).get("year"))
    post_publication_leads = _bibliographic_leads_after(candidate, primary_records, pub_year)
    review_age = datetime.now(timezone.utc).year - pub_year if pub_year else None
    if year is not None and leads["count"] and leads["count"] > 0:
        classification = "POTENTIAL_UPDATE_VERIFY_NEW_STUDY_ELIGIBILITY"
    elif year is None and review_age is not None and review_age >= 3 and post_publication_leads["count"]:
        classification = "OLD_REVIEW_POTENTIAL_UPDATE_SEARCH_DATE_UNVERIFIED"
    elif year is None:
        classification = "SEARCH_DATE_MISSING_MANUAL_CHECK"
    else:
        classification = "NO_POST_SEARCH_TITLE_LEADS_FOUND_IN_SCOUT"
    return {
        "source": str(record.get("source") or ""),
        "record_id": str(record.get("source_record_id") or ""),
        "title": str(record.get("title") or ""),
        "publication_year": pub_year,
        "publication_age_years_approx": review_age,
        "last_search_date": cutoff or None,
        "search_date_evidence_quote": str(meta.get("search_date_evidence_quote") or "")[:230],
        "search_date_evidence_url": str(meta.get("search_date_evidence_url") or ""),
        "search_date_evidence_level": str(meta.get("search_date_evidence_level") or (
            "STRUCTURED_RECORD_DATE_FIELD" if cutoff else "NOT_FOUND"
        )),
        "classification": classification,
        "post_cutoff_bibliographic_leads": leads,
        "post_publication_bibliographic_leads": post_publication_leads,
        "novelty_confirmed": False,
        "next_action": (
            "Confirm the original review's actual literature-search cutoff, "
            "screen newer independent primary studies, and judge whether updating changes evidence."
        ),
    }


def _freshness_summary(registrations: list[dict], reviews: list[dict]) -> str:
    lines = []
    for item in registrations[:5]:
        leads = item.get("post_registration_bibliographic_leads") or {}
        lines.append(
            f"Registration {item['source']} {item['record_id']}: "
            f"{item['classification']}; registered={item['registered_at']}; "
            f"status={item['registry_status']}; newer bibliographic leads={leads.get('count')}. "
            "Not a verified publication or novelty clearance."
        )
    for item in reviews[:5]:
        lines.append(
            f"Published review {item['record_id']}: {item['classification']}; "
            f"last_search_date={item['last_search_date']}. "
            "Publication date does not establish last search date."
        )
    return "\n".join(lines)


def _attach_publication_linkage(registration: dict, published_records: list[dict]) -> None:
    """Link a registry entry to bibliographic records only by exact ID or URL.

    Similar titles are insufficient to assert publication, because unrelated
    review teams routinely register near-identical questions. These references
    still need a source-level manuscript/publication check.
    """
    rid = str(registration.get("record_id") or "").strip()
    source = str(registration.get("source") or "")
    if not rid or not published_records:
        return
    matches: list[dict] = []
    if source == "PROSPERO" and re.fullmatch(r"CRD\d{8,}", rid, flags=re.IGNORECASE):
        pattern = re.compile(r"(?<![A-Z0-9])" + re.escape(rid) + r"(?![A-Z0-9])", re.IGNORECASE)
    elif source == "OSF Registries" and re.fullmatch(r"[a-z0-9]{4,12}", rid, flags=re.IGNORECASE):
        pattern = re.compile(r"(?:https?://)?(?:www\.)?osf\.io/" + re.escape(rid) + r"(?:/|\b)", re.IGNORECASE)
    else:
        return
    for review in _dedupe_records(published_records):
        title = str(review.get("title") or "")
        title_norm = title.casefold()
        if not any(term in title_norm for term in (
            "systematic review", "meta-analysis", "meta analysis", "scoping review",
        )):
            continue
        meta = _metadata(review)
        payload = review.get("payload") or {}
        blob = " ".join([
            _record_text(review),
            str(meta.get("prospero_id") or ""),
            str(meta.get("registration") or ""),
            str(meta.get("registration_number") or ""),
        ])
        if not pattern.search(blob):
            continue
        matches.append({
            "title": title,
            "source": str(review.get("source") or ""),
            "year": _year_value(payload.get("year")),
            "doi": str(payload.get("doi") or ""),
            "url": str(payload.get("url") or ""),
            "linkage_evidence": "Exact public registration identifier in bibliographic review text",
            "full_text_linkage_verified": False,
        })
    if matches:
        registration["publication_status"] = "PUBLICATION_CANDIDATE_LINKED_BY_REGISTRY_ID"
        registration["linked_publication_candidates"] = matches[:3]
        registration["next_action"] = (
            "A published-review bibliographic record mentions this exact registration ID. "
            "Verify the linked article and its actual last literature search, then screen "
            "newer eligible studies before planning an update."
        )
