"""A failed AI provider must not discard source-backed literature leads."""
from types import SimpleNamespace

import pytest

from scimed_scout.cloud.supabase import DiscoveryJob
from scimed_scout.cloud import worker as discovery_worker
from scimed_scout.ai.providers import ProviderFailure
from scimed_scout.ai.discovery import CandidateDiscoveryService
from scimed_scout.storage import ProjectRecord, SQLiteLedger


class MemoryStore:
    def __init__(self):
        self.updates = []

    def ensure_active(self, job_id):
        pass

    def recent_completed_jobs(self, **kwargs):
        return []

    def update_job(self, job_id, **kwargs):
        self.updates.append(kwargs)


def test_pubmed_checkpoint_saved_before_unavailable_ai(monkeypatch):
    fake_provider = SimpleNamespace(
        primary=SimpleNamespace(endpoint="https://api.example/v1", model="openrouter/free", api_key="mock"),
    )
    monkeypatch.setattr(discovery_worker.FreeProviderFallback, "from_env", lambda: fake_provider)
    monkeypatch.setattr(discovery_worker, "recent_pubmed_cues", lambda *args, **kwargs: [
        {"title": "Real clinical trial from PubMed", "year": 2026, "source": "PubMed",
         "pmid": "12345", "url": "https://pubmed.ncbi.nlm.nih.gov/12345/",
         "verified_inclusion": False}
    ])
    monkeypatch.setattr(discovery_worker, "recent_review_gap_cues",
                        lambda *args, **kwargs: [])

    def fail_generation(self, **kwargs):
        raise RuntimeError("free AI unreachable")

    monkeypatch.setattr(CandidateDiscoveryService, "generate_and_store", fail_generation)
    store = MemoryStore()
    job = DiscoveryJob(id="j1", specialty="Cardiology", question_type="ALL")
    with pytest.raises(RuntimeError, match="unreachable"):
        discovery_worker.process_job(job, store)
    checkpoints = [entry["result_json"]["checkpoint"] for entry in store.updates if "result_json" in entry]
    assert len(checkpoints) == 1
    assert checkpoints[0]["verified"] is False
    assert checkpoints[0]["candidates"] == []
    assert checkpoints[0]["recent_pubmed_cues"][0]["pmid"] == "12345"


def test_two_repeated_upstream_failures_stop_wasting_free_requests(tmp_path):
    class Unavailable:
        name = "free-route"
        model = "router/free"
        calls = 0

        def complete(self, request):
            self.calls += 1
            raise ProviderFailure("openrouter-free", 503, "HTTP 503")

    provider = Unavailable()
    with SQLiteLedger(tmp_path / "unavailable.sqlite3") as ledger:
        ledger.upsert_project(ProjectRecord("P1", "Cardiology"))
        with pytest.raises(RuntimeError, match="after 2 bounded calls"):
            CandidateDiscoveryService(provider, ledger).generate_and_store(
                project_id="P1", specialty="Cardiology", count=20
            )
    assert provider.calls == 2
