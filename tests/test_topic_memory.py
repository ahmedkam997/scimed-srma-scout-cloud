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


def test_generated_drafts_in_completed_jobs_are_used_for_exploration_only():
    from scimed_scout.discovery.topic_memory import (
        recent_generated_topic_memory, recent_topic_memory,
        saturated_intervention_themes, same_intervention_theme,
        intervention_theme_tokens, filter_saturated_evidence_cues,
    )
    assert intervention_theme_tokens("Oral ketone monoester ingestion before exercise") == frozenset({
        "ketone", "monoester",
    })
    assert intervention_theme_tokens("Vitamin D3") != intervention_theme_tokens("Vitamin C")

    def archived_job(number, topic_title, population):
        at = (NOW - timedelta(days=number)).isoformat()
        return {
            "id": f"JOB-{number}",
            "status": "COMPLETED",
            "completed_at": at,
            "result_json": {
                "package": {
                    "options": [],
                    "provisional_options": [],
                    "unverified_generated_options": [{
                        "candidate_id": f"TOPIC-{number}",
                        "title": topic_title,
                        "specialty": "Cardiology",
                        "question_type": "EFFECTIVENESS",
                        "population": population,
                        "intervention_exposure_index_test": "Ketone monoester supplementation",
                        "comparator_reference": "Placebo",
                        "outcomes": ["Cardiac performance"],
                    }],
                },
                "run_summary": {"topic_history": []},
            },
        }

    jobs = [
        archived_job(1, "Ketone monoester during exercise-heat stress", "Endurance athletes"),
        archived_job(2, "Ketone monoester for cardiac output", "Heart failure patients"),
    ]
    assert recent_topic_memory(jobs, now=NOW) == []
    generated = recent_generated_topic_memory(jobs, now=NOW)
    assert len(generated) == 2
    assert all(row["role"] == "PRIOR_GENERATED_TOPIC_EXPLORATION_ONLY" for row in generated)
    themes = saturated_intervention_themes(generated)
    assert len(themes) == 1
    assert themes[0]["distinct_prior_jobs"] == 2
    new_proposal = {
        "intervention_exposure_index_test": "Oral ketone monoester ingestion prior to exercise",
    }
    assert same_intervention_theme(new_proposal, themes[0])
    seeds = [
        {"title": "Ketone monoester ingestion during exercise-heat stress", "pmid": "12"},
        {"title": "Randomized study of an atrial fibrillation treatment", "pmid": "13"},
    ]
    kept, deferred = filter_saturated_evidence_cues(seeds, themes)
    assert [row["pmid"] for row in kept] == ["13"]
    assert [row["pmid"] for row in deferred] == ["12"]


def test_exploration_saturation_requires_multiple_distinct_completed_jobs():
    from scimed_scout.discovery.topic_memory import (
        saturated_intervention_themes, recent_generated_topic_memory,
    )
    at = (NOW - timedelta(days=2)).isoformat()
    one = {
        "id": "ONLY-JOB",
        "status": "COMPLETED",
        "completed_at": at,
        "result_json": {
            "package": {
                "options": [],
                "provisional_options": [],
                "unverified_generated_options": [
                    {
                        "candidate_id": str(i),
                        "title": f"Ketone monoester analysis {i}",
                        "specialty": "Cardiology",
                        "intervention_exposure_index_test": "Ketone monoester",
                    } for i in range(4)
                ],
            },
            "run_summary": {},
        },
    }
    history = recent_generated_topic_memory([one], now=NOW)
    assert len(history) == 4
    assert saturated_intervention_themes(history) == []
    assert recent_generated_topic_memory([one], revisit_days=0, now=NOW) == []
    assert recent_generated_topic_memory([{
        **one, "completed_at": (NOW - timedelta(days=9)).isoformat(),
    }], now=NOW) == []
