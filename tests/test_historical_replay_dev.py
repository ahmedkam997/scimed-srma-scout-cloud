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
    assert r["relative_recall"] is None
    assert not r["qualification_granted"]
