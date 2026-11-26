import json
from types import SimpleNamespace

from scimed_scout.ai import StaticAIProvider
from scimed_scout.discovery.evidence_metrics import (
    CRITERION_WEIGHTS,
    VERSION,
    composite_score,
    evidence_metrics,
)
from scimed_scout.discovery.scoring import DiscoveryScoringService


def study(title, year):
    return {
        "title": title,
        "source_record_id": title,
        "source": "PubMed",
        "payload": {"year": year, "doi": f"10.1234/{title}"},
    }


def reviewed(overlap="HIGH", year=2021, unresolved=False, search_date=None):
    a = {
        "overall_overlap": overlap,
        "confidence": 0.95,
        "unresolved": unresolved,
        "dimensions": [
            {"name": name, "level": overlap, "evidence": "original abstract phrase"}
            for name in (
                "population", "intervention_exposure_index_test",
                "comparator_reference", "outcomes", "design_scope",
                "clinical_decision",
            )
        ],
    }
    return {
        "title": "A comparable systematic review",
        "source_record_id": "REV-1",
        "source": "PubMed",
        "payload": {"year": year, "metadata": {"last_search_date": search_date} if search_date else {}, "discovery_semantic_assessment": a},
    }


def test_no_matching_review_is_provisional_not_maximum_novelty():
    metrics = evidence_metrics([], [], [study(f"s{i}", 2024) for i in range(4)])
    assert metrics["overall_novelty"] == 4.0
    assert metrics["new_information_gain"] == 4.0
    assert metrics["information_gain_is_formal_voi"] is False
    assert metrics["method_version"] == VERSION
    assert metrics["validated_instrument"] is False


def test_high_overlap_limits_novelty_but_newer_bibliography_supports_incremental_signal():
    metrics = evidence_metrics(
        [reviewed(year=2021, search_date="2020-11-30")],
        [],
        [study(f"s{i}", 2024) for i in range(4)],
    )
    assert metrics["overall_novelty"] == 1.0
    assert metrics["clinical_question_novelty"] == 1.0
    assert metrics["new_information_gain"] == 5.0
    assert metrics["primary_records_newer_than_publication"] == 4
    assert metrics["latest_related_review_publication_year"] == 2021
    assert metrics["information_gain_status"] == "POST_DOCUMENTED_SEARCH_CUTOFF_BIBLIOGRAPHIC_PROXY"
    assert metrics["latest_related_review_search_year"] == 2020
    assert metrics["primary_records_newer_than_review_search"] == 4


def test_unresolved_comparison_never_gets_high_novelty_or_information_gain():
    metrics = evidence_metrics([reviewed(unresolved=True)], [], [study(f"s{i}", 2024) for i in range(4)])
    assert metrics["overall_novelty"] == 0.0
    assert metrics["new_information_gain"] == 0.0
    assert metrics["novelty_status"] == "NOT_ESTIMABLE"


def test_missing_primary_publication_year_blocks_new_information_gain_proxy():
    metrics = evidence_metrics([reviewed(search_date="2021-09-30")], [], [study("only_date", 2023)] + [
        study(f"no_date_{i}", None) for i in range(3)
    ])
    assert metrics["new_information_gain"] == 0.0
    assert metrics["information_gain_status"] == "NOT_ESTIMABLE_PRIMARY_DATES"


def test_our_mcda_weights_are_explicit_normalized_and_reproducible():
    assert round(sum(CRITERION_WEIGHTS.values()), 10) == 1.0
    result = composite_score(
        novelty=4,
        information_gain=4,
        clinical_importance=5,
        feasibility="HIGH",
        publication_potential=5,
    )
    assert result["publication_oriented_score"] == 89.0
    assert result["sensitivity_score_range"][0] <= 89.0
    assert result["sensitivity_score_range"][1] >= 89.0


def test_ai_made_up_novelty_and_information_gain_do_not_set_final_scores():
    mocked = {
        "design_framework_defined": True,
        "meaningful_synthesis_plausible": True,
        "clinical_question_novelty": 5,
        "overall_novelty": 5,
        "question_framework_coherent": True,
        "feasibility": "HIGH",
        "fatal_methodological_flaw": False,
        "clinical_importance": 5,
        "publication_potential": 5,
        "new_information_gain": 5,
        "publication_oriented_score": 100,
        "editorial_grade": "A",
        "rationale": "model-only score",
    }
    candidate = SimpleNamespace(
        title="Test topic", question_type="EFFECTIVENESS",
        review_question="Research question",
        population="Adults", intervention_exposure_index_test="Treatment A",
        comparator_reference="Standard care", outcomes=["mortality"],
        eligible_designs=["RCT"], rationale="Important", novelty_hypothesis="Possible",
    )
    result = DiscoveryScoringService(StaticAIProvider(json.dumps(mocked))).score(
        candidate,
        unique_primary_studies=4,
        published_review_hits=1,
        registration_hits=0,
        competitor_summary="High overlap",
        review_records=[reviewed()],
        primary_records=[study(f"s{i}", 2020) for i in range(4)],
    )
    assert result["overall_novelty"] == 1.0
    assert result["new_information_gain"] == 0.0
    assert result["publication_oriented_score"] != 100
    assert result["scoring_trace"]["score_role"].startswith("UNVALIDATED")


def test_missing_source_quotes_block_novelty_instead_of_guessing():
    record = reviewed()
    record["payload"]["discovery_semantic_assessment"]["dimensions"] = []
    metrics = evidence_metrics([record], [], [study(f"s{i}", 2024) for i in range(4)])
    assert metrics["overall_novelty"] == 0.0
    assert metrics["novelty_status"] == "NOT_ESTIMABLE"


def test_duplicate_primary_records_with_and_without_doi_are_counted_once():
    a = study("same trial", 2023)
    b = {**a, "source": "OpenAlex", "payload": {"year": 2023, "doi": ""}}
    evidence = evidence_metrics([], [], [a, b, study("distinct trial", 2024), study("third trial", 2024), study("fourth trial", 2024)])
    assert evidence["study_count_discovered_not_eligible"] == 4


def test_old_published_review_without_actual_search_date_has_no_proven_information_gain():
    metrics = evidence_metrics(
        [reviewed(year=2019)],
        [],
        [study("new_potential_trial", 2025) for _ in range(4)],
    )
    assert metrics["information_gain_status"] == "NOT_ESTIMABLE_REVIEW_SEARCH_DATE"
    assert metrics["new_information_gain"] == 0.0
    assert metrics["latest_related_review_publication_year"] == 2019
    assert metrics["latest_related_review_search_year"] is None


def test_scoring_prohibits_fake_eligible_trial_counts_from_bibliography():
    from scimed_scout.discovery.scoring import _prompt, _safe_model_rationale, SYSTEM_PROMPT
    candidate = SimpleNamespace(
        title="Ketone monoester in HFpEF", question_type="EFFECTIVENESS",
        review_question="Is ketone ingestion clinically effective in HFpEF?",
        population="Adults with HFpEF", intervention_exposure_index_test="Ketone monoester",
        comparator_reference="Placebo", outcomes=["VO2 peak"],
        eligible_designs=["RCTs"], rationale="", novelty_hypothesis="",
    )
    wording = _prompt(
        candidate, unique_primary_studies=100,
        published_review_hits=35, registration_hits=6,
        competitor_summary="Still unresolved",
    )
    assert "LEADS retrieved: 100" in wording
    assert "CONFIRMED: NOT ASSESSED" in wording
    assert "Never call the 100 bibliography records eligible" in wording
    assert "UNSCREENED LEADS" in SYSTEM_PROMPT
    bad = "The search yields 100 eligible primary studies, sufficient data for meta-analysis."
    assert "withheld" in _safe_model_rationale(bad)
    assert "100 eligible primary" not in _safe_model_rationale(bad)
    good = _safe_model_rationale("Potential clinical relevance but the evidence is uncertain.")
    assert good.startswith("PRELIMINARY MODEL OPINION")


def test_unresolved_novelty_displays_unknown_without_changing_gate_safety():
    response = {
        "design_framework_defined": True,
        "meaningful_synthesis_plausible": True,
        "question_framework_coherent": True,
        "feasibility": "HIGH",
        "fatal_methodological_flaw": False,
        "clinical_importance": 5,
        "publication_potential": 5,
        "editorial_grade": "A",
        "rationale": "90 eligible primary studies prove meta-analysis feasibility",
    }
    candidate = SimpleNamespace(
        title="Treatment question", question_type="EFFECTIVENESS",
        review_question="Research question", population="Adults",
        intervention_exposure_index_test="Drug X",
        comparator_reference="Standard care", outcomes=["mortality"],
        eligible_designs=["RCT"], rationale="", novelty_hypothesis="",
    )
    unresolved = reviewed(unresolved=True)
    result = DiscoveryScoringService(StaticAIProvider(json.dumps(response))).score(
        candidate, unique_primary_studies=90,
        published_review_hits=1, registration_hits=0,
        competitor_summary="Competing review unresolved",
        review_records=[unresolved],
        primary_records=[study("Unverified bibliographic record", 2025)],
        semantically_capped=True,
    )
    assert result["overall_novelty"] == 0
    assert result["new_information_gain"] == 0
    assert result["scoring_trace"]["display_novelty"] is None
    assert result["scoring_trace"]["display_information_gain"] is None
    assert result["scoring_trace"]["confirmed_independent_study_count"] is None
    assert result["scoring_trace"]["bibliographic_lead_count"] == 90
    assert "withheld" in result["rationale"]


def test_conflicting_doi_same_title_retains_both_reports():
    from scimed_scout.discovery.evidence_metrics import _unique_records
    a=study("same title",2023)
    b={**a,"source_record_id":"different","payload":{"year":2024,"doi":"10.1234/different"}}
    assert len(_unique_records([a,b]))==2

def test_exact_review_identity_keeps_search_provenance_atomic():
    from scimed_scout.discovery.evidence_metrics import _unique_records
    from scimed_scout.discovery.review_opportunity import _cutoff
    a=reviewed(search_date="2021-01-01")
    a["payload"]["doi"]="10.1234/review"
    b={**a,"source":"Europe PMC","payload":{"doi":"10.1234/review","year":2021,"metadata":{
        "last_search_date":"2020-11-30","search_date_evidence_quote":"We searched through 2020-11-30.","search_date_evidence_url":"https://example.org/review","search_date_evidence_level":"METHODS"}}}
    row=_unique_records([a,b])[0]
    assert _cutoff(row)["reported_date"]=="2020-11-30"
    # A title-only match must not create a source-backed cutoff.
    b["payload"].pop("doi")
    assert _cutoff(_unique_records([a,b])[0]) is None
