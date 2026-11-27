import pytest

from scripts.asreview_screening_audit import audit


def test_work_saved_uses_group_denominator_and_expanded_rows_measure_coverage():
    report = audit(
        {0: 1, 1: 1, 2: 0, 3: 0},
        {0: 0, 1: 0, 2: 2, 3: 3},
        [(2, 0), (0, 1)],
        [(2, 0), (0, 1), (1, 1)],
    )
    assert report["duplicate_groups"] == 1
    assert report["group_decisions"]["reference_positive"] == 1
    assert report["group_decisions"]["screened_at_95"] == 2
    assert report["group_decisions"]["wss95"] == pytest.approx(0.95 - 2 / 3)
    assert report["expanded_rows"]["found_positive"] == 2


def test_conflicting_duplicate_labels_fail_closed():
    with pytest.raises(ValueError, match="conflicting reference label"):
        audit({0: 1, 1: 0}, {0: 0, 1: 0}, [(0, 1)], [(0, 1), (1, 0)])


def test_missing_expanded_member_fails_closed():
    with pytest.raises(ValueError, match="do not cover all members"):
        audit({0: 1, 1: 1}, {0: 0, 1: 0}, [(0, 1)], [(0, 1)])


def test_default_ungrouped_simulation_counts_rows_hidden_by_default_export():
    report = audit(
        {0: 1, 1: 1, 2: 0},
        {0: 0, 1: 0, 2: 2},
        [(0, 1)],
        [(1, 1), (0, 1)],
        grouped=False,
    )
    assert report["exported_representative_positives"] == 1
    assert report["record_decisions"]["found_positive"] == 2
    assert report["record_decisions"]["screened_at_95"] == 2
