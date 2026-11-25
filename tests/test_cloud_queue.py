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


def test_history_uses_small_json_projections_and_preserves_topic_memory_shape():
    from urllib.parse import urlsplit, parse_qs
    calls = []
    def responder(req, timeout):
        q = parse_qs(urlsplit(req.full_url).query)
        calls.append(q)
        return json.dumps([{
            "id": "J1", "status": "COMPLETED",
            "topic_history": [{"title": "Verified topic", "status": "PROVISIONAL_BACKUP"}],
            "generated_history": [{"title": "Generated topic"}],
        }]).encode()
    store = SupabaseJobStore("https://example.supabase.co", "anon", "worker", requester=responder)
    rows = store.recent_completed_jobs(client_token_hash="a" * 64)
    assert len(calls) == 1
    assert "topic_history:result_json->run_summary->topic_history" in calls[0]["select"][0]
    assert calls[0]["limit"] == ["5"]
    assert rows[0]["result_json"]["run_summary"]["topic_history"][0]["title"] == "Verified topic"
    assert rows[0]["result_json"]["package"]["unverified_generated_options"][0]["title"] == "Generated topic"


def test_history_timeout_reduces_page_size_and_does_not_stop_discovery():
    from urllib.parse import urlsplit, parse_qs
    calls = []
    def responder(req, timeout):
        q = parse_qs(urlsplit(req.full_url).query)
        calls.append(q["limit"][0])
        raise RuntimeError("Supabase HTTP 500: 57014 statement timeout")
    store = SupabaseJobStore("https://example.supabase.co", "anon", "worker", requester=responder)
    assert store.recent_completed_jobs(client_token_hash="a" * 64) == []
    assert calls == ["5", "2", "1"]
    assert "duplicate prevention" in store.history_warning


def test_progress_update_returns_only_id_and_retries_statement_cancellation(monkeypatch):
    from urllib.parse import parse_qs, urlsplit
    from scimed_scout.cloud import supabase
    calls = []
    monkeypatch.setattr(supabase.time, "sleep", lambda _: None)
    def responder(req, timeout):
        calls.append(parse_qs(urlsplit(req.full_url).query))
        if len(calls) == 1:
            raise RuntimeError("Supabase HTTP 500: 57014 statement timeout")
        return b'[{"id":"J1"}]'
    store = SupabaseJobStore("https://example.supabase.co", "anon", "worker", requester=responder)
    store.update_job("J1", progress=41)
    assert len(calls) == 2
    assert all(row["select"] == ["id"] for row in calls)


def test_cardio_scope_guard_excludes_pulmonary_only_questions():
    from types import SimpleNamespace
    from scimed_scout.cloud.worker import _within_specialty
    candidate = SimpleNamespace(specialty="Cardiology",
        title="Dual Bronchodilator Treatment Effects on Regional Ventilation in COPD",
        review_question="Effects on ventilation", population="Adults with COPD",
        intervention_exposure_index_test="Dual bronchodilators", outcomes=["Ventilation"])
    assert not _within_specialty(candidate, "Cardiology")
    assert _within_specialty(candidate, "ALL")
    candidate.outcomes = ["Cardiovascular mortality"]
    assert _within_specialty(candidate, "Cardiology")
