from datetime import datetime, timedelta, timezone

from scimed_scout.discovery.topic_memory import is_recently_checked, recent_topic_memory
from scimed_scout.ai.models import CandidateProposal


NOW = datetime(2026, 11, 23, tzinfo=timezone.utc)


def proposal(title="Drug X for adult heart failure", *, comparator="Usual care", outcome="mortality"):
    return CandidateProposal(
        title=title,
        specialty="Cardiology",
        question_type="EFFECTIVENESS",
        review_question=f"What is the effect of Drug X compared with {comparator}?",
        population="Adults with heart failure",
        intervention_exposure_index_test="Drug X",
        comparator_reference=comparator,
        outcomes=[outcome],
        eligible_designs=["RCT"],
    )


def previous(*, status="REJECTED", age_days=2, title="Drug X for adult heart failure"):
    item = {
        "candidate_id": "C1",
        "title": title,
        "specialty": "Cardiology",
        "question_type": "EFFECTIVENESS",
        "population": "Adults with heart failure",
        "intervention_exposure_index_test": "Drug X",
        "comparator_reference": "Usual care",
        "outcomes": ["mortality"],
        "eligible_designs": ["RCT"],
        "status": status,
    }
    date = (NOW - timedelta(days=age_days)).isoformat()
    return {
        "status": "COMPLETED",
        "completed_at": date,
        "updated_at": date,
        "result_json": {"run_summary": {"topic_history": [item]}},
    }


def test_recent_same_pico_is_skipped_despite_slight_title_word_order():
    memory = recent_topic_memory([previous()], now=NOW, revisit_days=30)
    assert len(memory) == 1
    assert is_recently_checked(proposal("Adult heart failure and Drug X"), memory[0])


def test_clinically_distinct_comparator_or_outcome_is_not_suppressed():
    old = recent_topic_memory([previous()], now=NOW)[0]
    assert not is_recently_checked(proposal(comparator="Placebo"), old)
    assert not is_recently_checked(proposal(outcome="hospitalization"), old)
    assert not is_recently_checked(CandidateProposal(
        title="Drug X for adult heart failure",
        specialty="Cardiology", question_type="SAFETY_HARMS",
        review_question="What are the harms of Drug X?",
        population="Adults with heart failure",
        intervention_exposure_index_test="Drug X",
        comparator_reference="Usual care",
        outcomes=["mortality"],
    ), old)


def test_checked_topic_expires_and_returns_to_pool():
    assert recent_topic_memory([previous(age_days=2)], now=NOW, revisit_days=30)
    assert recent_topic_memory([previous(age_days=31)], now=NOW, revisit_days=30) == []
    assert recent_topic_memory([previous(age_days=1)], now=NOW, revisit_days=0) == []


def test_incomplete_source_checks_are_revisited_after_seven_days():
    recent = recent_topic_memory([previous(status="PROVISIONAL_BACKUP", age_days=4)], now=NOW, revisit_days=30)
    assert len(recent) == 1
    assert recent[0]["cooldown_days"] == 7
    assert recent_topic_memory([previous(status="PROVISIONAL_BACKUP", age_days=8)], now=NOW, revisit_days=30) == []


def test_failed_and_cancelled_runs_do_not_lock_ideas():
    bad = previous()
    for status in ("FAILED", "CANCELLED", "RUNNING"):
        assert recent_topic_memory([{**bad, "status": status}], now=NOW) == []


def test_legacy_reports_with_only_title_use_exact_title_match():
    old = previous()
    old["result_json"] = {"run_summary": {"candidate_audits": [{
        "candidate_id": "C1", "title": "Drug X for adult heart failure", "status": "REJECTED"
    }]}, "package": {"options": [], "provisional_options": []}}
    rows = recent_topic_memory([old], now=NOW)
    assert is_recently_checked(proposal(), rows[0])
    assert not is_recently_checked(proposal("Drug X for patients with chronic heart failure"), rows[0])


def test_user_selecting_shorter_cooldown_also_shortens_provisional_period():
    rows = recent_topic_memory([previous(status="PROVISIONAL_BACKUP", age_days=4)], now=NOW, revisit_days=3)
    assert rows == []
