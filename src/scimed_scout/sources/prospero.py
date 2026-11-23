from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import Callable

from scimed_scout.domain import SourceStatus
from .base import SearchRecord, SearchResult


Runner = Callable[[list[str]], subprocess.CompletedProcess[str]]


@dataclass(slots=True)
class ProsperoCliSource:
    """Read-only PROSPERO official registry search via pinned PROSPERO-MCP CLI.

    A paginated or failed search must NOT be treated as evidence that no
    competing protocol exists. The GitHub worker builds the pinned CLI from
    source and verifies its executable before starting discovery.
    """

    executable: str = "prospero"
    runner: Runner | None = None
    name: str = "PROSPERO"
    max_pages: int = 3

    def search(self, query: str, *, limit: int = 20) -> SearchResult:
        node_entry = os.getenv("PROSPERO_CLI_JS", "").strip() if self.runner is None else ""
        if self.runner is None and not (node_entry and os.path.isfile(node_entry)) and shutil.which(self.executable) is None:
            return SearchResult(
                self.name, query, SourceStatus.ACCESS_FAILED,
                message="PROSPERO CLI missing. Worker must build verified v0.2.2 source; not an empty registry.",
            )

        # A 50-record first page avoids needless page-turn requests on
        # focused clinical queries. PROSPERO can change result totals while
        # paginating; do not treat such changes as complete coverage.
        page_size = 50
        max_pages = min(5, max(1, self.max_pages))
        all_records: dict[str, SearchRecord] = {}
        total: int | None = None
        count_changed = False
        pages_fetched = 0
        for page in range(1, max_pages + 1):
            prefix = ["node", node_entry] if node_entry and os.path.isfile(node_entry) else [self.executable]
            command = [
                *prefix, "search", query,
                "--page", str(page), "--page-size", str(page_size),
                "--sort", "accession", "--order", "asc",
            ]
            try:
                completed = self.runner(command) if self.runner else self._run(command)
            except Exception as exc:
                return SearchResult(
                    self.name, query,
                    SourceStatus.PARTIAL if all_records else SourceStatus.ACCESS_FAILED,
                    list(all_records.values()), total,
                    message=f"PROSPERO page {page} failed: {type(exc).__name__}: {str(exc)[:180]}",
                )
            if completed.returncode != 0:
                detail = (completed.stderr or completed.stdout or "nonzero exit").strip()
                return SearchResult(
                    self.name, query,
                    SourceStatus.PARTIAL if all_records else SourceStatus.ACCESS_FAILED,
                    list(all_records.values()), total,
                    message=f"PROSPERO page {page} failed: {detail[:250]}",
                )
            try:
                envelope = json.loads(completed.stdout)
                if not isinstance(envelope, dict) or envelope.get("ok") is not True:
                    raise ValueError("CLI search returned non-success envelope")
                data = envelope["data"]
                if not isinstance(data, dict) or "total_hits" not in data:
                    raise ValueError("CLI missing PROSPERO total_hits")
                reported = int(data["total_hits"])
                if reported < 0:
                    raise ValueError("invalid negative PROSPERO total_hits")
                if total is None:
                    total = reported
                elif total != reported:
                    # A changing remote index must not discard earlier pages
                    # or be declared an exhaustive successful search.
                    count_changed = True
                    total = max(total, reported)
                hits = data.get("hits")
                if not isinstance(hits, list):
                    raise ValueError("CLI missing PROSPERO hits list")
                # A successful CLI envelope must also contain a clean
                # upstream response. A transport/index warning is not a
                # trustworthy zero-match registry search.
                note = str(data.get("raw_note") or "").strip()
                if note and any(mark in note.casefold() for mark in (
                    "error", "unavailable", "timeout", "failed", "invalid",
                )):
                    raise ValueError("upstream PROSPERO search reported an error")
            except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
                return SearchResult(
                    self.name, query, SourceStatus.PARTIAL,
                    list(all_records.values()), total,
                    message=f"PROSPERO page {page} malformed: {type(exc).__name__}: {str(exc)[:160]}",
                )

            pages_fetched += 1
            for hit in hits:
                if not isinstance(hit, dict):
                    continue
                accession = str(hit.get("accession_number") or "").strip()
                rid = accession or str(hit.get("record_id") or "").strip()
                if not rid:
                    continue
                year = hit.get("year_first_published")
                if isinstance(year, str) and year.isdigit():
                    year = int(year)
                all_records[rid] = SearchRecord(
                    source=self.name,
                    record_id=rid,
                    title=str(hit.get("title") or ""),
                    url=(f"https://www.crd.york.ac.uk/PROSPERO/view/{accession}" if accession else ""),
                    year=year if isinstance(year, int) else None,
                    metadata=hit,
                )
            if total == 0:
                if hits:
                    return SearchResult(self.name, query, SourceStatus.PARTIAL, message="PROSPERO reported zero with hits")
                return SearchResult(self.name, query, SourceStatus.SEARCHED_NEGATIVE, total_count=0,
                                    message=f"PROSPERO returned confirmed zero on page {page}")
            if not hits:
                break
            if total is not None and len(all_records) >= total:
                break

        complete = (not count_changed and total is not None and len(all_records) >= total)
        supplemental = 0
        if not complete and pages_fetched and total and (
            total > page_size * max_pages or count_changed
        ):
            # The index is too broad or changed while paginating. A bounded
            # title-only search identifies further directly relevant
            # protocols, but must never turn an incomplete ALL-field search
            # into a conclusive negative or scientific novelty clearance.
            prefix = ["node", node_entry] if node_entry and os.path.isfile(node_entry) else [self.executable]
            command = [
                *prefix, "search", query, "--field", "TI",
                "--page", "1", "--page-size", str(page_size),
                "--sort", "accession", "--order", "asc",
            ]
            try:
                reply = self.runner(command) if self.runner else self._run(command)
                if reply.returncode == 0:
                    envelope = json.loads(reply.stdout)
                    data = envelope.get("data", {}) if isinstance(envelope, dict) else {}
                    if envelope.get("ok") is True and isinstance(data, dict):
                        hits = data.get("hits")
                        note = str(data.get("raw_note") or "").casefold()
                        if isinstance(hits, list) and not any(
                            mark in note for mark in ("error", "failed", "timeout", "unavailable")
                        ):
                            for hit in hits:
                                if not isinstance(hit, dict):
                                    continue
                                accession = str(hit.get("accession_number") or "").strip()
                                rid = accession or str(hit.get("record_id") or "").strip()
                                if not rid or rid in all_records:
                                    continue
                                year = hit.get("year_first_published")
                                if isinstance(year, str) and year.isdigit():
                                    year = int(year)
                                all_records[rid] = SearchRecord(
                                    source=self.name, record_id=rid,
                                    title=str(hit.get("title") or ""),
                                    url=(f"https://www.crd.york.ac.uk/PROSPERO/view/{accession}" if accession else ""),
                                    year=year if isinstance(year, int) else None,
                                    metadata={**hit, "search_scope": "TITLE_ONLY_SUPPLEMENT"},
                                )
                                supplemental += 1
            except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
                pass
        status = SourceStatus.SEARCHED_POSITIVE if complete else SourceStatus.PARTIAL
        return SearchResult(
            self.name, query, status, list(all_records.values()), total,
            message=(
                f"PROSPERO pages checked={pages_fetched}; retrieved={len(all_records)}; "
                f"total={total}; count_changed={count_changed}; "
                f"title_only_supplemental_records={supplemental}; "
                f"{'complete response' if complete else 'additional matches not retrieved or index changed; manual verification required'}"
            ),
        )

    def _run(self, command: list[str]) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env.setdefault("PROSPERO_NETWORK_MODE", "online")
        return subprocess.run(command, capture_output=True, text=True, timeout=32, check=False, env=env)
