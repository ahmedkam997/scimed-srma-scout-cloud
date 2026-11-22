import json

import pytest

from scimed_scout.cloud.supabase import JobCancelled, SupabaseJobStore


def test_cancelled_job_cannot_be_overwritten_by_worker():
    requested = []

    def requester(req, timeout):
        requested.append(req)
        if req.method == "PATCH":
            return b"[]"
        return json.dumps([{"status": "CANCELLED"}]).encode("utf-8")

    store = SupabaseJobStore(
        "https://example.supabase.co",
        "public-key",
        "private-worker-token",
        requester=requester,
    )
    with pytest.raises(JobCancelled):
        store.update_job("job-1", stage="REVIEW_DISCOVERY", progress=80)
    assert requested[0].method == "PATCH"
    assert "status=in.%28QUEUED%2CRUNNING%29" in requested[0].full_url


def test_claim_skips_job_cancelled_after_queue_scan():
    def requester(req, timeout):
        if req.method == "GET":
            return json.dumps([{
                "id": "J1", "specialty": "Cardiology",
                "question_type": "ALL", "status": "QUEUED"
            }]).encode("utf-8")
        return b"[]"

    store = SupabaseJobStore(
        "https://example.supabase.co",
        "public-key",
        "private-worker-token",
        requester=requester,
    )
    assert store.claim_next() is None


def test_active_checker_rejects_cancelled_job():
    store = SupabaseJobStore(
        "https://example.supabase.co",
        "public-key",
        "private-worker-token",
        requester=lambda req, timeout: json.dumps([{"status": "CANCELLED"}]).encode("utf-8"),
    )
    with pytest.raises(JobCancelled):
        store.ensure_active("J1")
