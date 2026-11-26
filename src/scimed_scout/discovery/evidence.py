from __future__ import annotations

import re

from scimed_scout.storage import SQLiteLedger

from .models import DiscoveryEvidenceSnapshot
from .trial_family import audit_trial_families


def discovery_evidence_snapshot(
    ledger: SQLiteLedger,
    candidate_id: str,
) -> DiscoveryEvidenceSnapshot:
    records = ledger.list_external_evidence(candidate_id, "PRIMARY_STUDY")
    from .pico_matching import _groups
    from .trial_family import registration_signals
    from .competitor_records import abstract
    positive_sources={str(r.get("source") or "").strip() for r in records if str(r.get("source") or "").strip()}
    distinct=[]
    for group in _groups(records):
        variants=group["records"]
        preferred=max(variants,key=lambda r:len(abstract(r)))
        payload=dict(preferred.get("payload") or {})
        metadata=dict(payload.get("metadata") or {})
        # Conflicting registry cues remain ambiguous rather than silently
        # disappearing when a thinner database record is encountered first.
        metadata["trial_registration_ids"]=sorted({identifier for r in variants for identifier in registration_signals(r)})
        distinct.append({**preferred,"payload":{**payload,"metadata":metadata}})

    family_audit = audit_trial_families(distinct)
    return DiscoveryEvidenceSnapshot(
        raw_primary_records=len(records),
        unique_primary_study_candidates=len(distinct),
        trial_family_audit=family_audit,
        primary_sources_with_hits=len(positive_sources),
        primary_source_names=tuple(sorted(positive_sources)),
    )


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


def _normalize_doi(value) -> str:
    raw = str(value or "").strip().casefold()
    raw = raw.removeprefix("https://doi.org/").removeprefix("http://doi.org/")
    return raw.strip().rstrip(".")


def _normalize_title(value) -> str:
    text = re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold())
    return " ".join(text.split())
