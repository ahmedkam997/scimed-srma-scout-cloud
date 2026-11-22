from __future__ import annotations

import re

from scimed_scout.storage import SQLiteLedger

from .models import DiscoveryEvidenceSnapshot


def discovery_evidence_snapshot(
    ledger: SQLiteLedger,
    candidate_id: str,
) -> DiscoveryEvidenceSnapshot:
    records = ledger.list_external_evidence(candidate_id, "PRIMARY_STUDY")
    seen_doi: set[str] = set()
    seen_title: set[str] = set()
    unique = 0
    positive_sources: set[str] = set()

    for record in records:
        source = str(record.get("source") or "").strip()
        if source:
            positive_sources.add(source)

        payload = record.get("payload") or {}
        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        doi = _normalize_doi(
            payload.get("doi")
            or metadata.get("doi")
            or _external_doi(metadata)
        )
        title = _normalize_title(record.get("title"))

        duplicate = bool(
            (doi and doi in seen_doi)
            or (title and title in seen_title)
        )
        if duplicate:
            continue

        unique += 1
        if doi:
            seen_doi.add(doi)
        if title:
            seen_title.add(title)

    return DiscoveryEvidenceSnapshot(
        raw_primary_records=len(records),
        unique_primary_study_candidates=unique,
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
