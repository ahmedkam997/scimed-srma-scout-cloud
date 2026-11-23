"""Recent clinical-family cooldown is scheduling, not scientific equivalence."""
import json

from scimed_scout.ai import CandidateDiscoveryService, StaticAIProvider
from scimed_scout.storage import SQLiteLedger, ProjectRecord


def seed(comparator="Usual care", outcome="hospitalization"):
    return {"candidates": [{
        "title": f"Drug X for adult heart failure: {outcome}",
        "specialty": "Cardiology",
        "question_type": "EFFECTIVENESS",
        "review_question": f"Does Drug X reduce {outcome}?",
        "population": "Adults with heart failure",
        "intervention_exposure_index_test": "Drug X",
        "comparator_reference": comparator,
        "outcomes": [outcome],
        "eligible_designs": ["RCTs"],
        "rationale": "Focused question requiring independent verification",
        "novelty_hypothesis": "Possible new trials",
        "search_terms": ["Drug X heart failure"],
    }]}


RECENT = [{
    "title": "Drug X for adult heart failure: mortality",
    "specialty": "Cardiology",
    "question_type": "EFFECTIVENESS",
    "population": "Adults with heart failure",
    "intervention_exposure_index_test": "Drug X",
    "comparator_reference": "Usual care",
    "outcomes": ["mortality"],
    "eligible_designs": ["RCTs"],
    "checked_at": "2026-11-23T20:30:00+00:00",
    "recheck_at": "2026-11-30T20:30:00+00:00",
}]


def test_related_outcome_variant_temporarily_paused_and_explicitly_labeled(tmp_path):
    skipped=[]
    with SQLiteLedger(tmp_path / "cooldown.db") as ledger:
        ledger.upsert_project(ProjectRecord("P", "Cardiology"))
        result=CandidateDiscoveryService(
            StaticAIProvider(json.dumps(seed())), ledger
        ).generate_and_store(
            project_id="P",specialty="Cardiology",count=1,
            recent_topics=RECENT,skipped_recent=skipped,
        )
    assert result == []
    assert skipped
    assert all(x["reason"] == "RECENT_RELATED_CLINICAL_FAMILY_COOLDOWN" for x in skipped)
    assert all(x["recheck_after"] == RECENT[0]["recheck_at"] for x in skipped)


def test_different_active_comparator_remains_separate_question(tmp_path):
    skipped=[]
    with SQLiteLedger(tmp_path / "comparator.db") as ledger:
        ledger.upsert_project(ProjectRecord("P", "Cardiology"))
        result=CandidateDiscoveryService(
            StaticAIProvider(json.dumps(seed(comparator="Placebo injection"))), ledger
        ).generate_and_store(
            project_id="P", specialty="Cardiology",count=1,
            recent_topics=RECENT,skipped_recent=skipped,
        )
    assert len(result)==1
    assert skipped==[]
