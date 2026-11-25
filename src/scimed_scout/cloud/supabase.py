from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable


Requester = Callable[[urllib.request.Request, float], bytes]


class JobCancelled(RuntimeError):
    """A client cancelled a job before the next worker checkpoint."""



@dataclass(frozen=True, slots=True)
class DiscoveryJob:
    id: str
    specialty: str
    question_type: str
    candidate_count: int = 12
    final_options: int = 3
    min_verify: int = 3
    max_verify: int = 10
    limit_per_query: int = 20
    revisit_days: int = 30
    client_token_hash: str = ""

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "DiscoveryJob":
        return cls(
            id=str(row.get("id") or ""),
            specialty=str(row.get("specialty") or "ALL"),
            question_type=str(row.get("question_type") or "ALL"),
            candidate_count=_bounded_int(row.get("candidate_count"), 12, 4, 50),
            final_options=_bounded_int(row.get("final_options"), 3, 2, 10),
            min_verify=_bounded_int(row.get("min_verify"), 3, 1, 20),
            max_verify=_bounded_int(row.get("max_verify"), 10, 2, 30),
            limit_per_query=_bounded_int(row.get("limit_per_query"), 20, 5, 100),
            revisit_days=_bounded_int(row.get("revisit_days"), 30, 0, 180),
            client_token_hash=str(row.get("client_token_hash") or ""),
        )


class SupabaseJobStore:
    """Limited worker client.

    The worker uses the public anon API key plus a separate worker token.
    RLS grants that token only queue read/update access. The service-role key
    is deliberately not used by GitHub Actions.
    """

    def __init__(
        self,
        url: str,
        anon_key: str,
        worker_token: str,
        *,
        timeout: float = 30.0,
        requester: Requester | None = None,
    ):
        self.url = url.rstrip("/")
        self.anon_key = anon_key.strip()
        self.worker_token = worker_token.strip()
        self.timeout = timeout
        self.requester = requester
        self.history_warning = ""
        if not self.url or not self.anon_key or not self.worker_token:
            raise ValueError("Supabase URL, anon key, and SCIMED_WORKER_TOKEN are required")

    @classmethod
    def from_env(cls) -> "SupabaseJobStore":
        return cls(
            os.getenv("SUPABASE_URL", ""),
            os.getenv("SUPABASE_ANON_KEY", ""),
            os.getenv("SCIMED_WORKER_TOKEN", ""),
        )

    def recover_stale_jobs(self, *, max_age_minutes: int = 90) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=max_age_minutes)
        rows = self._select(
            {
                "select": "id",
                "status": "eq.RUNNING",
                "updated_at": f"lt.{cutoff.isoformat()}",
                "order": "updated_at.asc",
                "limit": "20",
            }
        )
        recovered = 0
        for row in rows:
            job_id = str(row.get("id") or "")
            if not job_id:
                continue
            try:
                self.update_job(
                    job_id,
                    status="QUEUED",
                    stage="RECOVERED",
                    progress=0,
                    message="Recovered after an interrupted worker run",
                    error_text="",
                    started_at=None,
                )
                recovered += 1
            except JobCancelled:
                continue
        return recovered

    def recent_completed_jobs(
        self, *, client_token_hash: str, revisit_days: int = 30
    ) -> list[dict[str, Any]]:
        """Query only this browser's completed topic decisions.

        The worker credential can see the queue, so the explicit owner
        predicate is essential. A missing owner token means no memory.
        """
        if len(client_token_hash) != 64 or revisit_days <= 0:
            return []
        cutoff = datetime.now(timezone.utc) - timedelta(days=min(180, revisit_days))
        # Fetch only small PICO history projections, never entire evidence
        # dossiers (which can be several MB per job). PostgREST JSON aliases
        # preserve the existing topic-memory reader's nested shape.
        filters = {
            "client_token_hash": f"eq.{client_token_hash}",
            "status": "eq.COMPLETED",
            "completed_at": f"gte.{cutoff.isoformat()}",
            "order": "completed_at.desc,id.desc",
        }
        projection = (
            "id,status,updated_at,completed_at,"
            "topic_history:result_json->run_summary->topic_history,"
            "generated_history:result_json->run_summary->generated_topic_history,"
            "drafts:result_json->package->unverified_generated_options"
        )
        output = []
        self.history_warning = ""
        offset = 0
        page_size = 5
        while offset < 80:
            try:
                rows = self._select({
                    **filters, "select": projection,
                    "limit": str(min(page_size, 80 - offset)),
                    "offset": str(offset),
                })
            except RuntimeError as exc:
                if "57014" not in str(exc) and "timeout" not in str(exc).lower():
                    raise
                if page_size > 1:
                    page_size = max(1, page_size // 2)
                    continue
                self.history_warning = "Prior topic history partially unavailable due to database timeout; duplicate prevention may be incomplete."
                break
            for row in rows:
                checked = row.get("topic_history")
                drafts = row.get("generated_history")
                if not isinstance(drafts, list):
                    drafts = row.get("drafts") or []
                if not isinstance(checked, list):
                    # Older records without a compact history need a separate
                    # legacy read. Never fetch all full reports in one request.
                    try:
                        legacy = self._select({
                            **filters, "id": f"eq.{row['id']}",
                            "select": "id,status,updated_at,completed_at,result_json",
                            "limit": "1",
                        })
                        output.extend(legacy)
                    except RuntimeError as exc:
                        if "57014" not in str(exc) and "timeout" not in str(exc).lower():
                            raise
                        self.history_warning = "Some legacy topic history could not be retrieved; duplicate prevention may be incomplete."
                    continue
                output.append({
                    "id": row.get("id"), "status": row.get("status"),
                    "updated_at": row.get("updated_at"),
                    "completed_at": row.get("completed_at"),
                    "result_json": {
                        "run_summary": {"topic_history": checked},
                        "package": {"unverified_generated_options": drafts},
                    },
                })
            offset += len(rows)
            if len(rows) < page_size:
                break
        return output

    def claim_next(self) -> DiscoveryJob | None:
        rows = self._select(
            {
                "select": "*",
                "status": "eq.QUEUED",
                "order": "created_at.asc",
                "limit": "1",
            }
        )
        if not rows:
            return None
        row = rows[0]
        job_id = str(row.get("id") or "")
        if not job_id:
            return None
        now = _utc_now()
        updated = self._patch(
            job_id,
            {
                "status": "RUNNING",
                "stage": "CLAIMED",
                "progress": 1,
                "message": "Background worker claimed this discovery job",
                "error_text": "",
                "started_at": now,
                "completed_at": None,
                "updated_at": now,
            },
            allowed_statuses=("QUEUED",),
        )
        return DiscoveryJob.from_row(updated[0]) if updated else None

    def update_job(
        self,
        job_id: str,
        *,
        status: str | None = None,
        stage: str | None = None,
        progress: int | None = None,
        message: str | None = None,
        error_text: str | None = None,
        result_json: dict[str, Any] | None = None,
        started_at: str | None | object = ...,
        completed_at: str | None | object = ...,
    ) -> None:
        payload: dict[str, Any] = {"updated_at": _utc_now()}
        if status is not None:
            payload["status"] = status
        if stage is not None:
            payload["stage"] = stage
        if progress is not None:
            payload["progress"] = max(0, min(100, int(progress)))
        if message is not None:
            payload["message"] = message
        if error_text is not None:
            payload["error_text"] = error_text[:8000]
        if result_json is not None:
            payload["result_json"] = result_json
        if started_at is not ...:
            payload["started_at"] = started_at
        if completed_at is not ...:
            payload["completed_at"] = completed_at
        updated = self._patch(job_id, payload, allowed_statuses=("QUEUED", "RUNNING"))
        if not updated:
            self.ensure_active(job_id)
            raise RuntimeError(f"Discovery job {job_id} was not writable")

    def job_status(self, job_id: str) -> str | None:
        rows = self._select({"select": "status", "id": f"eq.{job_id}", "limit": "1"})
        return str(rows[0].get("status")) if rows else None

    def ensure_active(self, job_id: str) -> None:
        status = self.job_status(job_id)
        if status == "CANCELLED":
            raise JobCancelled(f"Discovery job {job_id} was cancelled by its owner")
        if status != "RUNNING":
            raise RuntimeError(f"Discovery job {job_id} is no longer active: {status}")

    def complete(self, job_id: str, result_json: dict[str, Any], message: str) -> None:
        self.update_job(
            job_id,
            status="COMPLETED",
            stage="COMPLETE",
            progress=100,
            message=message,
            error_text="",
            result_json=result_json,
            completed_at=_utc_now(),
        )

    def fail(self, job_id: str, error_text: str) -> None:
        self.update_job(
            job_id,
            status="FAILED",
            stage="FAILED",
            message="Discovery job failed",
            error_text=error_text,
            completed_at=_utc_now(),
        )

    def _select(self, params: dict[str, str]) -> list[dict[str, Any]]:
        query = urllib.parse.urlencode(params)
        return self._request("GET", f"/rest/v1/discovery_jobs?{query}")

    def _patch(
        self,
        job_id: str,
        payload: dict[str, Any],
        *,
        allowed_statuses: tuple[str, ...] = (),
    ) -> list[dict[str, Any]]:
        params = {"id": f"eq.{job_id}"}
        if allowed_statuses:
            params["status"] = "in.(" + ",".join(allowed_statuses) + ")"
        query = urllib.parse.urlencode(params)
        return self._request(
            "PATCH",
            f"/rest/v1/discovery_jobs?{query}",
            payload,
            prefer="return=representation",
        )

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        prefer: str = "",
    ) -> list[dict[str, Any]]:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
        headers = {
            "apikey": self.anon_key,
            "Authorization": f"Bearer {self.anon_key}",
            "x-scimed-worker-token": self.worker_token,
            "Accept": "application/json",
        }
        if payload is not None:
            headers["Content-Type"] = "application/json"
        if prefer:
            headers["Prefer"] = prefer

        req = urllib.request.Request(
            f"{self.url}{path}",
            data=data,
            headers=headers,
            method=method,
        )
        try:
            raw = self.requester(req, self.timeout) if self.requester else _urlopen(req, self.timeout)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Supabase HTTP {exc.code}: {body[:1200]}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Supabase request failed: {exc}") from exc

        if not raw:
            return []
        parsed = json.loads(raw.decode("utf-8"))
        if isinstance(parsed, list):
            return parsed
        if isinstance(parsed, dict):
            return [parsed]
        raise RuntimeError("Unexpected Supabase response shape")


def _urlopen(req: urllib.request.Request, timeout: float) -> bytes:
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read()


def _bounded_int(value: Any, default: int, low: int, high: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(low, min(high, parsed))


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
