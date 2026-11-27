from datetime import date
from types import SimpleNamespace
import json
import pytest
from scimed_scout.discovery.pubmed_id_inventory import initial,step,next_page,acknowledge_page

def client(responses):
    it=iter(responses)
    def get(*a):
        value=next(it)
        if isinstance(value,Exception):raise value
        return {"esearchresult":value}
    return SimpleNamespace(http=SimpleNamespace(get_json=get),base="test/",_params=lambda x:x)

def test_split_resume_and_deduplicate():
    state=initial("test",date(2020,1,1),date(2020,1,4))
    c=client([{"count":"4","idlist":["1","2"]},{"count":"2","idlist":["3","4"]},{"count":"2","idlist":["1","3"]}])
    assert step(state,c,cap=2)["status"]=="SPLIT_REQUIRED"
    assert state["pending"][0]["start"]=="2020-01-03" and state["pending"][1]["end"]=="2020-01-02"
    state=json.loads(json.dumps(state))
    assert step(state,c,cap=2)["new_ids"]==2
    assert step(state,c,cap=2)["new_ids"]==1
    assert state["query_enumeration_complete"] and state["ids"]==["3","4","1"]
    assert next_page(state,2)==["3","4"]
    with pytest.raises(ValueError):acknowledge_page(state,["1"])
    acknowledge_page(state,["3","4"])
    assert next_page(state)==["1"] and not state["qualification_granted"]

def test_access_and_translation_fail_closed():
    s=initial("test",date(2020,1,1),date(2020,1,1))
    c=client([OSError(),{"count":"0","idlist":[],"warninglist":{"quotedphrasesnotfound":["x"]}},{"count":"1","idlist":[]}])
    for _ in range(3):assert step(s,c)["status"]=="ACCESS_OR_QUERY_UNRESOLVED"
    assert s["unresolved"] and not s["query_enumeration_complete"]

def test_storage_cap_never_drops_pending_interval():
    s=initial("test")
    assert step(s,client([{"count":"2","idlist":["1","2"]}]),storage_limit=1)["status"]=="STORAGE_LIMIT"
    assert s["pending"] and not s["query_enumeration_complete"] and s["ids"]==[]
    assert step(s,client([{"count":"2","idlist":["1","2"]}]),storage_limit=2)["new_ids"]==2
    assert s["query_enumeration_complete"]

def test_exact_query_hash_and_bad_ids():
    s=initial("test")
    s["query"]="changed"
    with pytest.raises(ValueError):step(s,client([]))
    s=initial("test")
    assert step(s,client([{"count":"2","idlist":["1","1"]}]))["status"]=="ACCESS_OR_QUERY_UNRESOLVED"
