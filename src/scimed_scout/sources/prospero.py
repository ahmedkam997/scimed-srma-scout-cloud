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
    """Optional read-only adapter for the open-source PROSPERO-MCP CLI.

    The adapter never interprets an unavailable CLI or a failed command as a
    negative registry search. Public hits should still be inspected against the
    official PROSPERO record before a fatal overlap decision.
    """

    executable: str = "prospero"
    runner: Runner | None = None
    name: str = "PROSPERO"

    def search(self, query: str, *, limit: int = 20) -> SearchResult:
        if self.runner is None and shutil.which(self.executable) is None:
            return SearchResult(
                self.name,
                query,
                SourceStatus.ACCESS_FAILED,
                message="PROSPERO-MCP CLI is not installed or not on PATH.",
            )

        command = [self.executable, "search", query, "--page-size", str(min(max(1, limit), 50))]
        try:
            completed = self.runner(command) if self.runner is not None else self._run(command)
        except Exception as exc:
            return SearchResult(self.name, query, SourceStatus.ACCESS_FAILED, message=str(exc))

        if completed.returncode != 0:
            message = (completed.stderr or completed.stdout or "PROSPERO CLI failed").strip()
            return SearchResult(self.name, query, SourceStatus.ACCESS_FAILED, message=message[:1000])

        try:
            envelope = json.loads(completed.stdout)
        except Exception as exc:
            return SearchResult(self.name, query, SourceStatus.PARTIAL, message=f"Invalid PROSPERO CLI JSON: {exc}")

        if envelope.get("ok") is not True:
            return SearchResult(self.name, query, SourceStatus.ACCESS_FAILED, message=str(envelope.get("error") or "PROSPERO CLI reported failure"))

        data = envelope.get("data") or {}
        total = data.get("total_hits")
        if total is None:
            return SearchResult(self.name, query, SourceStatus.PARTIAL, message="PROSPERO CLI response missing total_hits")

        total = int(total)
        if total == 0:
            return SearchResult(self.name, query, SourceStatus.SEARCHED_NEGATIVE, total_count=0)

        records: list[SearchRecord] = []
        for hit in data.get("hits") or []:
            accession = str(hit.get("accession_number") or "")
            rid = accession or str(hit.get("record_id") or "")
            if not rid:
                continue
            records.append(
                SearchRecord(
                    self.name,
                    rid,
                    str(hit.get("title") or ""),
                    url=f"https://www.crd.york.ac.uk/PROSPERO/view/{accession}" if accession else "",
                    year=hit.get("year_first_published") if isinstance(hit.get("year_first_published"), int) else None,
                    metadata=hit,
                )
            )
        return SearchResult(self.name, query, SourceStatus.SEARCHED_POSITIVE, records, total)

    def _run(self, command: list[str]) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env.setdefault("PROSPERO_NETWORK_MODE", "online")
        return subprocess.run(command, capture_output=True, text=True, timeout=30, check=False, env=env)
