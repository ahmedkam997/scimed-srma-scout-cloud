from types import SimpleNamespace

from scimed_scout.domain import SourceStatus
from scripts.academy_components import evaluate_competitors, evaluate_report_tasks, family_pair_scores


def test_missing_link_coverage_does_not_remove_pairs_from_denominator():
    expected = {"1": "a", "2": "a", "3": "b"}
    assert family_pair_scores(expected, {"1": "a", "3": "b"}) == {
        "tp": 0, "fp": 0, "fn": 1, "tn": 2,
    }
    assert family_pair_scores(expected, {"1": "a", "2": "a", "3": "a"}) == {
        "tp": 1, "fp": 2, "fn": 0, "tn": 0,
    }


def test_missing_report_keeps_outcome_references_in_denominator():
    result = evaluate_report_tasks({})
    assert result["coverage"] == "PARTIAL_OR_UNAVAILABLE"
    assert result["trial_family_linkage"]["conditional_on_retrieved"]["explicit_registration_linkage"] is None
    assert result["outcome_extraction"]["reference_primary_report_ratios"] == 4
    assert result["outcome_extraction"]["all_explicit_ratios"]["matched_reference_reports"] == 0
    assert result["outcome_extraction"]["endpoint_direction_and_usable_outcomes_verified"] is False


def test_unavailable_competitor_query_has_no_ranking_score():
    client = SimpleNamespace(search=lambda *a, **k: SimpleNamespace(
        status=SourceStatus.ACCESS_FAILED, records=[],
    ))
    assert all(
        row["comparison_at_five"] == {"lexical_baseline": None, "hybrid_bm25": None}
        for row in evaluate_competitors(client).values()
    )
