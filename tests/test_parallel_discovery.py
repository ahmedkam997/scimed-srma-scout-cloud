import threading
import time

from scimed_scout.discovery import ReviewDiscoveryOrchestrator
from scimed_scout.domain import SourceStatus
from scimed_scout.sources.base import SearchResult
from scimed_scout.storage import CandidateRecord, ProjectRecord, SQLiteLedger
from scimed_scout.verification.queries import build_search_plan


class BarrierSource:
    def __init__(self, name, barrier):
        self.name = name
        self.barrier = barrier
        self.calls = 0

    def search(self, query, *, limit=20):
        self.calls += 1
        if self.calls == 1:
            self.barrier.wait(timeout=2)
        return SearchResult(self.name, query, SourceStatus.SEARCHED_NEGATIVE, [], 0)


def _candidate():
    return CandidateRecord(
        candidate_id="C1",
        project_id="P1",
        title="Topic title",
        specialty="Neurology",
        question_type="PROGNOSIS",
        review_question="What predicts outcome X after disease Y?",
        population="Adults with disease Y",
        intervention_exposure_index_test="Predictor Z",
        comparator_reference="",
        outcomes=["Outcome X"],
        eligible_designs=["cohort studies"],
        search_terms=["disease Y predictor Z", "outcome X prognosis", "cohort predictor"],
    )


def test_default_search_plan_is_bounded_to_four_variants():
    plan = build_search_plan(_candidate())
    assert 1 <= len(plan.primary_queries) <= 4
    assert 1 <= len(plan.review_queries) <= 4
    assert 1 <= len(plan.registry_queries) <= 4


def test_independent_sources_start_concurrently(tmp_path):
    barrier = threading.Barrier(2)
    source_a = BarrierSource("A", barrier)
    source_b = BarrierSource("B", barrier)

    with SQLiteLedger(tmp_path / "parallel.sqlite3") as ledger:
        ledger.upsert_project(ProjectRecord("P1", "Neurology"))
        ledger.upsert_candidate(_candidate())
        orchestrator = ReviewDiscoveryOrchestrator(ledger, [source_a, source_b])

        started = time.monotonic()
        orchestrator._search_sources(
            ledger.get_candidate("C1"),
            ("A", "B"),
            ("query one",),
            evidence_type="PRIMARY_STUDY",
            purpose="test",
            limit_per_query=5,
        )
        elapsed = time.monotonic() - started

        assert source_a.calls == 1
        assert source_b.calls == 1
        assert elapsed < 2
        logs = ledger.list_search_log("C1")
        assert len(logs) == 2
        assert all(item.status == SourceStatus.SEARCHED_NEGATIVE for item in logs)
