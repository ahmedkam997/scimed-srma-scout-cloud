from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from typing import Any

from scimed_scout.evidence import MIN_STUDIES
from scimed_scout.storage import SQLiteLedger
from scimed_scout.synthesis import EvidenceScope, SynthesisDataExtractor, to_outcome_datum
from scimed_scout.usability import UsabilityStatus, assess_outcome


@dataclass(frozen=True, slots=True)
class SynthesisVerificationSummary:
    candidate_id: str
    verified_families_seen: int
    outcomes_extracted: int
    verified_usable_families: int
    conservative_verified_usable_families: int
    principal_outcome_usable_families: int
    potentially_usable_families: int
    definitively_not_usable_families: int
    families_needing_full_text: int
    threshold_met: bool
    synthesis_audit_complete: bool


class SynthesisVerificationBridge:
    def __init__(
        self,
        ledger: SQLiteLedger,
        extractor: SynthesisDataExtractor | None,
        *,
        minimum_outcome_confidence: float = 0.90,
    ):
        self.ledger = ledger
        self.extractor = extractor
        self.minimum_outcome_confidence = minimum_outcome_confidence

    def run(self, candidate_id: str, *, force: bool = False) -> SynthesisVerificationSummary:
        candidate = self.ledger.get_candidate(candidate_id)
        if candidate is None:
            raise ValueError(f"Candidate not found: {candidate_id}")

        families = [
            item for item in self.ledger.list_payloads("study_families", candidate_id)
            if bool(item.get("independence_verified"))
            and bool(item.get("eligibility_verified"))
            and bool(item.get("design_verified"))
        ]
        studies = {
            str(item.get("study_id") or ""): item
            for item in self.ledger.list_payloads("studies", candidate_id)
            if str(item.get("promotion_status") or "") == "VERIFIED_ELIGIBLE"
        }
        external = {
            str(item.get("source_record_id") or ""): item
            for item in self.ledger.list_external_evidence(candidate_id, "PRIMARY_STUDY")
        }

        self.ledger.clear_payloads("outcomes", candidate_id)

        family_statuses: dict[str, set[str]] = {}
        family_definitive_not_usable: dict[str, bool] = {}
        family_has_source: dict[str, bool] = {}
        outcome_count = 0

        for family in families:
            family_id = str(family.get("family_id") or "")
            family_statuses[family_id] = set()
            family_definitive_not_usable[family_id] = False
            family_has_source[family_id] = False

            for study_id in family.get("study_ids") or []:
                study_id = str(study_id)
                study = studies.get(study_id)
                if study is None:
                    continue
                record = external.get(study_id)
                if record is None:
                    continue

                family_has_source[family_id] = True
                scope = _scope(record)
                extraction = self._extract(candidate, study, record, scope=scope, force=force)
                self._persist_study_extraction(candidate_id, study, extraction)

                for index, outcome in enumerate(extraction.outcomes, start=1):
                    outcome_id = _outcome_id(
                        family_id,
                        study_id,
                        outcome.outcome_name,
                        outcome.follow_up,
                        outcome.outcome_type,
                        index,
                    )
                    datum = to_outcome_datum(candidate, outcome_id, outcome)
                    assessment = assess_outcome(datum)
                    final_status, reasons, definitive = self._finalize_status(
                        assessment.status,
                        list(assessment.reasons),
                        outcome,
                        scope,
                    )
                    family_statuses[family_id].add(final_status)
                    if final_status == UsabilityStatus.NOT_USABLE.value and definitive:
                        family_definitive_not_usable[family_id] = True
                    outcome_count += 1

                    payload = {
                        "outcome_id": outcome_id,
                        "family_id": family_id,
                        "study_id": study_id,
                        "outcome_name": datum.outcome_name,
                        "outcome_type": datum.outcome_type.value,
                        "follow_up": datum.follow_up,
                        "principal": datum.principal,
                        "usability_status": final_status,
                        "usability_reasons": reasons,
                        "definitive": definitive,
                        "evidence_scope": scope.value,
                        "overall_confidence": outcome.overall_confidence,
                        "unresolved_fields": list(outcome.unresolved_fields),
                        "extraction": {
                            "data": outcome.data,
                            "signals": outcome.signals,
                            "raw": outcome.raw,
                        },
                        "datum": _datum_payload(datum),
                    }
                    self.ledger.upsert_payload(
                        "outcomes",
                        candidate_id,
                        outcome_id,
                        payload,
                        family_id=family_id,
                    )

        verified_usable_ids = {
            family_id
            for family_id, statuses in family_statuses.items()
            if UsabilityStatus.VERIFIED_USABLE.value in statuses
        }
        potential_ids = {
            family_id
            for family_id, statuses in family_statuses.items()
            if UsabilityStatus.VERIFIED_USABLE.value not in statuses
            and (
                UsabilityStatus.POTENTIALLY_USABLE.value in statuses
                or UsabilityStatus.UNRESOLVED.value in statuses
                or not statuses
            )
        }

        outcomes = self.ledger.list_payloads("outcomes", candidate_id)
        principal_ids = {
            str(item.get("family_id") or "")
            for item in outcomes
            if bool(item.get("principal"))
            and str(item.get("usability_status") or "") == UsabilityStatus.VERIFIED_USABLE.value
        }

        possible_links = list((candidate.metadata or {}).get("family_possible_links_detail") or [])
        study_to_family = {
            str(study_id): str(family.get("family_id") or "")
            for family in families
            for study_id in (family.get("study_ids") or [])
        }
        conservative_usable = _conservative_count(
            verified_usable_ids,
            possible_links,
            study_to_family,
        )
        conservative_principal = _conservative_count(
            principal_ids,
            possible_links,
            study_to_family,
        )

        definitive_not_usable_ids = {
            family_id
            for family_id, definitive in family_definitive_not_usable.items()
            if definitive
            and family_id not in verified_usable_ids
            and not (
                UsabilityStatus.POTENTIALLY_USABLE.value in family_statuses.get(family_id, set())
                or UsabilityStatus.UNRESOLVED.value in family_statuses.get(family_id, set())
            )
        }
        families_needing_full_text = sum(
            1
            for family_id in family_statuses
            if family_id not in verified_usable_ids
            and family_id not in definitive_not_usable_ids
        )
        threshold_met = conservative_usable >= MIN_STUDIES

        # Audit is decisive either when >=4 conservative usable families are
        # established, or when every verified family has a definitive full-text
        # usability conclusion.
        all_families_definitive = all(
            family_id in verified_usable_ids or family_id in definitive_not_usable_ids
            for family_id in family_statuses
        )
        synthesis_audit_complete = threshold_met or all_families_definitive

        metadata = dict(candidate.metadata or {})
        metadata.update({
            "synthesis_audit_complete": synthesis_audit_complete,
            "synthesis_threshold_met": threshold_met,
            "verified_usable_families_raw": len(verified_usable_ids),
            "conservative_verified_usable_studies": conservative_usable,
            "principal_outcome_usable_families": conservative_principal,
            "potentially_usable_families": len(potential_ids),
            "definitively_not_usable_families": len(definitive_not_usable_ids),
            "families_needing_full_text_for_synthesis": families_needing_full_text,
            "synthesis_extraction_is_family_based": True,
        })
        candidate.metadata = metadata
        self.ledger.upsert_candidate(candidate)

        return SynthesisVerificationSummary(
            candidate_id=candidate_id,
            verified_families_seen=len(families),
            outcomes_extracted=outcome_count,
            verified_usable_families=len(verified_usable_ids),
            conservative_verified_usable_families=conservative_usable,
            principal_outcome_usable_families=conservative_principal,
            potentially_usable_families=len(potential_ids),
            definitively_not_usable_families=len(definitive_not_usable_ids),
            families_needing_full_text=families_needing_full_text,
            threshold_met=threshold_met,
            synthesis_audit_complete=synthesis_audit_complete,
        )

    def _extract(self, candidate, study, record, *, scope: EvidenceScope, force: bool):
        cached = study.get("synthesis_extraction")
        current_hash = _source_hash(record)
        if (
            not force
            and isinstance(cached, dict)
            and study.get("synthesis_extraction_input_hash") == current_hash
        ):
            return _from_cached(cached)

        if self.extractor is None:
            return _empty_extraction(
                str(study.get("study_id") or ""),
                str(record.get("source_record_id") or ""),
                scope,
                "Synthesis AI extractor is not configured",
            )

        return self.extractor.extract(
            candidate,
            study,
            record,
            evidence_scope=scope,
        )

    def _persist_study_extraction(self, candidate_id: str, study: dict, extraction) -> None:
        updated = dict(study)
        record_id = str(extraction.source_record_id or "")
        record = next(
            (
                item for item in self.ledger.list_external_evidence(candidate_id, "PRIMARY_STUDY")
                if str(item.get("source_record_id") or "") == record_id
            ),
            None,
        )
        updated["synthesis_extraction"] = {
            "study_id": extraction.study_id,
            "source_record_id": extraction.source_record_id,
            "evidence_scope": extraction.evidence_scope.value,
            "outcomes": [
                {
                    "outcome_name": item.outcome_name,
                    "outcome_type": item.outcome_type,
                    "follow_up": item.follow_up,
                    "data": item.data,
                    "signals": item.signals,
                    "overall_confidence": item.overall_confidence,
                    "unresolved_fields": item.unresolved_fields,
                    "raw": item.raw,
                }
                for item in extraction.outcomes
            ],
            "no_data_reason": extraction.no_data_reason,
            "reviewer": extraction.reviewer,
        }
        if record is not None:
            updated["synthesis_extraction_input_hash"] = _source_hash(record)
        self.ledger.upsert_payload(
            "studies",
            candidate_id,
            str(updated.get("study_id") or ""),
            updated,
            family_id=str(updated.get("family_id") or ""),
        )

    def _finalize_status(self, status, reasons, outcome, scope):
        if outcome.overall_confidence < self.minimum_outcome_confidence or outcome.unresolved_fields:
            return (
                UsabilityStatus.UNRESOLVED.value,
                list(dict.fromkeys(reasons + ["outcome extraction confidence/provenance is insufficient"])),
                False,
            )
        if status == UsabilityStatus.VERIFIED_USABLE:
            return status.value, reasons, True
        if status == UsabilityStatus.POTENTIALLY_USABLE:
            return status.value, reasons, False
        if scope != EvidenceScope.FULL_TEXT:
            return (
                UsabilityStatus.POTENTIALLY_USABLE.value,
                list(dict.fromkeys(reasons + ["available evidence is insufficient to conclude non-usability; full text required"])),
                False,
            )
        return status.value, reasons, status == UsabilityStatus.NOT_USABLE


def _scope(record: dict[str, Any]) -> EvidenceScope:
    payload = record.get("payload") or {}
    if str(payload.get("full_text") or "").strip():
        return EvidenceScope.FULL_TEXT
    if str(payload.get("supplement_text") or "").strip():
        return EvidenceScope.SUPPLEMENT
    return EvidenceScope.TITLE_ABSTRACT


def _source_hash(record: dict[str, Any]) -> str:
    payload = record.get("payload") or {}
    basis = repr((
        record.get("title"),
        record.get("source"),
        payload.get("metadata"),
        payload.get("full_text"),
        payload.get("supplement_text"),
    ))
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


def _outcome_id(family_id, study_id, name, follow_up, outcome_type, index):
    basis = "|".join([
        str(family_id),
        str(study_id),
        str(name).casefold().strip(),
        str(follow_up).casefold().strip(),
        str(outcome_type).upper(),
        str(index),
    ])
    return "OUT-" + hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16].upper()


def _conservative_count(
    family_ids: set[str],
    possible_links: list[dict],
    study_to_family: dict[str, str],
) -> int:
    ids = {x for x in family_ids if x}
    if not ids:
        return 0
    parent = {x: x for x in ids}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for link in possible_links:
        a = study_to_family.get(str(link.get("study_a") or ""))
        b = study_to_family.get(str(link.get("study_b") or ""))
        if a in ids and b in ids and a != b:
            union(a, b)
    return len({find(x) for x in ids})


def _datum_payload(datum) -> dict[str, Any]:
    return asdict(datum)


def _empty_extraction(study_id, source_record_id, scope, reason):
    from scimed_scout.synthesis.models import StudySynthesisExtraction
    return StudySynthesisExtraction(
        study_id=study_id,
        source_record_id=source_record_id,
        evidence_scope=scope,
        outcomes=[],
        no_data_reason=reason,
        reviewer="NOT_CONFIGURED",
    )


def _from_cached(raw: dict[str, Any]):
    from scimed_scout.synthesis.models import ExtractedOutcome, StudySynthesisExtraction
    scope_raw = str(raw.get("evidence_scope") or EvidenceScope.TITLE_ABSTRACT.value)
    try:
        scope = EvidenceScope(scope_raw)
    except ValueError:
        scope = EvidenceScope.TITLE_ABSTRACT
    outcomes = [
        ExtractedOutcome(
            outcome_name=str(item.get("outcome_name") or ""),
            outcome_type=str(item.get("outcome_type") or "OTHER"),
            follow_up=str(item.get("follow_up") or ""),
            data=item.get("data") if isinstance(item.get("data"), dict) else {},
            signals=item.get("signals") if isinstance(item.get("signals"), dict) else {},
            overall_confidence=float(item.get("overall_confidence") or 0.0),
            unresolved_fields=[str(x) for x in item.get("unresolved_fields") or []],
            raw=item.get("raw") if isinstance(item.get("raw"), dict) else {},
        )
        for item in raw.get("outcomes") or []
        if isinstance(item, dict)
    ]
    return StudySynthesisExtraction(
        study_id=str(raw.get("study_id") or ""),
        source_record_id=str(raw.get("source_record_id") or ""),
        evidence_scope=scope,
        outcomes=outcomes,
        no_data_reason=str(raw.get("no_data_reason") or ""),
        reviewer=str(raw.get("reviewer") or "CACHED"),
    )
