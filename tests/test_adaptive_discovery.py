from __future__ import annotations

from scimed_scout.discovery.models import DiscoveryCandidateResult, DiscoveryEvidenceSnapshot
from scimed_scout.discovery.orchestrator import ReviewDiscoveryOrchestrator
from scimed_scout.discovery.triage import discovery_triage
from scimed_scout.domain import CandidateStatus, SourceStatus
from scimed_scout.storage import CandidateRecord, ProjectRecord, SQLiteLedger
from scimed_scout.verification.coverage import VerificationCoverage


def _candidate(i: int) -> CandidateRecord:
    return CandidateRecord(
        candidate_id=f"C{i}",
        project_id="P1",
        title=f"Focused therapy {i} in adults with heart failure",
        specialty="Cardiology",
        question_type="EFFECTIVENESS",
        population="Adults with heart failure",
        intervention_exposure_index_test=f"Focused therapy {i}",
        comparator_reference="Standard care",
        outcomes=["Hospitalization", "Mortality"],
        eligible_designs=["randomized trials"],
        review_question=f"Is focused therapy {i} effective?",
        rationale="Clinical decision uncertainty",
        novelty_hypothesis="Test whether newer trials change estimates",
        search_terms=[f"Focused therapy {i}"],
    )


def _record(cid: str, *, blocked: bool) -> DiscoveryCandidateResult:
    coverage = VerificationCoverage(
        source_statuses={
            "PROSPERO": SourceStatus.PARTIAL if blocked else SourceStatus.SEARCHED_NEGATIVE,
            "OSF Registries": SourceStatus.PARTIAL if blocked else SourceStatus.SEARCHED_NEGATIVE,
        },
        blockers=("TYPE-A: registry sources incomplete",) if blocked else (),
    )
    return DiscoveryCandidateResult(
        cid, 92, coverage,
        DiscoveryEvidenceSnapshot(7, 5, 1, ("PubMed",)),
        pending=list(coverage.blockers),
        decision="PROVISIONAL — SOURCE COVERAGE INCOMPLETE" if blocked else "REJECT — METHODOLOGICAL OVERLAP",
        candidate_status=CandidateStatus.PROVISIONAL_BACKUP if blocked else CandidateStatus.REJECTED,
    )


class ControlledOrchestrator(ReviewDiscoveryOrchestrator):
    def __init__(self, ledger, *, blocked=False):
        super().__init__(ledger, [])
        self.checked = []
        self.blocked = blocked

    def verify_candidate(self, candidate_id, *, ranking_score=0, limit_per_query=20):
        self.checked.append(candidate_id)
        return _record(candidate_id, blocked=self.blocked)


def _ledger(path):
    ledger = SQLiteLedger(path)
    ledger.upsert_project(ProjectRecord("P1", "Cardiology"))
    for i in range(8):
        ledger.upsert_candidate(_candidate(i))
    return ledger


def test_adaptive_checks_add_other_distinct_topics_after_initial_rejections(tmp_path):
    with _ledger(tmp_path / "adaptive.sqlite3") as ledger:
        engine = ControlledOrchestrator(ledger)
        run = engine.run("P1", min_verify=2, max_verify=3, final_options=2, adaptive_extra=2)
        assert len(engine.checked) == 5
        assert len(set(engine.checked)) == 5
        assert run.adaptive_deep_checks_used == 2
        assert run.adaptive_checks_skipped_reason == ""
        assert len(run.ranked) == 8
        assert len(run.verified) == 5
        assert run.final_option_candidate_ids == []


def test_systemic_registry_outage_does_not_waste_additional_ai_or_network_calls(tmp_path):
    with _ledger(tmp_path / "partial.sqlite3") as ledger:
        engine = ControlledOrchestrator(ledger, blocked=True)
        run = engine.run("P1", min_verify=2, max_verify=3, final_options=2, adaptive_extra=3)
        assert len(engine.checked) == 3
        assert run.adaptive_deep_checks_used == 0
        assert "source-coverage blockers" in run.adaptive_checks_skipped_reason
        assert len(run.verified) == 3


def test_default_discovery_budget_does_not_change_without_opt_in(tmp_path):
    with _ledger(tmp_path / "legacy.sqlite3") as ledger:
        engine = ControlledOrchestrator(ledger)
        run = engine.run("P1", min_verify=2, max_verify=3, final_options=2)
        assert len(run.verified) == 3
        assert run.adaptive_deep_checks_used == 0


def test_triage_explicitly_separates_go_refine_no_go_and_unresolved():
    good = _record("GOOD", blocked=False)
    good.candidate_status = CandidateStatus.QUALIFIED
    assert discovery_triage(good)["label"] == "GO"
    assert "INDEPENDENT_VALIDATION" in discovery_triage(good)["decision_scope"]

    rejected = _record("REJECTED", blocked=False)
    assert discovery_triage(rejected)["label"] == "NO-GO"
    assert discovery_triage(rejected)["decision_scope"].startswith("PRELIMINARY")

    unresolved = _record("UNRESOLVED", blocked=True)
    assert discovery_triage(unresolved)["label"] == "UNRESOLVED"

    refine = _record("REFINE", blocked=True)
    refine.evidence = DiscoveryEvidenceSnapshot(44, 24, 2, ("PubMed", "Europe PMC"))
    info = discovery_triage(refine, pico_fit={
        "intervention_title_matches": 0,
        "intervention_population_title_matches": 0,
    })
    assert info["label"] == "REFINE"
    assert "NOT_SCIENTIFIC_REJECTION" in info["decision_scope"]
