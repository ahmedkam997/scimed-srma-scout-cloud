from scripts import scimed_autonomous_worker as v1, scimed_autonomous_worker_v2 as v2

def test_dynamic_discovery_alternates_and_preserves_retry():
    s=v1.initial()
    seen=[]
    def collect(*a,**kw):
        seen.append(kw["dynamic"])
        return {"status":"ACCESS_UNRESOLVED" if len(seen)==1 else "SAMPLED",
                "candidates":[],"dynamic_discovery":{"anchors":[]}}
    first,_=v1.run(s,collect,lambda x:{})
    second,_=v1.run(s,collect,lambda x:{})
    third,_=v1.run(s,collect,lambda x:{})
    fourth,_=v1.run(s,collect,lambda x:{})
    assert seen==[True,False,True,False]
    assert first["discovery_mode"]=="dynamic" and second["discovery_mode"]=="curated"
    assert all(not x["qualification_granted"] for x in (first,second,third,fourth))

def test_early_lead_recovery_reserved_but_never_shortlisted():
    s=v1.initial()
    s["ledger"]={"strong":{"family_leads":8,"shortlist_cue":True},
                 "early":{"family_leads":3,"shortlist_cue":False}}
    ext=v2.extend(s)
    raw={"candidates":[{"candidate_id":"early","metadata":{"rct_first":{"comparison_records":[]}}}]}
    v2.seed_jobs(s,raw)
    assert "early" in ext["jobs"]
    assert v2.choose_job(s,"families")[0]=="strong"
    ext["task_counts"]["families"]=3
    assert v2.choose_job(s,"families")[0]=="early"
    assert v2.choose_job(s,"competitors")[0]=="strong"
    assert not s["ledger"]["early"]["shortlist_cue"]
    assert not s["qualification_granted"]

def test_no_strong_candidate_does_not_abandon_early_lead():
    s=v1.initial();s["ledger"]["early"]={"family_leads":2,"shortlist_cue":False}
    assert v2.choose_job(s,"families")[0]=="early"
    assert v2.choose_job(s,"competitors") is None
