from urllib.parse import parse_qs,urlsplit
from scimed_scout.sources.pubmed import PubMedSource
from scimed_scout.sources.http import JsonHttpClient
from scimed_scout.domain import SourceStatus

def fixture(*,fail=False,drift=False,empty=False,broken_metadata=False):
    calls=[]
    def load(url):
        q=parse_qs(urlsplit(url).query);calls.append(q)
        if "esearch" in url:
            sort=q["sort"][0];n=int(q["retmax"][0])
            if fail and sort=="pub_date":raise RuntimeError("offline")
            ids=[] if empty else [str(i) for i in (range(1,n+1) if sort=="relevance" else range(5,5+n))]
            return {"esearchresult":{"count":"0" if empty else "11" if drift and sort=="pub_date" else "10","idlist":ids}}
        ids=q["id"][0].split(",")
        return {"result":{i:{"title":"" if broken_metadata else "Article "+i} for i in ids}}
    return PubMedSource(JsonHttpClient(loader=load,retries=0),sort="mixed"),calls

def test_mixed_budget_duplicate_and_provenance():
    c,calls=fixture();r=c.search("x",limit=6)
    assert r.status==SourceStatus.SEARCHED_POSITIVE
    assert len(r.records)==6
    assert [q["sort"][0] for q in calls if "sort" in q]==["relevance","pub_date"]
    assert sum(int(q["retmax"][0]) for q in calls if "retmax" in q)==6
    assert r.records[0].metadata["scimed_pubmed_ranks"]=={"relevance":1}
    c,_=fixture();r=c.search("x",limit=9)
    assert len(r.records)==7
    assert r.records[4].metadata["scimed_pubmed_ranks"]=={"relevance":5,"pub_date":1}

def test_mixed_failure_and_drift_never_clear_coverage():
    for flags in ({"fail":True},{"drift":True},{"broken_metadata":True}):
        c,_=fixture(**flags);r=c.search("x",limit=6)
        assert r.status==SourceStatus.PARTIAL
        assert r.records

def test_mixed_empty_requires_both_valid_zero_results():
    c,_=fixture(empty=True);assert c.search("x",limit=6).status==SourceStatus.SEARCHED_NEGATIVE
    c,_=fixture(empty=True,fail=True);assert c.search("x",limit=6).status==SourceStatus.PARTIAL
