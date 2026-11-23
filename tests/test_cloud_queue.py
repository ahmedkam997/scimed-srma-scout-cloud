import json

from scimed_scout.cloud.supabase import DiscoveryJob, SupabaseJobStore


def test_discovery_job_defaults_and_bounds():
    job = DiscoveryJob.from_row({
        "id": "J1",
        "specialty": "ALL",
        "question_type": "ALL",
        "candidate_count": 999,
        "final_options": 1,
        "min_verify": 0,
        "max_verify": 100,
        "limit_per_query": 1,
    })
    assert job.id == "J1"
    assert job.specialty == "ALL"
    assert job.question_type == "ALL"
    assert job.candidate_count == 50
    assert job.final_options == 2
    assert job.min_verify == 1
    assert job.max_verify == 30
    assert job.limit_per_query == 5


def test_supabase_job_store_claims_oldest_queued_job_with_limited_worker_token():
    requests = []

    def requester(req, timeout):
        requests.append(req)
        if req.method == "GET":
            return json.dumps([{
                "id": "J1",
                "specialty": "Radiology",
                "question_type": "DIAGNOSTIC_ACCURACY",
                "candidate_count": 12,
                "final_options": 3,
                "min_verify": 3,
                "max_verify": 10,
                "limit_per_query": 20,
            }]).encode("utf-8")

        body = json.loads(req.data.decode("utf-8"))
        return json.dumps([{
            "id": "J1",
            "specialty": "Radiology",
            "question_type": "DIAGNOSTIC_ACCURACY",
            "candidate_count": 12,
            "final_options": 3,
            "min_verify": 3,
            "max_verify": 10,
            "limit_per_query": 20,
            **body,
        }]).encode("utf-8")

    store = SupabaseJobStore(
        "https://example.supabase.co",
        "public-anon-jwt",
        "worker-secret",
        requester=requester,
    )
    job = store.claim_next()

    assert job is not None
    assert job.id == "J1"
    assert job.question_type == "DIAGNOSTIC_ACCURACY"
    assert requests[0].method == "GET"
    assert "status=eq.QUEUED" in requests[0].full_url
    assert requests[1].method == "PATCH"
    assert requests[1].headers["Authorization"] == "Bearer public-anon-jwt"
    assert requests[1].headers["Apikey"] == "public-anon-jwt"
    assert requests[1].headers["X-scimed-worker-token"] == "worker-secret"


def test_supabase_job_store_returns_idle_when_queue_empty():
    store = SupabaseJobStore(
        "https://example.supabase.co",
        "public-anon-jwt",
        "worker-secret",
        requester=lambda req, timeout: b"[]",
    )
    assert store.claim_next() is None


def test_temporary_topic_memory_queries_only_same_device_completed_jobs():
    requested = []

    def responder(req, timeout):
        requested.append(req.full_url)
        return b"[]"

    store = SupabaseJobStore(
        "https://example.supabase.co", "public-anon-jwt", "worker-token",
        requester=responder,
    )
    assert store.recent_completed_jobs(
        client_token_hash="a" * 64, revisit_days=30
    ) == []
    assert len(requested) == 1
    assert "client_token_hash=eq." in requested[0]
    assert "status=eq.COMPLETED" in requested[0]
    assert "completed_at=gte." in requested[0]
    assert store.recent_completed_jobs(client_token_hash="", revisit_days=30) == []
    assert store.recent_completed_jobs(client_token_hash="a" * 64, revisit_days=0) == []
    assert len(requested) == 1


def test_topic_memory_window_is_bounded():
    job = DiscoveryJob.from_row({"id": "J1", "revisit_days": 999})
    assert job.revisit_days == 180
    job = DiscoveryJob.from_row({"id": "J2", "revisit_days": 0})
    assert job.revisit_days == 0
