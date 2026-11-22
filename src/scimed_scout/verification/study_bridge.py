from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any

from scimed_scout.evidence import MIN_STUDIES
from scimed_scout.studies import EvidenceFamilyResolver, StudyRecord
from scimed_scout.studies.classifier import classify_design
from scimed_scout.storage import SQLiteLedger


class PromotionStatus(StrEnum):
    VERIFIED_ELIGIBLE = "VERIFIED_ELIGIBLE"
    VERIFIED_INELIGIBLE = "VERIFIED_INELIGIBLE"
    NEEDS_REVIEW = "NEEDS_REVIEW"


@dataclass(frozen=True, slots=True)
class StudyPromotion:
    study_id: str
    status: PromotionStatus
    reasons: tuple[str, ...]
    design_label: str = ""


@dataclass(frozen=True, slots=True)
class StudyVerificationSummary:
    candidate_id: str
    records_seen: int
    verified_eligible: int
    verified_ineligible: int
    needs_review: int
    deterministic_families: int
    conservative_independent_count: int
    possible_family_links: int
    decision_changing_family_uncertainty: bool
    study_audit_complete: bool


class StudyVerificationBridge:
    def __init__(
        self,
        ledger: SQLiteLedger,
        *,
        minimum_overall_confidence: float = 0.90,
        minimum_field_confidence: float = 0.85,
    ):
        self.ledger = ledger
        self.minimum_overall_confidence = minimum_overall_confidence
        self.minimum_field_confidence = minimum_field_confidence
        self.resolver = EvidenceFamilyResolver()

    def run(self, candidate_id: str) -> StudyVerificationSummary:
        candidate = self.ledger.get_candidate(candidate_id)
        if candidate is None:
            raise ValueError(f"Candidate not found: {candidate_id}")

        stored = self.ledger.list_payloads("studies", candidate_id)
        stored_by_id = {str(x.get("study_id") or ""): dict(x) for x in stored}
        promotions: list[StudyPromotion] = []
        eligible_records: list[StudyRecord] = []

        for payload in stored:
            promotion, record = self._promote(candidate, payload)
            promotions.append(promotion)
            payload = dict(payload)
            payload["promotion_status"] = promotion.status.value
            payload["promotion_reasons"] = list(promotion.reasons)
            payload["verification_status"] = promotion.status.value
            payload["eligibility_verified"] = promotion.status in {
                PromotionStatus.VERIFIED_ELIGIBLE,
                PromotionStatus.VERIFIED_INELIGIBLE,
            }
            payload["eligible_for_review"] = promotion.status == PromotionStatus.VERIFIED_ELIGIBLE
            payload["design_verified"] = bool(record and record.design.design_verified)
            payload["independence_verified"] = False
            study_id = str(payload.get("study_id") or "")
            stored_by_id[study_id] = dict(payload)
            self.ledger.upsert_payload("studies", candidate_id, study_id, payload)
            if record is not None and promotion.status == PromotionStatus.VERIFIED_ELIGIBLE:
                eligible_records.append(record)

        overrides = dict((candidate.metadata or {}).get("family_link_overrides") or {})
        self._apply_same_family_overrides(eligible_records, overrides)
        audit = self.resolver.audit(eligible_records)
        audit.possible_links = [
            link for link in audit.possible_links
            if _pair_override(overrides, link.study_a, link.study_b) != "DISTINCT_FAMILIES"
        ]

        self.ledger.clear_payloads("study_families", candidate_id)
        possible_by_study: dict[str, list[dict[str, Any]]] = {}
        for link in audit.possible_links:
            item = {
                "study_a": link.study_a,
                "study_b": link.study_b,
                "status": link.status.value,
                "reasons": list(link.reasons),
            }
            possible_by_study.setdefault(link.study_a, []).append(item)
            possible_by_study.setdefault(link.study_b, []).append(item)

        raw_verified = 0
        for family in audit.families:
            members = [x for x in eligible_records if x.study_id in family.study_ids]
            eligibility_verified = any(x.eligibility_verified for x in members)
            design_verified = any(x.design.design_verified for x in members)
            family.independence_verified = eligibility_verified and design_verified
            family.eligibility_verified = eligibility_verified
            family.design_verified = design_verified
            if family.verified_for_counting:
                raw_verified += 1

            family_payload = {
                "family_id": family.family_id,
                "study_ids": list(family.study_ids),
                "registry_ids": list(family.registry_ids),
                "independence_verified": family.independence_verified,
                "eligibility_verified": family.eligibility_verified,
                "design_verified": family.design_verified,
                "verification_status": "FAMILY_AUDITED",
                "possible_links": [
                    link for study_id in family.study_ids for link in possible_by_study.get(study_id, [])
                ],
            }
            self.ledger.upsert_payload("study_families", candidate_id, family.family_id, family_payload)

            for study_id in family.study_ids:
                study_payload = stored_by_id.get(study_id)
                if study_payload is None:
                    continue
                updated = dict(study_payload)
                updated["family_id"] = family.family_id
                updated["promotion_status"] = PromotionStatus.VERIFIED_ELIGIBLE.value
                updated["eligibility_verified"] = True
                updated["design_verified"] = True
                updated["independence_verified"] = True
                updated["family_possible_links"] = possible_by_study.get(study_id, [])
                self.ledger.upsert_payload("studies", candidate_id, study_id, updated, family_id=family.family_id)

        conservative_count = audit.minimum_possible_verified_independent_count()
        decision_changing = audit.family_uncertainty_is_decision_changing(MIN_STUDIES)
        needs_review = sum(x.status == PromotionStatus.NEEDS_REVIEW for x in promotions)
        verified_eligible = sum(x.status == PromotionStatus.VERIFIED_ELIGIBLE for x in promotions)
        verified_ineligible = sum(x.status == PromotionStatus.VERIFIED_INELIGIBLE for x in promotions)

        study_audit_complete = needs_review == 0 and not decision_changing
        metadata = dict(candidate.metadata or {})
        metadata.update({
            "study_verification_bridge_complete": needs_review == 0,
            "study_audit_complete": study_audit_complete,
            "verified_eligible_publications": verified_eligible,
            "verified_ineligible_publications": verified_ineligible,
            "study_records_needing_review": needs_review,
            "deterministic_family_count": len(audit.families),
            "raw_verified_family_count": raw_verified,
            "conservative_verified_independent_studies": conservative_count,
            "possible_family_links": len(audit.possible_links),
            "family_uncertainty_decision_changing": decision_changing,
            "family_possible_links_detail": [
                {
                    "study_a": link.study_a,
                    "study_b": link.study_b,
                    "status": link.status.value,
                    "reasons": list(link.reasons),
                }
                for link in audit.possible_links
            ],
        })
        candidate.metadata = metadata
        self.ledger.upsert_candidate(candidate)

        return StudyVerificationSummary(
            candidate_id=candidate_id,
            records_seen=len(stored),
            verified_eligible=verified_eligible,
            verified_ineligible=verified_ineligible,
            needs_review=needs_review,
            deterministic_families=len(audit.families),
            conservative_independent_count=conservative_count,
            possible_family_links=len(audit.possible_links),
            decision_changing_family_uncertainty=decision_changing,
            study_audit_complete=study_audit_complete,
        )

    def set_manual_study_verification(
        self,
        candidate_id: str,
        study_id: str,
        *,
        eligible: bool,
        design_label: str = "",
        reason: str = "",
    ) -> StudyVerificationSummary:
        payloads = self.ledger.list_payloads("studies", candidate_id)
        target = next((x for x in payloads if str(x.get("study_id") or "") == study_id), None)
        if target is None:
            raise ValueError(f"Study not found: {study_id}")
        updated = dict(target)
        updated["manual_verification"] = {
            "eligibility": "ELIGIBLE" if eligible else "INELIGIBLE",
            "design_label": design_label.strip(),
            "reason": reason.strip(),
            "verified_at": datetime.now(timezone.utc).isoformat(),
            "verified_by": "MANUAL",
        }
        self.ledger.upsert_payload(
            "studies",
            candidate_id,
            study_id,
            updated,
            family_id=str(updated.get("family_id") or ""),
        )
        return self.run(candidate_id)

    def set_family_link_override(
        self,
        candidate_id: str,
        study_a: str,
        study_b: str,
        *,
        resolution: str,
        reason: str = "",
    ) -> StudyVerificationSummary:
        value = resolution.strip().upper()
        if value not in {"SAME_FAMILY", "DISTINCT_FAMILIES"}:
            raise ValueError("resolution must be SAME_FAMILY or DISTINCT_FAMILIES")
        candidate = self.ledger.get_candidate(candidate_id)
        if candidate is None:
            raise ValueError(f"Candidate not found: {candidate_id}")
        if study_a == study_b:
            raise ValueError("study_a and study_b must be different")
        known_ids = {str(x.get("study_id") or "") for x in self.ledger.list_payloads("studies", candidate_id)}
        missing = [study_id for study_id in (study_a, study_b) if study_id not in known_ids]
        if missing:
            raise ValueError("Study not found: " + ", ".join(missing))
        metadata = dict(candidate.metadata or {})
        overrides = dict(metadata.get("family_link_overrides") or {})
        overrides[_pair_key(study_a, study_b)] = {
            "resolution": value,
            "reason": reason.strip(),
            "verified_at": datetime.now(timezone.utc).isoformat(),
            "verified_by": "MANUAL",
        }
        metadata["family_link_overrides"] = overrides
        candidate.metadata = metadata
        self.ledger.upsert_candidate(candidate)
        return self.run(candidate_id)

    def _apply_same_family_overrides(self, records: list[StudyRecord], overrides: dict[str, Any]) -> None:
        ids = {record.study_id for record in records}
        parent = {study_id: study_id for study_id in ids}

        def find(x: str) -> str:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a: str, b: str) -> None:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[rb] = ra

        for key, raw in overrides.items():
            if not isinstance(raw, dict) or str(raw.get("resolution") or "").upper() != "SAME_FAMILY":
                continue
            parts = key.split("||", 1)
            if len(parts) == 2 and parts[0] in ids and parts[1] in ids:
                union(parts[0], parts[1])

        groups: dict[str, list[str]] = {}
        for study_id in ids:
            groups.setdefault(find(study_id), []).append(study_id)
        by_id = {record.study_id: record for record in records}
        for members in groups.values():
            if len(members) < 2:
                continue
            manual_id = "MANUAL-" + hashlib.sha256("|".join(sorted(members)).encode("utf-8")).hexdigest()[:12].upper()
            for study_id in members:
                by_id[study_id].manually_verified_family_id = manual_id

    def _promote(self, candidate, payload: dict[str, Any]) -> tuple[StudyPromotion, StudyRecord | None]:
        extraction = payload.get("extraction") or {}
        manual = payload.get("manual_verification") if isinstance(payload.get("manual_verification"), dict) else None
        eligibility = str(extraction.get("eligibility") or payload.get("eligibility_status") or "").upper()
        confidence = _float(extraction.get("overall_confidence"))
        unresolved = {str(x) for x in extraction.get("unresolved_fields") or []}
        fields = extraction.get("raw", {}).get("fields") if isinstance(extraction.get("raw"), dict) else None
        if not isinstance(fields, dict):
            fields = _fields_from_serialized_extraction(extraction)

        if manual is not None:
            manual_eligibility = str(manual.get("eligibility") or "").upper()
            if manual_eligibility == "INELIGIBLE":
                return (
                    StudyPromotion(
                        str(payload.get("study_id") or ""),
                        PromotionStatus.VERIFIED_INELIGIBLE,
                        (str(manual.get("reason") or "manual exclusion"),),
                    ),
                    None,
                )
            if manual_eligibility == "ELIGIBLE":
                design_label = str(manual.get("design_label") or _field_value(fields, "design_label") or "").strip()
                if not design_label:
                    return (
                        StudyPromotion(
                            str(payload.get("study_id") or ""),
                            PromotionStatus.NEEDS_REVIEW,
                            ("manual eligibility supplied but study design is still missing",),
                        ),
                        None,
                    )
                profile = classify_design(candidate.question_type, design_label)
                profile.design_verified = True
                record = self._record_from_fields(payload, fields, profile, notes="Manually verified eligibility/design")
                return (
                    StudyPromotion(
                        record.study_id,
                        PromotionStatus.VERIFIED_ELIGIBLE,
                        (str(manual.get("reason") or "manual eligibility/design verification"),),
                        profile.effective_design_label,
                    ),
                    record,
                )

        if (
            eligibility == "INELIGIBLE"
            and confidence >= self.minimum_overall_confidence
            and str(extraction.get("exclusion_reason") or "").strip()
            and str(extraction.get("exclusion_evidence") or "").strip()
            and "exclusion_evidence" not in unresolved
        ):
            reason = str(extraction.get("exclusion_reason") or "High-confidence source-supported exclusion")
            return StudyPromotion(str(payload.get("study_id") or ""), PromotionStatus.VERIFIED_INELIGIBLE, (reason,)), None

        reasons: list[str] = []
        if eligibility != "ELIGIBLE":
            reasons.append(f"eligibility is {eligibility or 'missing'}")
        if confidence < self.minimum_overall_confidence:
            reasons.append(f"overall confidence {confidence:.2f} below {self.minimum_overall_confidence:.2f}")

        critical = ["design_label", "population"]
        if candidate.intervention_exposure_index_test.strip():
            critical.append("intervention_exposure_index_test")
        if candidate.comparator_reference.strip():
            critical.append("comparator_reference")

        for name in critical:
            field = fields.get(name) if isinstance(fields, dict) else None
            value = field.get("value") if isinstance(field, dict) else None
            evidence = str(field.get("evidence") or "").strip() if isinstance(field, dict) else ""
            field_confidence = _float(field.get("confidence")) if isinstance(field, dict) else 0.0
            if value in (None, "", []):
                reasons.append(f"{name} missing")
            if not evidence:
                reasons.append(f"{name} lacks source provenance")
            if field_confidence < self.minimum_field_confidence:
                reasons.append(f"{name} confidence {field_confidence:.2f} below {self.minimum_field_confidence:.2f}")
            if name in unresolved:
                reasons.append(f"{name} unresolved")

        design_label = _field_value(fields, "design_label")
        profile = classify_design(candidate.question_type, str(design_label or ""))
        if not profile.design_verified:
            reasons.append("study design could not be deterministically classified")

        if reasons:
            return (
                StudyPromotion(
                    str(payload.get("study_id") or ""),
                    PromotionStatus.NEEDS_REVIEW,
                    tuple(dict.fromkeys(reasons)),
                    str(design_label or ""),
                ),
                None,
            )

        record = self._record_from_fields(
            payload,
            fields,
            profile,
            notes="Automatically promoted by deterministic provenance/confidence bridge",
        )
        return (
            StudyPromotion(
                record.study_id,
                PromotionStatus.VERIFIED_ELIGIBLE,
                ("high-confidence eligibility with validated critical-field provenance",),
                profile.effective_design_label,
            ),
            record,
        )

    def _record_from_fields(self, payload, fields, profile, *, notes: str) -> StudyRecord:
        return StudyRecord(
            study_id=str(payload.get("study_id") or ""),
            title=str(payload.get("title") or ""),
            design=profile,
            year=_int_value(fields, "year"),
            first_author=str(_field_value(fields, "first_author") or ""),
            doi=str(payload.get("doi") or ""),
            registry_ids=_list_value(fields, "registry_ids"),
            sample_size=_int_value(fields, "sample_size"),
            eligibility_verified=True,
            independence_verified=True,
            notes=notes,
        )


def _pair_key(study_a: str, study_b: str) -> str:
    return "||".join(sorted((str(study_a), str(study_b))))


def _pair_override(overrides: dict[str, Any], study_a: str, study_b: str) -> str:
    raw = overrides.get(_pair_key(study_a, study_b))
    return str(raw.get("resolution") or "").upper() if isinstance(raw, dict) else ""


def _fields_from_serialized_extraction(extraction: dict[str, Any]) -> dict[str, Any]:
    names = [
        "design_label",
        "population",
        "intervention_exposure_index_test",
        "comparator_reference",
        "outcomes",
        "sample_size",
        "registry_ids",
        "first_author",
        "year",
    ]
    return {name: extraction.get(name) for name in names if isinstance(extraction.get(name), dict)}


def _field_value(fields: dict[str, Any], name: str):
    field = fields.get(name)
    return field.get("value") if isinstance(field, dict) else None


def _list_value(fields: dict[str, Any], name: str) -> list[str]:
    value = _field_value(fields, name)
    if isinstance(value, list):
        return [str(x) for x in value if str(x).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _int_value(fields: dict[str, Any], name: str) -> int | None:
    value = _field_value(fields, name)
    if isinstance(value, int):
        return value
    try:
        return int(str(value)) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _float(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
