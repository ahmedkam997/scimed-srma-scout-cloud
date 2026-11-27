from datetime import date
from types import SimpleNamespace

import pytest

from scimed_scout.domain import SourceStatus
from scripts.academy_benchmark import SCHEMA
from scripts.academy_replay import (
    BUDGET, RECOVERY, REGROUP, build_report, observe, paired_pubmed_retrieval, replay_external_pair,
    replay_development_pairs,
)


def test_published_controls_separate_publication_recency_from_independence():
    report = build_report()
    regroup, recovery = report["controls"]
    assert (regroup["id"], recovery["id"]) == (REGROUP, RECOVERY)
    assert "42969104" not in regroup["frames"][0]["visible_pmids"]
    assert "42969104" in regroup["frames"][1]["publication_recency"]
    assert not regroup["frames"][1]["new_family_cues"]
    assert recovery["frames"][1]["post_cutoff_flags"]["37060915"] == "PRIOR_REGISTRATION_DIFFERENT_COMPARISON"
    assert not report["qualification_granted"]


def test_year_precision_is_not_available_midyear():
    rows = [{"id": "1", "date": "2025", "families": ["X"]}]
    assert not observe(rows, date(2025, 6, 1))
    assert [row["id"] for row in observe(rows, date(2025, 12, 31))] == ["1"]


def test_retrieval_does_not_expose_reference_ids_or_exceed_budgets():
    calls = []

    def search(query, limit):
        assert "2017/10/31" in query or "[dp]" in query
        assert "30834266" not in query and "9613910" not in query
        calls.append(limit)
        return SimpleNamespace(
            status=SourceStatus.ACCESS_FAILED, records=[], total_count=None, message="Denied"
        )

    report = paired_pubmed_retrieval(SimpleNamespace(search=search))
    assert sum(calls) == 3 * BUDGET
    assert not report["resolved"]
    assert all(row["relative_recall"] is None and row["missing"] is None
               for row in report["variants"].values())


def evidence(record_id, kind, available, family=None):
    return {
        "record_id": record_id, "kind": kind, "available_on": available,
        "source_url": f"https://example.org/{record_id}", "locator": "Methods",
        "identifiers": {
            "trial_family_ids": [family] if family else [],
            "registration_ids": {
                "same-family": ["NCT12345678"], "new-family": ["NCT12345679"],
            }.get(family, []),
        },
    }


def test_reverse_replay_separates_future_labels_and_recognizes_existing_family():
    row = {
        "case_id": "case", "topic_family_id": "topic", "split": "development",
        "opportunity": "UPDATE", "index_date": "2020-01-01", "evaluation_date": "2022-01-01",
        "question": {key: key for key in ("population", "intervention", "comparator", "outcome")},
        "evidence": [
            evidence("baseline", "REVIEW", "2018-01-02"),
            evidence("followup", "REVIEW", "2021-01-02"),
            evidence("original", "STUDY", "2017-01-01", "same-family"),
            evidence("outcome", "STUDY", "2019-01-01", "same-family"),
            evidence("new-study", "STUDY", "2019-08-01", "new-family"),
            evidence("unseen", "STUDY", "2021-01-01", "future-family"),
        ],
        "reverse_replay": {
            "baseline_review_id": "baseline", "followup_review_id": "followup",
            "baseline_search_through": "2018-01-01", "followup_search_through": "2020-12-30",
            "added_report_ids": ["new-study"],
        },
    }
    manifest = {"schema": SCHEMA, "cases": [row]}
    result, = replay_development_pairs(manifest)
    assert result["observable_study_count"] == 3
    assert result["baseline_relative_report_recall"] == 1
    assert result["family_cue_relative_report_recall"] == 1
    row["split"] = "test"
    with pytest.raises(ValueError, match="accepts only train and development"):
        replay_development_pairs(manifest)



def test_published_pair_redacts_reference_identifiers_and_suppresses_partial_scores(monkeypatch):
    from scripts import academy_replay as replay

    pair = {
        "available_pairs": 1, "original_publication": date(2000, 1, 1),
        "updated_publication": date(2002, 1, 1), "baseline_pmids": {"100"},
        "followup_pmids": {"100", "200"},
    }
    monkeypatch.setattr(replay, "load_external_review_pair", lambda read: pair)

    def search(query, limit):
        assert '"2000/01/02"' in query and '"2001/12/31"' in query
        assert "200[pmid]" not in query and limit == BUDGET
        return SimpleNamespace(status=SourceStatus.PARTIAL, records=[SimpleNamespace(record_id="200")])

    report = replay_external_pair(SimpleNamespace(search=search))
    assert report["source_labelled_added_report_count"] == 1
    assert report["original_and_update_overlap_count"] == 1
    assert all(v["relative_added_report_recall"] is None for v in report["variants"].values())
    assert not report["qualification_granted"]


def test_external_review_pair_rejects_changed_source_bytes():
    assert not replay_external_pair(read=lambda _: b"Changed corpus")["source_resolved"]
