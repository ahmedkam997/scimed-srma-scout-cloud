from __future__ import annotations

from dataclasses import dataclass, field

from scimed_scout.domain import SourceStatus
from scimed_scout.sources.base import SearchRecord, SearchResult, SourceClient
from .audit import CoverageAudit, SearchLogEntry


@dataclass(slots=True)
class FirewallSourceReport:
    source: str
    status: SourceStatus
    records: list[SearchRecord] = field(default_factory=list)
    queries_run: int = 0
    messages: list[str] = field(default_factory=list)


@dataclass(slots=True)
class FirewallReport:
    sources: dict[str, FirewallSourceReport]
    audit: CoverageAudit


class NoveltyFirewall:
    def __init__(self, clients: list[SourceClient]):
        self.clients = {client.name: client for client in clients}

    def run(self, query_map: dict[str, list[str]], *, limit_per_query: int = 20) -> FirewallReport:
        entries: list[SearchLogEntry] = []
        source_reports: dict[str, FirewallSourceReport] = {}

        for source_name, queries in query_map.items():
            client = self.clients.get(source_name)
            results: list[SearchResult] = []

            if client is None:
                entries.append(SearchLogEntry(source_name, "", SourceStatus.NOT_SEARCHED, message="No configured source client"))
                source_reports[source_name] = FirewallSourceReport(source_name, SourceStatus.NOT_SEARCHED)
                continue

            for query in queries:
                result = client.search(query, limit=limit_per_query)
                results.append(result)
                entries.append(
                    SearchLogEntry(
                        source=source_name,
                        query=query,
                        status=result.status,
                        result_count=result.total_count,
                        message=result.message,
                    )
                )

            source_reports[source_name] = _aggregate(source_name, results)

        audit = CoverageAudit(entries)
        return FirewallReport(source_reports, audit)


def _aggregate(source: str, results: list[SearchResult]) -> FirewallSourceReport:
    if not results:
        return FirewallSourceReport(source, SourceStatus.NOT_SEARCHED)

    statuses = [result.status for result in results]
    records: dict[tuple[str, str], SearchRecord] = {}
    messages: list[str] = []
    for result in results:
        for record in result.records:
            records[(record.source, record.record_id)] = record
        if result.message:
            messages.append(result.message)

    if all(status == SourceStatus.ACCESS_FAILED for status in statuses):
        status = SourceStatus.ACCESS_FAILED
    elif any(status in {SourceStatus.ACCESS_FAILED, SourceStatus.PARTIAL, SourceStatus.NOT_SEARCHED} for status in statuses):
        status = SourceStatus.PARTIAL
    elif any(status == SourceStatus.SEARCHED_POSITIVE for status in statuses):
        status = SourceStatus.SEARCHED_POSITIVE
    elif all(status == SourceStatus.SEARCHED_NEGATIVE for status in statuses):
        status = SourceStatus.SEARCHED_NEGATIVE
    elif any(status == SourceStatus.MANUAL_VERIFIED for status in statuses):
        status = SourceStatus.MANUAL_VERIFIED
    else:
        status = SourceStatus.PARTIAL

    return FirewallSourceReport(source, status, list(records.values()), len(results), messages)
