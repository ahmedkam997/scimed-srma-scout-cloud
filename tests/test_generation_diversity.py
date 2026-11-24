"""Regression test for repeated Ketone Monoester discovery across cloud jobs."""
import json

from scimed_scout.ai import CandidateDiscoveryService, StaticAIProvider
from scimed_scout.storage import ProjectRecord, SQLiteLedger


def proposals():
    return {
        "candidates": [
            {
                "title": "Ketone Monoester Ingestion and Post-Exercise Cardiac Recovery Indices in Hypertensive Adults",
                "specialty": "Cardiology",
                "question_type": "EFFECTIVENESS",
                "review_question": "Does ketone monoester improve recovery in hypertensive adults?",
                "population": "Adults with stage 1 hypertension",
                "intervention_exposure_index_test": "Oral ketone monoester ingestion prior to exercise",
                "comparator_reference": "Caloric matched placebo",
                "outcomes": ["Heart rate recovery"],
                "eligible_designs": ["Randomized controlled trial"],
            },
            {
                "title": "Novel drug Z versus usual care for atrial fibrillation",
                "specialty": "Cardiology",
                "question_type": "EFFECTIVENESS",
                "review_question": "Does Drug Z reduce stroke in atrial fibrillation?",
                "population": "Adults with atrial fibrillation",
                "intervention_exposure_index_test": "Drug Z",
                "comparator_reference": "Usual care",
                "outcomes": ["Stroke"],
                "eligible_designs": ["Randomized controlled trial"],
            },
        ]
    }


def prior(job, population):
    return {
        "job_id": job, "title": f"Earlier ketone in {population}",
        "specialty": "Cardiology", "question_type": "EFFECTIVENESS",
        "population": population,
        "intervention_exposure_index_test": "Ketone monoester supplementation",
        "comparator_reference": "Placebo",
        "outcomes": ["Exercise performance"],
        "eligible_designs": ["Randomized controlled trial"],
    }


def test_repeated_theme_is_not_researched_in_third_exploration_run(tmp_path):
    history = [
        prior("JOB-A", "Endurance athletes"),
        prior("JOB-B", "Heart failure patients"),
    ]
    skipped = []
    with SQLiteLedger(tmp_path / "scout.sqlite3") as ledger:
        ledger.upsert_project(ProjectRecord("P1", "Cardiology", question_type="EFFECTIVENESS"))
        provider = StaticAIProvider(json.dumps(proposals()))
        generator = CandidateDiscoveryService(provider, ledger)
        generated = generator.generate_and_store(
            project_id="P1", specialty="Cardiology",
            question_types=["EFFECTIVENESS"], count=2,
            generated_history=history, skipped_recent=skipped,
        )
        assert [topic.title for topic in generated] == [
            "Novel drug Z versus usual care for atrial fibrillation",
        ]
        assert any(
            entry["reason"] == "RECENT_SATURATED_INTERVENTION_THEME_EXPLORATION_ONLY"
            and "Ketone Monoester" in entry["title"]
            for entry in skipped
        )


def test_one_previous_draft_does_not_ban_distinct_clinical_pico(tmp_path):
    history = [prior("JOB-A", "Endurance athletes")]
    with SQLiteLedger(tmp_path / "scout.sqlite3") as ledger:
        ledger.upsert_project(ProjectRecord("P1", "Cardiology", question_type="EFFECTIVENESS"))
        generator = CandidateDiscoveryService(
            StaticAIProvider(json.dumps(proposals())), ledger,
        )
        generated = generator.generate_and_store(
            project_id="P1", specialty="Cardiology",
            question_types=["EFFECTIVENESS"], count=2,
            generated_history=history,
        )
        assert len(generated) == 2
        assert any("Ketone Monoester" in topic.title for topic in generated)
