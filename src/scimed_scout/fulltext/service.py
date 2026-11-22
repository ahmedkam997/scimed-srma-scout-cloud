from __future__ import annotations

from dataclasses import asdict
from typing import Any

from scimed_scout.storage import SQLiteLedger

from .chunking import chunk_plain_text, parse_jats_xml
from .europe_pmc import EuropePMCFullTextFetcher
from .models import FullTextAcquisitionSummary, FullTextPurpose, FullTextStatus


class FullTextAcquisitionService:
    def __init__(self, ledger: SQLiteLedger, fetcher: EuropePMCFullTextFetcher | None = None):
        self.ledger = ledger
        self.fetcher = fetcher or EuropePMCFullTextFetcher()

    def run(
        self,
        candidate_id: str,
        *,
        purpose: FullTextPurpose | str = FullTextPurpose.ALL,
        force: bool = False,
    ) -> FullTextAcquisitionSummary:
        candidate = self.ledger.get_candidate(candidate_id)
        if candidate is None:
            raise ValueError(f"Candidate not found: {candidate_id}")

        purpose = FullTextPurpose(str(purpose).upper())
        records = self.ledger.list_external_evidence(candidate_id, "PRIMARY_STUDY")
        target_ids = self._target_ids(candidate_id, records, purpose)
        counts = {status: 0 for status in FullTextStatus}
        considered = 0

        for record in records:
            study_id = str(record.get("source_record_id") or "")
            if study_id not in target_ids:
                continue
            considered += 1
            payload = dict(record.get("payload") or {})
            existing_text = str(payload.get("full_text") or "").strip()
            if existing_text and not force:
                counts[FullTextStatus.ALREADY_PRESENT] += 1
                continue

            fetch_record = record
            if force and existing_text:
                fetch_record = dict(record)
                fetch_payload = dict(payload)
                fetch_payload.pop("full_text", None)
                fetch_payload.pop("full_text_chunks", None)
                fetch_record["payload"] = fetch_payload

            result = self.fetcher.fetch(fetch_record)
            counts[result.status] += 1
            payload["full_text_acquisition"] = {
                "status": result.status.value,
                "pmcid": result.pmcid,
                "source": result.source,
                "source_url": result.source_url,
                "message": result.message,
            }
            if result.status == FullTextStatus.ACQUIRED:
                payload["full_text"] = result.full_text
                payload["full_text_chunks"] = [chunk.to_dict() for chunk in result.chunks]
                payload["full_text_source"] = result.source
                payload["full_text_pmcid"] = result.pmcid
                payload["full_text_source_url"] = result.source_url
            elif existing_text:
                # A refresh failure must never destroy previously attached evidence.
                payload["full_text"] = existing_text

            self.ledger.upsert_external_evidence(
                candidate_id,
                "PRIMARY_STUDY",
                study_id,
                source=record.get("source", ""),
                title=record.get("title", ""),
                payload=payload,
            )

        summary = FullTextAcquisitionSummary(
            candidate_id=candidate_id,
            purpose=purpose.value,
            records_considered=considered,
            acquired=counts[FullTextStatus.ACQUIRED],
            already_present=counts[FullTextStatus.ALREADY_PRESENT],
            not_available=counts[FullTextStatus.NOT_AVAILABLE],
            no_pmcid=counts[FullTextStatus.NO_PMCID],
            access_failed=counts[FullTextStatus.ACCESS_FAILED],
            invalid_content=counts[FullTextStatus.INVALID_CONTENT],
        )
        metadata = dict(candidate.metadata or {})
        metadata[f"full_text_{purpose.value.casefold()}_summary"] = asdict(summary)
        candidate.metadata = metadata
        self.ledger.upsert_candidate(candidate)
        return summary

    def attach_text(
        self,
        candidate_id: str,
        study_id: str,
        text: str,
        *,
        source_label: str = "MANUAL",
    ) -> dict[str, Any]:
        text = str(text or "").strip()
        if len(text) < 200:
            raise ValueError("Attached full text must contain at least 200 characters")

        record = next(
            (
                item for item in self.ledger.list_external_evidence(candidate_id, "PRIMARY_STUDY")
                if str(item.get("source_record_id") or "") == str(study_id)
            ),
            None,
        )
        if record is None:
            raise ValueError(f"Primary-study record not found: {study_id}")

        normalized_text = text
        chunks = []
        format_label = "TEXT"
        if text.lstrip().startswith("<"):
            try:
                normalized_text, chunks = parse_jats_xml(text)
                format_label = "JATS_XML"
            except ValueError:
                chunks = chunk_plain_text(text)
        else:
            chunks = chunk_plain_text(text)

        payload = dict(record.get("payload") or {})
        payload.update({
            "full_text": normalized_text,
            "full_text_chunks": [chunk.to_dict() for chunk in chunks],
            "full_text_source": source_label,
            "full_text_acquisition": {
                "status": FullTextStatus.MANUAL_ATTACHED.value,
                "source": source_label,
                "pmcid": payload.get("full_text_pmcid", ""),
                "source_url": "",
                "message": f"Full text attached manually as {format_label}",
            },
        })
        self.ledger.upsert_external_evidence(
            candidate_id,
            "PRIMARY_STUDY",
            str(study_id),
            source=record.get("source", ""),
            title=record.get("title", ""),
            payload=payload,
        )
        return {
            "candidate_id": candidate_id,
            "study_id": str(study_id),
            "status": FullTextStatus.MANUAL_ATTACHED.value,
            "characters": len(normalized_text),
            "chunks": len(chunks),
            "source": source_label,
            "format": format_label,
        }

    def _target_ids(self, candidate_id: str, records: list[dict], purpose: FullTextPurpose) -> set[str]:
        if purpose == FullTextPurpose.ALL:
            return {str(item.get("source_record_id") or "") for item in records}

        if purpose == FullTextPurpose.ELIGIBILITY:
            targets: set[str] = set()
            for record in records:
                payload = record.get("payload") or {}
                extraction = payload.get("study_eligibility_extraction")
                if not isinstance(extraction, dict) or str(extraction.get("eligibility") or "").upper() == "UNCERTAIN":
                    targets.add(str(record.get("source_record_id") or ""))
            return targets

        studies = self.ledger.list_payloads("studies", candidate_id)
        return {
            str(item.get("study_id") or "")
            for item in studies
            if str(item.get("promotion_status") or "") == "VERIFIED_ELIGIBLE"
        }
