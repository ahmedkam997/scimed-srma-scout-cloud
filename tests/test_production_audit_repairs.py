from scimed_scout.discovery.adjudication import build,validate
from scimed_scout.storage import CandidateRecord
from scimed_scout.discovery.registration_enrichment import enrich_fair
from scimed_scout.sources.prospero import ProsperoCliSource
from scimed_scout.sources.clinicaltrials import ClinicalTrialsGovSource
from scimed_scout.sources.http import JsonHttpClient
from scimed_scout.domain import SourceStatus
import json,subprocess
from urllib.parse import urlparse,parse_qs

def record(i,kind="PRIMARY_STUDY"):
    return {"source":"PubMed","source_record_id":str(i),"title":"Trial report "+str(i),"evidence_type":kind,"payload":{"url":f"https://pubmed.ncbi.nlm.nih.gov/{i}/","metadata":{"pmid":str(i),"pmcid":"PMC"+str(1234500+i)}}}

def test_all_competitors_visible_and_no_qualification():
    c=CandidateRecord("c","p","Q","Cardiology")
    packet=build(c,[record(i) for i in range(1,9)],[record(i,"PUBLISHED_REVIEW") for i in range(10,100)],[])
    assert packet["competitor_count"]==90 and len(packet["primary_report_index"])==8
    a=validate(packet,packet["submission_template"])
    assert a["valid_study_rows"]==0 and a["competitors_pending"]==90 and not a["qualification_granted"]

def test_outcome_validation_rejects_double_count_invalid_events_and_wrong_scope():
    import pytest
    c=CandidateRecord("c","p","Q","Cardiology");packet=build(c,[record(i) for i in range(1,9)],[],[])
    e={"url":"https://pubmed.ncbi.nlm.nih.gov/1/","locator":"Table 2","excerpt":"Source evidence"}
    s={"study_id":"s","report_ids":["PubMed:1"],"registry_ids":[],"design":"RCT","population":"P","intervention_arm":"I","comparator_arm":"C","independence_basis":"distinct cohort","eligibility_evidence":e,"reviewers":["A","B"]}
    o={"study_id":"s","report_id":"PubMed:1","outcome":"death","definition":"all-cause","timepoint":"1 year","measure":"RR","intervention_n":20,"comparator_n":20,"intervention_events":1,"comparator_events":2,"evidence":e,"reviewers":["A","B"]}
    a=validate(packet,{"candidate_id":"c","studies":[s,{**s,"study_id":"duplicate"}],"outcomes":[o,o,{**o,"intervention_events":21}]})
    assert a["valid_study_rows"]==1 and a["studies_with_valid_outcome_rows"]==1 and len(a["errors"])==3 and not a["qualification_granted"]
    with pytest.raises(ValueError):validate(packet,{"candidate_id":"different"})

def test_fair_enrichment_rotates_and_keeps_budget():
    calls=[]
    def fail(url):calls.append(url);raise TimeoutError()
    rows=[record(i) for i in range(1,5)]
    _,a=enrich_fair(rows,fetcher=fail,max_lookups=3)
    assert a["source_calls"]==3 and len({x["pmid"] for x in a["new_attempts"]})==3
    _,b=enrich_fair(rows,fetcher=fail,max_lookups=3,previous=a)
    assert b["source_calls"]==3 and b["new_attempts"][0]["pmid"] not in {x["pmid"] for x in a["new_attempts"]}
    assert len(b["attempts"])==4 and not b["independence_confirmed"]

def test_prospero_same_scope_recovery_completes_350():
    pages=[]
    def run(cmd):
        page=int(cmd[cmd.index("--page")+1]);pages.append(page)
        hits=[{"record_id":str(i),"title":"Review"} for i in range((page-1)*50,min(350,page*50))]
        return subprocess.CompletedProcess(cmd,0,stdout=json.dumps({"ok":True,"data":{"page":page,"page_size":50,"total_hits":350,"hits":hits}}),stderr="")
    src=ProsperoCliSource(runner=run)
    assert src.search("q").status==SourceStatus.PARTIAL
    pages.clear()
    r=src.search_recovery("q")
    assert r.status==SourceStatus.SEARCHED_POSITIVE and len(r.records)==350 and pages==list(range(1,8))

def test_ctgov_same_scope_recovery_completes_784():
    calls=[]
    def load(url):
        params=parse_qs(urlparse(url).query);calls.append(params)
        size=int(params["pageSize"][0]);start=int(params.get("pageToken",["0"])[0]);end=min(start+size,784)
        return {"totalCount":784,"studies":[{"protocolSection":{"identificationModule":{"nctId":f"NCT{i+1:08d}","briefTitle":"Trial"}}} for i in range(start,end)],**({"nextPageToken":str(end)} if end<784 else {})}
    src=ClinicalTrialsGovSource(JsonHttpClient(loader=load))
    assert src.search("catheter ablation").status==SourceStatus.PARTIAL
    calls.clear()
    r=src.search_recovery("catheter ablation")
    assert len(r.records)==784 and r.status==SourceStatus.SEARCHED_POSITIVE and len(calls)==2
    assert all(x["query.term"]==["catheter ablation"] for x in calls)


def test_registry_reference_recovery_rotates_without_new_merges():
    from scimed_scout.discovery.registry_reference_suggestions import suggest
    rows=[record(i) for i in range(1,6)]
    for i in range(4):rows[i]["payload"]["metadata"]["trial_registration_id"]=f"NCT{i+1:08d}"
    calls=[]
    def lookup(n):
        calls.append(n)
        return {"protocolSection":{"identificationModule":{"nctId":n},"referencesModule":{"references":[{"type":"RESULT","pmid":"5"}] if n=="NCT00000004" else []}}}
    first=suggest(rows,lookup=lookup,max_lookups=3)
    assert not first["suggestions"] and first["remaining_registry_ids"]==1
    second=suggest(rows,lookup=lookup,max_lookups=3,previous=first)
    assert second["source_calls"]==1 and second["remaining_registry_ids"]==0
    assert second["suggestions"][0]["pmid"]=="5" and not second["automatic_merge"]
    assert len(set(calls))==4

def test_documented_mcda_unchanged_exploratory_exposed():
    from scimed_scout.discovery.opportunity_mcda import weighted_assessment,compare_assessments
    a=weighted_assessment({"clinical_importance":{"rating":5,"status":"PRELIMINARY"}})
    r=compare_assessments([("a",a)])
    row=r["scenarios"]["balanced"]["intervals"][0]
    assert row["lower"]==0 and row["upper"]==100 and row["exploratory_lower"]==15
    assert r["robust_winner"] is None and not r["qualification_granted"]


def test_registry_results_are_source_linked_without_automatic_arm_mapping():
    from scimed_scout.discovery.registry_outcomes import extract
    study={"protocolSection":{"identificationModule":{"nctId":"NCT00000001"}},"resultsSection":{"outcomeMeasuresModule":{"outcomeMeasures":[{"title":"All-cause death","timeFrame":"12 months","paramType":"COUNT_OF_PARTICIPANTS","unitOfMeasure":"participants","groups":[{"id":"OG000","title":"Group A"},{"id":"OG001","title":"Group B"}],"denoms":[{"units":"participants","counts":[{"groupId":"OG000","value":"50"},{"groupId":"OG001","value":"49"}]}],"classes":[{"categories":[{"measurements":[{"groupId":"OG000","value":"2"},{"groupId":"OG001","value":"3"},{"groupId":"UNKNOWN","value":"100"}]}]}]}]}}}
    rows=extract(study,"NCT00000001")
    assert rows[0]["measurements"][0]["value"]=="2" and len(rows[0]["measurements"])==2
    assert rows[0]["denominators"][1]["value"]=="49" and not rows[0]["pooling_allowed"]
    assert not extract(study,"NCT00000002")


def test_prospero_continuation_reuses_validated_prefix_and_rejects_drift():
    total=1110;pages=[];changed=False
    def run(cmd):
        page=int(cmd[cmd.index("--page")+1]);pages.append(page)
        ids=list(range((page-1)*50,min(total,page*50)))
        if changed and page==1:ids[0]=99999
        hits=[{"record_id":str(i),"title":"Review "+str(i)} for i in ids]
        return subprocess.CompletedProcess(cmd,0,stdout=json.dumps({"ok":True,"data":{"page":page,"page_size":50,"total_hits":total,"hits":hits}}),stderr="")
    src=ProsperoCliSource(runner=run)
    first=src.search("q")
    assert first.continuation["last_page"]==5
    pages.clear()
    second=src.search_recovery("q",checkpoint=first.continuation,previous_records=first.records)
    assert second.continuation["last_page"]==15 and len(second.records)==750
    assert pages[:2]==[1,5] and 2 not in pages and 6 in pages
    pages.clear()
    final=src.search_recovery("q",checkpoint=second.continuation,previous_records=second.records)
    assert final.status==SourceStatus.SEARCHED_POSITIVE and len(final.records)==1110
    assert final.continuation is None and len({x.record_id for x in final.records})==1110
    changed=True
    drift=src.search_recovery("q",checkpoint=first.continuation,previous_records=first.records)
    assert drift.status==SourceStatus.PARTIAL and drift.continuation is None and "boundary page changed" in drift.message


def test_no_ai_inventory_counts_selected_deferred_and_preserves_all_cached(tmp_path):
    from scimed_scout.discovery.novelty import DiscoveryNoveltyService,_assessment_hash
    from scimed_scout.storage import SQLiteLedger,ProjectRecord,CandidateRecord
    with SQLiteLedger(tmp_path/"pending.sqlite") as ledger:
        ledger.upsert_project(ProjectRecord("P","Cardiology"))
        c=CandidateRecord("C","P","Question","Cardiology",population="hypertension",intervention_exposure_index_test="renal denervation")
        ledger.upsert_candidate(c)
        for kind,total in (("PUBLISHED_REVIEW",35),("REGISTRATION",25)):
            for i in range(total):
                ledger.upsert_external_evidence("C",kind,f"{kind}-{i}",source="PubMed" if kind=="PUBLISHED_REVIEW" else "OSF Registries",title="Review "+str(i),payload={"year":2025})
        rows=ledger.list_external_evidence("C","PUBLISHED_REVIEW")
        for r in rows[-15:]:
            p=dict(r["payload"]);p["discovery_semantic_assessment"]={"unresolved":False,"overall_overlap":"LOW","record_id":r["source_record_id"]}
            p["discovery_semantic_assessment_input_hash"]=_assessment_hash(c,r)
            ledger.upsert_external_evidence("C","PUBLISHED_REVIEW",r["source_record_id"],source=r["source"],title=r["title"],payload=p)
        a=DiscoveryNoveltyService(ledger,None,max_reviews=12,max_registrations=8).assess_candidate("C")
        m=ledger.get_candidate("C").metadata
        assert m["discovery_competitor_resolved_count"]==15
        assert a["published_reviews_total_pending"]==20 and a["registrations_total_pending"]==25
        assert m["discovery_ai_competitor_analysis_deferred"] and not m["discovery_competitor_assessment_complete"]

def test_distinct_publication_aliases_cannot_count_as_separate_studies():
    from scimed_scout.discovery.adjudication import build,validate
    from scimed_scout.storage import CandidateRecord
    a=record(1);b=record(2);b["source"]="Crossref"
    a["payload"]["doi"]=b["payload"]["doi"]="10.1234/same"
    e={"url":"https://doi.org/10.1234/same","locator":"Methods","excerpt":"Source evidence"}
    s={"study_id":"s","report_ids":["PubMed:1"],"registry_ids":[],"design":"RCT","population":"P","intervention_arm":"I","comparator_arm":"C","independence_basis":"distinct cohort","eligibility_evidence":e,"reviewers":["A","B"]}
    packet=build(CandidateRecord("c","p","Q","Cardiology"),[a,b],[],[])
    result=validate(packet,{"candidate_id":"c","studies":[s,{**s,"study_id":"other","report_ids":["Crossref:2"]}]})
    assert result["valid_study_rows"]==1 and not result["qualification_granted"]

def test_competitor_variants_retained_in_packet():
    from scimed_scout.discovery.adjudication import build
    from scimed_scout.storage import CandidateRecord
    a=record(1,"PUBLISHED_REVIEW");b=record(2,"PUBLISHED_REVIEW");b["source"]="Crossref"
    b["payload"]["metadata"]["pmid"]="1"
    a["payload"]["doi"]=b["payload"]["doi"]="10.1234/same"
    packet=build(CandidateRecord("c","p","Q","Cardiology"),[],[a,b],[])
    assert packet["competitor_count"]==1 and packet["competitor_raw_record_count"]==2
    assert len(packet["competitor_index"][0]["source_variants"])==2
