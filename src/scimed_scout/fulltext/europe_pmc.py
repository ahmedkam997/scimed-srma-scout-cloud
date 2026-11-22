from __future__ import annotations

from typing import Any

from .chunking import parse_jats_xml
from .http import TextHTTPError, TextHttpClient
from .models import FullTextFetchResult, FullTextStatus


class EuropePMCFullTextFetcher:
    base = "https://www.ebi.ac.uk/europepmc/webservices/rest"

    def __init__(self, http: TextHttpClient | None = None):
        self.http = http or TextHttpClient()

    def fetch(self, record: dict[str, Any]) -> FullTextFetchResult:
        payload = record.get("payload") or {}
        if str(payload.get("full_text") or "").strip():
            return FullTextFetchResult(
                status=FullTextStatus.ALREADY_PRESENT,
                pmcid=_find_pmcid(record),
                source=str(payload.get("full_text_source") or "existing"),
                full_text=str(payload.get("full_text") or ""),
            )

        pmcid = _find_pmcid(record)
        if not pmcid:
            return FullTextFetchResult(
                status=FullTextStatus.NO_PMCID,
                message="No PMCID was available for official Europe PMC full-text retrieval",
            )

        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        if _flag_is_no(metadata.get("isOpenAccess")) or _flag_is_no(metadata.get("inEPMC")):
            return FullTextFetchResult(
                status=FullTextStatus.NOT_AVAILABLE,
                pmcid=pmcid,
                source="Europe PMC",
                source_url=f"{self.base}/{pmcid}/fullTextXML",
                message="Europe PMC metadata indicates that distributable full text is unavailable",
            )

        url = f"{self.base}/{pmcid}/fullTextXML"
        try:
            xml_text = self.http.get_text(url)
        except TextHTTPError as exc:
            status = FullTextStatus.NOT_AVAILABLE if exc.status_code in {403, 404} else FullTextStatus.ACCESS_FAILED
            return FullTextFetchResult(
                status=status,
                pmcid=pmcid,
                source="Europe PMC",
                source_url=url,
                message=str(exc),
            )
        except Exception as exc:
            return FullTextFetchResult(
                status=FullTextStatus.ACCESS_FAILED,
                pmcid=pmcid,
                source="Europe PMC",
                source_url=url,
                message=str(exc),
            )

        try:
            full_text, chunks = parse_jats_xml(xml_text)
        except ValueError as exc:
            return FullTextFetchResult(
                status=FullTextStatus.INVALID_CONTENT,
                pmcid=pmcid,
                source="Europe PMC",
                source_url=url,
                message=str(exc),
            )

        if len(full_text.strip()) < 200:
            return FullTextFetchResult(
                status=FullTextStatus.INVALID_CONTENT,
                pmcid=pmcid,
                source="Europe PMC",
                source_url=url,
                message="Retrieved XML did not contain enough article text",
            )

        return FullTextFetchResult(
            status=FullTextStatus.ACQUIRED,
            pmcid=pmcid,
            source="Europe PMC OA fullTextXML",
            source_url=url,
            full_text=full_text,
            chunks=chunks,
        )


def _find_pmcid(record: dict[str, Any]) -> str:
    payload = record.get("payload") or {}
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}

    direct = [
        payload.get("pmcid"), metadata.get("pmcid"), metadata.get("pmcId"),
        metadata.get("pmc_id"), record.get("source_record_id"),
    ]
    ids = metadata.get("ids")
    if isinstance(ids, dict):
        direct.extend([ids.get("pmcid"), ids.get("pmc")])

    article_ids = metadata.get("articleids") or metadata.get("articleIds")
    if isinstance(article_ids, list):
        for item in article_ids:
            if not isinstance(item, dict):
                continue
            id_type = str(item.get("idtype") or item.get("idType") or "").casefold()
            if id_type in {"pmc", "pmcid"}:
                direct.append(item.get("value") or item.get("id"))

    for value in direct:
        normalized = _normalize_pmcid(value)
        if normalized:
            return normalized
    return ""


def _normalize_pmcid(value: Any) -> str:
    raw = str(value or "").strip().upper()
    if raw.startswith("HTTPS://") or raw.startswith("HTTP://"):
        raw = raw.rstrip("/").split("/")[-1]
    if raw.startswith("PMC") and raw[3:].isdigit():
        return raw
    return ""


def _flag_is_no(value: Any) -> bool:
    return str(value or "").strip().upper() in {"N", "NO", "FALSE", "0"}
