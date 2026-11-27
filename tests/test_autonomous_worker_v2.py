import json
from types import SimpleNamespace
from scripts import scimed_autonomous_worker as v1
from scripts import scimed_autonomous_worker_v2 as w

def lead():
    return {"id":"RCT-X","title":"Renal denervation versus sham","population":"hypertension","intervention":"renal denervation","comparator":"sham","family_leads":9,"shortlist_cue":True,"qualification_granted":False}

def row(pid):
    return {"source":"PubMed","source_record_id":pid,"title":"Report","payload":{"metadata":{}}}

def test_migrate_v1_and_alternate_preserve_gates():
    s=v1.initial();s["cycles"]=1;s["ledger"]["RCT-X"]=lead()
    def fake_recover(state,kind,client):
        return {"task":kind,"source_status":"PARTIAL_SAMPLE"},{"source":"fixture"}
    for task in ("families","competitors"):
        result,_=w.cycle(s,None,None,recoverer=fake_recover)
        assert result["task"]==task and result["first_choice_count"]==0 and result["qualification_granted"] is False
    assert s["cycles"]==3 and s["v2"]["schema"]==2

def test_alternate_route_never_skipped():
    s=v1.initial();ext=w.extend(s);j=w.job_for(ext,"RCT-X")
    w.learn_route(ext,"families","exact",10,"SEARCHED_POSITIVE")
    w.learn_route(ext,"families","broad",1,"SEARCHED_POSITIVE")
    assert w.choose_route(ext,j,"families")=="exact"
    j["family_routes"]["exact"]={"cycle":1,"status":"SEARCHED_POSITIVE"}
    assert w.choose_route(ext,j,"families")=="broad"
    w.learn_route(ext,"families","broad",90,"PARTIAL")
    assert ext["route_stats"]["families:broad"]["n"]==1

def test_actual_recovery_preserves_ids_on_source_failure():
    s=v1.initial();s["ledger"]["RCT-X"]=lead()
    j=w.job_for(w.extend(s),"RCT-X");j["trial_ids"]=["111"]
    report,_=w.recover(s,"families",None,searcher=lambda *a:{"status":"PARTIAL","rows":[row("222")]},fetcher=lambda client,ids:({},{}))
    assert j["trial_ids"]==["111","222"] and report["new_ids"]==1 and report["qualification_granted"] is False
    s["cycles"]=8
    def failure(*a):raise OSError()
    report,_=w.recover(s,"families",None,searcher=failure,fetcher=lambda client,ids:({},{}))
    assert j["trial_ids"]==["111","222"] and report["source_status"]=="ACCESS_UNRESOLVED"

def test_competitor_pending_date_and_persist():
    s=v1.initial();s["ledger"]["RCT-X"]=lead();j=w.job_for(w.extend(s),"RCT-X")
    class Resolver:
        def resolve(self,r):return {"date":"May 2025","source_url":"https://example.org","full_text_eligibility_verified":False}
    report,_=w.recover(s,"competitors",None,searcher=lambda *a:{"status":"SEARCHED_POSITIVE","rows":[row("111"),row("222")]},fetcher=lambda c,ids:({"111":row("111")},{}),resolver=Resolver())
    assert report["methods_date_cues"]==1 and report["methods_pending"]==1
    assert j["methods"]["111"]["date_cue"]["date"]=="May 2025"
    assert report["novelty_confirmed"] is False and report["usable_trial_count"] is None

def test_learning_and_diagnostic_do_not_need_discovery():
    s=v1.initial();s["cycles"]=6
    result,_=w.cycle(s,None,None,learner=lambda *a:({"task":"learning","status":"TEST_ONLY"},{}))
    assert result["task"]=="learning"
    result,_=w.cycle(s,None,None)
    assert result["task"]=="diagnostic" and s["cycles"]==8
    assert s["v2"]["task_counts"]=={"learning":1,"diagnostic":1}

def test_cooldown_and_identifier_cap_are_explicit():
    s=v1.initial();s["ledger"]["RCT-X"]=lead();j=w.job_for(w.extend(s),"RCT-X")
    j["last_family"]=0
    j["family_routes"]={route:{"cycle":0,"status":"SEARCHED_POSITIVE"} for route in w.ROUTES}
    s["cycles"]=8;assert w.choose_job(s,"families") is None
    s["cycles"]=48;assert w.choose_job(s,"families")[0]=="RCT-X"
    ids,cap=w.union_ids([],map(str,range(1,102)))
    assert cap and len(ids)==100

def test_query_is_bounded_scope():
    row=lead()
    exact=w.query_for(row,"families","exact")
    broad=w.query_for(row,"families","broad")
    assert '"sham"[tiab]' in exact and '"sham"[tiab]' not in broad
    assert '"renal denervation"[tiab]' in exact and '"renal denervation"[tiab]' in broad
