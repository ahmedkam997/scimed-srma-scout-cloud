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


def test_supabase_job_store_claims_oldest_queued_job_with_service_role():
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
        "service-secret",
        requester=requester,
    )
    job = store.claim_next()

    assert job is not None
    assert job.id == "J1"
    assert job.question_type == "DIAGNOSTIC_ACCURACY"
    assert requests[0].method == "GET"
    assert "status=eq.QUEUED" in requests[0].full_url
    assert requests[1].method == "PATCH"
    assert requests[1].headers["Authorization"] == "Bearer service-secret"
    assert requests[1].headers["Apikey"] == "service-secret"


def test_supabase_job_store_returns_idle_when_queue_empty():
    store = SupabaseJobStore(
        "https://example.supabase.co",
        "service-secret",
        requester=lambda req, timeout: b"[]",
    )
    assert store.claim_next() is None
