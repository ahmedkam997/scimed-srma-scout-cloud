from scimed_scout.discovery.query_membership_audit import classify_one,uid_query,esearch
from scimed_scout.sources.pubmed import PubMedSource
from scimed_scout.sources.http import JsonHttpClient
import pytest

def result(ids=(),ok=True,total=100,cap=50):
    return {"ids":list(ids),"ok":ok,"total":total,"cap":cap}
def checks(sample,inter):
    return [{"sample":sample,"intersection":inter}]
def test_distinguishes_query_mismatch_rank_and_access():
    b=result(["123"])
    for sample,inter,status in (
        (result(["123"]),result(["123"]),"TOP_12"),
        (result([str(x) for x in range(1,13)]+["123"]),result(["123"]),"RANK_13_TO_50"),
        (result(),result(["123"]),"MATCHED_BEYOND_50"),
        (result(),result([]),"QUERY_MISMATCH"),
        (result(ok=False),result([]),"ACCESS_UNRESOLVED"),
        (result(["123"]),result([]),"INCONSISTENT_REMOTE_RESULTS"),
        (result([],total=4),result(["123"]),"INCONSISTENT_REMOTE_RESULTS"),
    ):
        assert classify_one("123",b,checks(sample,inter))["status"]==status
    assert classify_one("123",result([]),[])["status"]=="REFERENCE_INDEX_UNRESOLVED"
def test_id_query_and_fail_closed_esearch():
    assert uid_query(["123","456","123"])=="(123[uid] OR 456[uid])"
    with pytest.raises(ValueError):uid_query(["123 OR cancer"])
    for payload in ({"esearchresult":{"count":"4","idlist":["123"]}},
                    {"esearchresult":{"count":"0","idlist":[],"errorlist":{"phrasesnotfound":["x"]}}},
                    {"esearchresult":{"count":"2","idlist":["123","123"]}}):
        c=PubMedSource(JsonHttpClient(loader=lambda _:payload,retries=0))
        assert not esearch(c,"q",50)["ok"]
def test_true_zero_and_rank_cutoff():
    c=PubMedSource(JsonHttpClient(loader=lambda _:{"esearchresult":{"count":"0","idlist":[]}},retries=0))
    assert esearch(c,"q",50)["ok"]
