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

def test_singleton_search_hypothesis_not_qualification():
    from scimed_scout.discovery.dynamic_anchors import derive
    # Synthetic original trial, exact source identity and co-occurring MeSH.
    row={"source":"PubMed","source_record_id":"123456","title":"Flecainide in atrial fibrillation: a randomized trial",
         "payload":{"year":2026,"url":"https://pubmed.ncbi.nlm.nih.gov/123456/","metadata":{
             "pubmed_efetch_identity":"EXACT_PMID","publication_types":["Randomized Controlled Trial"],
             "mesh_headings":[{"descriptor":"atrial fibrillation","qualifiers":["drug therapy"]}],
             "chemical_names":["Flecainide"],"abstractText":"Patients with atrial fibrillation were randomized."}}}
    assert derive([row],[],year=2026,allow_single=True,specialty="cardiology")==[]
    result=derive([row],[],year=2026,allow_single=True,specialty="cardiology",exploratory=True)
    assert len(result)==1 and result[0]["scope"]=="EXPLORATORY_PI_SEARCH_ONLY"
    assert result[0]["qualification_granted"] is False
    assert "comparator" not in result[0]

def test_hypothesis_cache_distinct_from_candidate_ledger():
    s=v1.initial()
    anchor={"scope":"EXPLORATORY_PI_SEARCH_ONLY","pair":["condition","treatment",[],[]],"source_reports":[{"record_id":"123456"}]}
    report,raw=v1.run(s,lambda *a,**kw:{"status":"SAMPLED","candidates":[],"dynamic_discovery":{"anchors":[anchor]}},lambda x:{})
    assert len(s["idea_hypotheses"])==1 and not s["ledger"]
    assert report["first_choice_count"]==0
    assert next(iter(s["idea_hypotheses"].values()))["qualification_granted"] is False
