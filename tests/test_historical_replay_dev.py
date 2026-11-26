from types import SimpleNamespace
from scripts.v2_historical_replay_dev import STRATEGIES, REFERENCE, retrieve, evaluate

def audit(status):
    return [{"status":status}]

def test_equal_budget_and_no_reference_identifiers_in_search():
    for routes in STRATEGIES.values():
        assert sum(n for _,n in routes)==100
        for query,_ in routes:
            assert "2017/10/31" in query
            assert all(pmid not in query for pmid in REFERENCE["linked_reports"])
            assert REFERENCE["review_pmid"] not in query

def test_dedup_and_search_input_only():
    class Fake:
        def search(self, query, limit):
            assert query in [q for q,_ in STRATEGIES["dual_route"]]
            return SimpleNamespace(records=[SimpleNamespace(record_id="9613910")],
                status=SimpleNamespace(value="SEARCHED_POSITIVE"), total_count=1)
    ids, rows=retrieve(Fake(), STRATEGIES["dual_route"])
    assert ids=={"9613910"} and len(rows)==2

def test_relative_recall_excludes_secondary_review_and_unlabelled_not_false_positive():
    r=evaluate({"9613910","19764857","999"},audit("SEARCHED_POSITIVE"),REFERENCE)
    assert r["reference_reports"]==12 and r["relative_recall"]==1/12
    assert r["unlabelled_retrieved"]==1 and not r["qualification_granted"]

def test_access_failure_is_unresolved_not_zero_recall():
    r=evaluate(set(),audit("ACCESS_FAILED"),REFERENCE)
    assert r["relative_recall"] is None and r["missing"] is None
    assert not r["qualification_granted"]

def test_diagnostic_separates_ranking_from_query_gap():
    from scripts.v2_historical_replay_dev import diagnose
    d=diagnose({"9613910"},{"9613910","15325833"},[{"complete":True}],REFERENCE)
    assert d["matched_but_outside_top_k"]==["15325833"]
    assert "12114036" in d["not_matching_any_query"]
    assert d["full_relative_recall"]==2/12
    d=diagnose(set(),set(),[{"complete":False}],REFERENCE)
    assert d["not_matching_any_query"] is None and d["full_relative_recall"] is None

def test_full_diagnostic_rejects_truncated_response():
    from scripts.v2_historical_replay_dev import full_id_diagnostic
    class Fake:
        base="https://example.invalid/"
        def _params(self, params): return params
        http=SimpleNamespace(get_json=lambda *args: {"esearchresult":{"count":"2","idlist":["1"]}})
    ids,audit=full_id_diagnostic(Fake(),"test")
    assert ids=={"1"} and not audit["complete"]


def test_live_entry_point_persists_unresolved_replay(tmp_path, monkeypatch):
    import json

    import pytest

    from scripts import v2_historical_replay_dev as replay

    class Unavailable:
        def search(self, query, limit):
            return SimpleNamespace(
                records=[], status=SimpleNamespace(value="ACCESS_FAILED"), total_count=None
            )

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(replay, "PubMedSource", lambda **kwargs: Unavailable())
    with pytest.raises(SystemExit, match="replay unresolved"):
        replay.main()
    report = json.loads((tmp_path / "v2-replay-dev.json").read_text())
    assert not report["all_resolved"]
    assert not report["qualification_granted"]
