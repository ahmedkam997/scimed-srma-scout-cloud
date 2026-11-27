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

def test_exact_efetch_year_is_preserved_and_not_invented():
    from scimed_scout.sources.pubmed_abstracts import parse_efetch
    from scripts.phase3_family_methods import as_row
    xml=b"""<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>12345</PMID><Article><ArticleTitle>Trial</ArticleTitle><Journal><JournalIssue><PubDate><Year>2023</Year></PubDate></JournalIssue></Journal></Article></MedlineCitation></PubmedArticle><PubmedArticle><MedlineCitation><PMID>12346</PMID><Article><ArticleTitle>Unknown date</ArticleTitle></Article></MedlineCitation></PubmedArticle></PubmedArticleSet>"""
    found,_=parse_efetch(xml,["12345","12346"])
    assert as_row("12345",found["12345"])["payload"]["year"]==2023
    assert as_row("12346",found["12346"])["payload"]["year"] is None

def test_recovered_comparison_audit_keeps_exact_scope_and_family_identity():
    from scripts.phase3_family_methods import as_row
    lead={"population":"hypertension","intervention":"renal denervation","comparator":"sham"}
    def trial(pid,nct,title="Renal denervation versus sham in hypertension: a randomized trial",year=2023):
        return as_row(pid,{"pubmed_efetch_title":title,"publication_year":year,
                           "pubmed_efetch_identity":"EXACT_PMID","pubtype":["Randomized Controlled Trial"],
                           "trial_registration_ids":[nct]})
    rows={str(i):trial(str(i),"NCT%08d"%i) for i in range(1,8)}
    rows["8"]=trial("8","NCT00000001")
    rows["9"]=trial("9","NCT00000009",title="Secondary analysis of renal denervation versus sham in hypertension")
    rows["10"]=trial("10","NCT00000010",title="Renal denervation in hypertension: a randomized trial")
    rows["11"]=trial("11","NCT00000011",year=None)
    rows["12"]=trial("12","NCT00000012")
    audit=v2.audit_recovered_comparisons(lead,rows,list(rows)[:-1])
    assert audit["family_leads"]==7 and audit["shortlist_signal"]
    assert set(audit["source_pmids"])==set(str(i) for i in range(1,9))
    assert audit["confirmed_independent_eligible_trials"] is None
    assert audit["qualification_granted"] is False
    assert not v2.audit_recovered_comparisons(lead,rows,["1","8","9","10","11"])["shortlist_signal"]

def test_explicit_receive_clause_with_numeric_population():
    from scimed_scout.discovery.rct_first import explicit_comparison
    methods="We randomly assigned 120 patients with heart failure and a left ventricular ejection fraction of more than 40% to receive dapagliflozin daily or matching placebo, in addition to usual therapy."
    assert explicit_comparison(methods,("dapagliflozin",),"placebo")
    assert not explicit_comparison(methods,("empagliflozin",),"placebo")
    shared="We randomly assigned 120 patients with heart failure and a left ventricular ejection fraction of more than 40% to receive dapagliflozin or dapagliflozin plus placebo."
    assert not explicit_comparison(shared,("dapagliflozin",),"placebo")
